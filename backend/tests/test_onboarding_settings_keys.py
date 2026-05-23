"""Smoke-тест: ключи онбординга не конфликтуют с другими настройками юзера.

Phase 2 хранит флаги в users.settings JSONB плоскими ключами `onboarding_*`.
Если кто-то добавит ключ с тем же префиксом для другой цели — сломается merge.
Этот тест документирует контракт.
"""
from bot.onboarding import ALL_KEYS as ONBOARDING_KEYS

# Зарезервированные пользовательские ключи (не онбординг). Если добавишь новый
# ключ в settings — добавь сюда. Тест проверяет что префиксы не пересекаются.
USER_SETTINGS_RESERVED = {
    "silent_mode",
    "language",
    "timezone",
}


def test_onboarding_keys_use_consistent_prefix():
    """Все онбординг-ключи начинаются с onboarding_ — облегчает поиск/миграции."""
    for key in ONBOARDING_KEYS:
        assert key.startswith("onboarding_"), f"{key} не использует префикс onboarding_"


def test_onboarding_keys_dont_conflict_with_reserved():
    """Онбординг-ключи не пересекаются с другими настройками юзера."""
    overlap = set(ONBOARDING_KEYS) & USER_SETTINGS_RESERVED
    assert not overlap, f"Конфликт ключей: {overlap}"


def test_onboarding_keys_unique():
    """Внутри онбординга ключи не дублируются."""
    assert len(ONBOARDING_KEYS) == len(set(ONBOARDING_KEYS))
