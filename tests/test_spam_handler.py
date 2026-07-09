"""Integration-тесты склейки chat_member_handler (flag при муте, unflag при размуте).

Покрывают ветвление хендлера, которое юнит-тесты чистой логики не трогают:
разбор ChatMemberUpdated, фильтр по типу чата, вызовы flag/unflag_spam_user.
"""

from datetime import datetime, timezone

from telegram import (
    Update,
    Chat,
    User,
    ChatMemberUpdated,
    ChatMemberMember,
    ChatMemberRestricted,
)

from app.bot.handlers import chat_member_handler
from app.spam_flags import flag_spam_user
from app.database import get_cursor

CHAT = Chat(id=-100123, type="supergroup", title="Handler test")
SPAMMER = User(id=999, is_bot=False, first_name="Spammer")
ANTISPAM = User(id=555, is_bot=True, first_name="AntiSpam")
# PTB декодирует бессрочный мут (Bot API until_date=0) как эпоху 1970.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
WHEN = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)


def _restricted(user: User, *, can_send_messages: bool, until_date) -> ChatMemberRestricted:
    return ChatMemberRestricted(
        user=user,
        is_member=True,
        until_date=until_date,
        can_send_messages=can_send_messages,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


def _update(old_member, new_member) -> Update:
    cmu = ChatMemberUpdated(
        chat=CHAT,
        from_user=ANTISPAM,
        date=WHEN,
        old_chat_member=old_member,
        new_chat_member=new_member,
    )
    return Update(update_id=1, chat_member=cmu)


async def _is_flagged() -> bool:
    async with get_cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM spam_users WHERE chat_id = %s AND user_id = %s",
            (CHAT.id, SPAMMER.id),
        )
        return (await cur.fetchone()) is not None


async def test_handler_flags_on_indefinite_mute(db):
    """Полный бессрочный мут через хендлер → юзер помечен спамером."""
    update = _update(
        ChatMemberMember(user=SPAMMER),
        _restricted(SPAMMER, can_send_messages=False, until_date=EPOCH),
    )

    await chat_member_handler(update, None)

    assert await _is_flagged() is True


async def test_handler_unflags_on_unmute(db):
    """Возврат в member через хендлер → пометка спамера снята."""
    await flag_spam_user(
        chat_id=CHAT.id, user_id=SPAMMER.id, muted_at=WHEN,
        muted_by=ANTISPAM.id, user=SPAMMER, chat=CHAT,
    )
    assert await _is_flagged() is True

    update = _update(
        _restricted(SPAMMER, can_send_messages=False, until_date=EPOCH),
        ChatMemberMember(user=SPAMMER),
    )

    await chat_member_handler(update, None)

    assert await _is_flagged() is False


async def test_handler_ignores_temporary_mute(db):
    """Временный мут (со сроком) хендлер не считает спамом."""
    future = datetime(2999, 1, 1, tzinfo=timezone.utc)
    update = _update(
        ChatMemberMember(user=SPAMMER),
        _restricted(SPAMMER, can_send_messages=False, until_date=future),
    )

    await chat_member_handler(update, None)

    assert await _is_flagged() is False
