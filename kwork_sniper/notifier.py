"""Отправка и обновление уведомлений в Telegram через aiogram."""

from __future__ import annotations

import html
from datetime import datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .categories import category_name
from .kwork import PROJECTS_URL, Project

# Описание не режем; обрезаем только если карточка грозит выйти за лимит Telegram.
_MAX_DESCRIPTION = 3500


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


def _buyer_lines(project: Project) -> list[str]:
    """Блок о покупателе (2 строки): имя + статус, затем цифры."""
    if not project.customer:
        return []
    url = project.customer_url or f"https://kwork.ru/user/{project.customer}"
    badge = f" [{html.escape(project.customer_tier)}]" if project.customer_tier else ""
    if project.customer_is_super:
        badge += " 💎"

    stats = [f"проектов {project.customer_projects}", f"нанимает {project.customer_hired_percent}%"]
    if project.customer_years:
        stats.append(f"{project.customer_years}+ лет")
    return [
        f"👤 {_link(project.customer, url)}{badge}",
        f"📊 {' · '.join(stats)}",
    ]


def _refresh_kb(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data=f"upd:{project_id}")]]
    )


def _body_lines(project: Project, *, expandable_desc: bool) -> list[str]:
    lines = [
        f"🎯 <b>{html.escape(project.name)}</b>",
        "",
        f"💰 {_fmt_price(project)}   💬 откликов: {project.offers}   👁 {project.views}",
        f"📂 {_link(category_name(project.category_id), f'{PROJECTS_URL}?fc={project.category_id}')}",
    ]
    lines += _buyer_lines(project)

    description = project.description
    if len(description) > _MAX_DESCRIPTION:
        description = description[:_MAX_DESCRIPTION].rstrip() + "…"
    if description:
        desc = f"<i>{html.escape(description)}</i>"
        lines.append("")
        if expandable_desc:
            # Разворачиваемая цитата: видно первые строки, тап — раскрыть всё.
            lines.append("📄 Описание:")
            lines.append(f"<blockquote expandable>{desc}</blockquote>")
        else:
            lines.append(desc)

    lines.append("")
    lines.append(f"🔗 {project.url}")
    return lines


def format_project(project: Project, *, refreshed: bool = False) -> str:
    """Активный проект: описание — разворачиваемой цитатой."""
    text = "\n".join(_body_lines(project, expandable_desc=True))
    if refreshed:
        text += f"\n\n🕒 обновлено {datetime.now():%d.%m %H:%M:%S}"
    return text


def format_deleted(project: Project) -> str:
    """Удалённый/закрытый проект: жирный заголовок + весь контент зачёркнут
    (форматирование сохраняется), описание показано (не под спойлером)."""
    body = "\n".join(_body_lines(project, expandable_desc=False))
    return (
        "❌ <b>ПРОЕКТ УДАЛЁН ИЛИ ЗАКРЫТ</b>\n\n"
        f"<s>{body}</s>\n\n"
        f"🕒 проверено {datetime.now():%d.%m %H:%M:%S}"
    )


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

    @property
    def bot(self) -> Bot:
        return self._bot

    async def send_project(self, project: Project) -> None:
        await self._bot.send_message(
            self._chat_id, format_project(project), reply_markup=_refresh_kb(project.id)
        )

    async def update_message(self, message: Message, project: Project, *, deleted: bool) -> None:
        """Перерисовывает существующее сообщение (по нажатию «Обновить»)."""
        if deleted:
            text, markup = format_deleted(project), None
        else:
            text, markup = format_project(project, refreshed=True), _refresh_kb(project.id)
        try:
            await message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def send_text(self, text: str) -> None:
        await self._bot.send_message(self._chat_id, text)

    async def close(self) -> None:
        await self._bot.session.close()
