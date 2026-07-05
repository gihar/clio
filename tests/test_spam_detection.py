"""Тесты чистой логики классификации мута как спам-сигнала."""

from datetime import datetime, timezone

from app.bot.spam_detection import is_spam_mute, is_unmute


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


def test_unmute_from_full_mute_to_member():
    """Был полный бессрочный мут → стал обычный участник → это размут."""
    assert is_unmute(
        old_status="restricted",
        old_can_send_messages=False,
        old_until_date=None,
        new_status="member",
        new_can_send_messages=None,
        new_until_date=None,
    ) is True


def test_not_unmute_when_was_never_muted():
    """Обычный участник, который не был замучен, — не размут (нечего снимать)."""
    assert is_unmute(
        old_status="member",
        old_can_send_messages=None,
        old_until_date=None,
        new_status="member",
        new_can_send_messages=None,
        new_until_date=None,
    ) is False


def test_not_unmute_when_banned_after_mute():
    """Был мут → забанили (kicked): не размут — пометку спамера оставляем."""
    assert is_unmute(
        old_status="restricted",
        old_can_send_messages=False,
        old_until_date=None,
        new_status="kicked",
        new_can_send_messages=None,
        new_until_date=None,
    ) is False


def test_not_unmute_when_still_muted():
    """Мут → всё ещё полный мут: не размут (регресс-гард)."""
    from datetime import datetime as _dt, timezone as _tz
    assert is_unmute(
        old_status="restricted",
        old_can_send_messages=False,
        old_until_date=None,
        new_status="restricted",
        new_can_send_messages=False,
        new_until_date=_dt(2999, 1, 1, tzinfo=_tz.utc),
    ) is False


def test_unmute_when_restriction_relaxed_to_can_send():
    """Мут → частичное ограничение, но писать снова можно → размут (регресс-гард)."""
    assert is_unmute(
        old_status="restricted",
        old_can_send_messages=False,
        old_until_date=None,
        new_status="restricted",
        new_can_send_messages=True,
        new_until_date=None,
    ) is True
