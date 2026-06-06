"""Загрузка и валидация настроек из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Переменная {name} должна быть числом, а не {raw!r}.")


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int
    telegram_proxy: str
    categories: list[str]
    keywords: list[str]
    exclude_keywords: list[str]
    min_budget: int
    max_offers: int
    min_hired_percent: int
    min_customer_projects: int
    poll_interval: int
    max_pages: int
    db_path: str
    log_level: str


def load_settings() -> Settings:
    """Читает .env и возвращает готовые настройки. Падает с понятной ошибкой,
    если не заполнены обязательные поля."""
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id_raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    missing = [
        name
        for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id_raw))
        if not value
    ]
    if missing:
        raise SystemExit(
            "Не заданы обязательные переменные в .env: "
            + ", ".join(missing)
            + ".\nСкопируй .env.example в .env и заполни их."
        )

    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        raise SystemExit("TELEGRAM_CHAT_ID должен быть числом (узнать: @userinfobot).")

    categories = _split_csv(os.getenv("KWORK_CATEGORIES", "41")) or ["41"]

    return Settings(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip(),
        categories=categories,
        keywords=[k.lower() for k in _split_csv(os.getenv("KEYWORDS", ""))],
        exclude_keywords=[k.lower() for k in _split_csv(os.getenv("EXCLUDE_KEYWORDS", ""))],
        min_budget=_int_env("MIN_BUDGET", 0),
        max_offers=_int_env("MAX_OFFERS", 0),
        min_hired_percent=_int_env("MIN_HIRED_PERCENT", 0),
        min_customer_projects=_int_env("MIN_CUSTOMER_PROJECTS", 0),
        poll_interval=max(_int_env("POLL_INTERVAL", 75), 15),
        max_pages=_int_env("MAX_PAGES", 0),
        db_path=os.getenv("DB_PATH", "seen.db").strip() or "seen.db",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
