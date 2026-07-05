"""Тесты чистой логики классификации мута как спам-сигнала."""

from datetime import datetime, timezone

from app.bot.spam_detection import is_spam_mute


def test_full_indefinite_mute_is_spam():
    """Полный бессрочный мут (restricted, нельзя писать, без срока) → спам-сигнал."""
    assert is_spam_mute(
        new_status="restricted",
        new_can_send_messages=False,
        new_until_date=None,
    ) is True


def test_indefinite_mute_with_epoch_sentinel_is_spam():
    """PTB кодирует бессрочный мут (Bot API until_date=0) как эпоху 1970 — тоже спам."""
    assert is_spam_mute(
        new_status="restricted",
        new_can_send_messages=False,
        new_until_date=datetime(1970, 1, 1, tzinfo=timezone.utc),
    ) is True


def test_temporary_mute_is_not_spam():
    """Временный мут (со сроком) — не спам-сигнал: антиспам мутит намертво."""
    assert is_spam_mute(
        new_status="restricted",
        new_can_send_messages=False,
        new_until_date=datetime(2999, 1, 1, tzinfo=timezone.utc),
    ) is False


def test_partial_restriction_is_not_spam():
    """Ограничили частично (писать сообщения всё ещё можно) — не спам-сигнал."""
    assert is_spam_mute(
        new_status="restricted",
        new_can_send_messages=True,
        new_until_date=None,
    ) is False


def test_ban_is_not_spam_mute():
    """Бан (kicked) — не наш сигнал: мы ловим именно мут, а не бан."""
    assert is_spam_mute(
        new_status="kicked",
        new_can_send_messages=False,
        new_until_date=None,
    ) is False


def test_normal_member_is_not_spam():
    """Обычный участник (вступил/пишет) — не спам-сигнал (регресс-гард)."""
    assert is_spam_mute(
        new_status="member",
        new_can_send_messages=None,
        new_until_date=None,
    ) is False
