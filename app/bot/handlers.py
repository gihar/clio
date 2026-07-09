"""Обработчики сообщений Telegram бота."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError

from ..config import get_config
from ..ingest import save_message
from ..join_request_status import JoinRequestStatus
from ..join_requests import (
    save_join_request_fields,
    get_pending_fresh_join_requests,
    mark_join_requests_status,
)
from ..spam_flags import flag_spam_user, unflag_spam_user
from .spam_detection import is_spam_mute, is_unmute

logger = logging.getLogger(__name__)
_clean_join_requests_lock = asyncio.Lock()


def _is_expired_join_request_error(text: str) -> bool:
    t = (text or "").lower()
    return any(
        needle in t
        for needle in (
            "chat_join_request_not_found",
            "join request not found",
            "user_already_participant",
            "user already participant",
            "user is already a participant",
            "user_not_found",
        )
    )


def _sanitize_one_line(text: str) -> str:
    return (text or "").replace("\n", " ").replace("\r", " ").strip()


def _append_log_line(fp, line: str) -> None:
    fp.write(line + "\n")
    fp.flush()


async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect chat join requests into DB (only for VIBECODER_CHAT_ID)."""
    req = update.chat_join_request
    if not req:
        return

    cfg = get_config()
    if not cfg.vibecoder_chat_id:
        logger.warning("VIBECODER_CHAT_ID is not set; ignoring join request")
        return

    if req.chat.id != cfg.vibecoder_chat_id:
        return

    user = req.from_user
    try:
        await save_join_request_fields(
            user_id=user.id,
            chat_id=req.chat.id,
            username=user.username,
            first_name=user.first_name,
            bio=req.bio,
            request_date=req.date,
            user=user,
            chat=req.chat,
        )
        logger.info(f"Saved join request: chat_id={req.chat.id} user_id={user.id}")
    except Exception as e:
        logger.error(f"Failed to save join request: chat_id={req.chat.id} user_id={user.id} err={e}")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик новых сообщений."""
    msg = update.effective_message
    
    if not msg:
        return
    
    # Только групповые чаты
    if msg.chat.type not in ['group', 'supergroup']:
        logger.debug(f"Ignoring message from non-group chat: {msg.chat.type}")
        return
    
    # Должен быть автор
    if not msg.from_user:
        logger.debug("Ignoring message without from_user")
        return
    
    try:
        await save_message(msg, is_edit=False)
        logger.info(
            f"Saved message {msg.message_id} from {msg.from_user.id} "
            f"in chat {msg.chat_id} ({msg.chat.title or 'No title'})"
        )
    except Exception as e:
        logger.error(f"Failed to save message {msg.message_id}: {e}")


async def edited_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик отредактированных сообщений."""
    msg = update.edited_message
    
    if not msg:
        return
    
    # Только групповые чаты
    if msg.chat.type not in ['group', 'supergroup']:
        return
    
    if not msg.from_user:
        return
    
    try:
        await save_message(msg, is_edit=True)
        logger.info(
            f"Updated edited message {msg.message_id} in chat {msg.chat_id}"
        )
    except Exception as e:
        logger.error(f"Failed to update message {msg.message_id}: {e}")


async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловит действия над участниками: полный бессрочный мут → пометка спамера.

    Антиспам-бот мутит спамера намертво (restrictChatMember без прав писать,
    без срока). Это событие — наш сигнал «спамер»; его сообщения после этого
    исключаются из аналитических выборок (дайджест/стратегия).
    """
    cmu = update.chat_member
    if not cmu:
        return

    chat = cmu.chat
    if chat.type not in ("group", "supergroup"):
        return

    new = cmu.new_chat_member
    old = cmu.old_chat_member
    # can_send_messages / until_date есть только у ChatMemberRestricted;
    # у остальных статусов их нет → getattr вернёт None.
    new_can_send = getattr(new, "can_send_messages", None)
    new_until = getattr(new, "until_date", None)
    old_can_send = getattr(old, "can_send_messages", None)
    old_until = getattr(old, "until_date", None)
    target = new.user

    if is_spam_mute(new.status, new_can_send, new_until):
        muted_by = cmu.from_user.id if cmu.from_user else None
        try:
            await flag_spam_user(
                chat_id=chat.id,
                user_id=target.id,
                muted_at=cmu.date,
                muted_by=muted_by,
                user=target,
                chat=chat,
            )
            logger.info(
                f"Flagged spam user {target.id} in chat {chat.id} "
                f"({chat.title or 'No title'}), muted_by={muted_by}"
            )
        except Exception as e:
            logger.error(
                f"Failed to flag spam user {target.id} in chat {chat.id}: {e}"
            )
    elif is_unmute(
        old.status, old_can_send, old_until,
        new.status, new_can_send, new_until,
    ):
        try:
            await unflag_spam_user(chat_id=chat.id, user_id=target.id)
            logger.info(
                f"Unflagged spam user {target.id} in chat {chat.id} "
                f"({chat.title or 'No title'}) after unmute"
            )
        except Exception as e:
            logger.error(
                f"Failed to unflag spam user {target.id} in chat {chat.id}: {e}"
            )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок бота."""
    logger.error(f"Update {update} caused error: {context.error}")


async def process_pending_fresh_join_requests(
    bot,
    chat_id: int,
    threshold: int,
    limit: int,
    log_path: str,
) -> tuple[int, int]:
    """Decline pending 'fresh' join requests and log results.

    Returns: (declined_count, processed_count)
    """
    pending = await get_pending_fresh_join_requests(chat_id, threshold, limit)
    processed = len(pending)
    declined = 0

    if processed == 0:
        return 0, 0

    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("a", encoding="utf-8") as fp:
        for req in pending:
            req_id = int(req["id"])
            user_id = int(req["user_id"])
            username = req.get("username") or ""
            first_name = req.get("first_name") or ""

            outcome = "error"
            err_msg = ""
            try:
                await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
                await mark_join_requests_status([req_id], JoinRequestStatus.DECLINED)
                declined += 1
                outcome = JoinRequestStatus.DECLINED
            except BadRequest as e:
                err_msg = f"{type(e).__name__}: {e}"
                if _is_expired_join_request_error(str(e)):
                    await mark_join_requests_status([req_id], JoinRequestStatus.EXPIRED)
                    outcome = JoinRequestStatus.EXPIRED
            except TelegramError as e:
                err_msg = f"{type(e).__name__}: {e}"
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"

            ts = datetime.now(timezone.utc).isoformat()
            line = (
                f"{ts}\t{outcome}\trequest_id={req_id}\tchat_id={chat_id}\tuser_id={user_id}\t"
                f"username={_sanitize_one_line(username)}\tfirst_name={_sanitize_one_line(first_name)}\t"
                f"message={_sanitize_one_line(err_msg)}"
            )
            _append_log_line(fp, line)
            logger.info(line)

    return declined, processed


async def clean_join_requests_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue: periodically decline fresh pending join requests."""
    if _clean_join_requests_lock.locked():
        return

    async with _clean_join_requests_lock:
        cfg = get_config()
        if not cfg.vibecoder_chat_id:
            return

        declined, processed = await process_pending_fresh_join_requests(
            context.bot,
            cfg.vibecoder_chat_id,
            cfg.fresh_account_id_threshold,
            cfg.join_request_clean_batch_limit,
            cfg.declined_requests_log_path,
        )
        if processed:
            logger.info(f"Declined {declined}/{processed} pending requests")
