"""Отправка уведомлений в Telegram через aiogram."""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from .categories import category_name
from .kwork import PROJECTS_URL, Project

_DESCRIPTION_LIMIT = 500


def _fmt_money(amount: float) -> str:
    return f"{int(amount):,}".replace(",", " ")


def _fmt_price(project: Project) -> str:
    low = int(project.price_limit)
    high = int(project.possible_price_limit)
    if high and high != low:
        return f"{_fmt_money(low)}–{_fmt_money(high)} ₽"
    if low:
        return f"от {_fmt_money(low)} ₽"
    return "бюджет не указан"


def _link(text: str, url: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def format_project(project: Project) -> str:
    """Готовит HTML-сообщение по проекту."""
    description = project.description
    if len(description) > _DESCRIPTION_LIMIT:
        description = description[:_DESCRIPTION_LIMIT].rstrip() + "…"

    category = _link(
        category_name(project.category_id),
        f"{PROJECTS_URL}?fc={project.category_id}",
    )

    lines = [
        f"🎯 <b>{html.escape(project.name)}</b>",
        "",
        f"💰 {_fmt_price(project)}   💬 откликов: {project.offers}   👁 {project.views}",
        f"📂 {category}",
    ]
    if project.customer:
        url = project.customer_url or f"https://kwork.ru/user/{project.customer}"
        stats = []
        if project.customer_hired_percent:
            stats.append(f"нанимает {project.customer_hired_percent}%")
        if project.customer_projects:
            stats.append(f"проектов: {project.customer_projects}")
        suffix = f"  ·  {'  ·  '.join(stats)}" if stats else ""
        lines.append(f"👤 {_link(project.customer, url)}{suffix}")
    if description:
        lines.append("")
        lines.append(f"<i>{html.escape(description)}</i>")
    lines.append("")
    lines.append(f"🔗 {project.url}")
    return "\n".join(lines)


class Notifier:
    def __init__(self, token: str, chat_id: int, proxy: str = ""):
        # Прокси нужен, если api.telegram.org заблокирован (например, в РФ).
        # Формат: http://user:pass@host:port или socks5://user:pass@host:port
        session = AiohttpSession(proxy=proxy) if proxy else None
        self._bot = Bot(
            token=token,
            session=session,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True,
            ),
        )
        self._chat_id = chat_id

    async def send_project(self, project: Project) -> None:
        await self._bot.send_message(self._chat_id, format_project(project))

    async def send_text(self, text: str) -> None:
        await self._bot.send_message(self._chat_id, text)

    async def close(self) -> None:
        await self._bot.session.close()
