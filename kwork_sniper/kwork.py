"""Слой получения и разбора ленты проектов Kwork.

Изолирован намеренно: если Kwork поменяет API или схему ответа — чинить нужно
будет только здесь. Используется публичный AJAX-эндпоинт сайта (без авторизации):

    POST https://kwork.ru/projects
    headers: X-Requested-With: XMLHttpRequest   ← без него вернётся HTML, не JSON
    body:    c=<код категории>&page=<номер>

Проекты в ответе лежат в  data.pagination.data[]  (проверено на живом API).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import aiohttp

PROJECTS_URL = "https://kwork.ru/projects"
PROJECT_URL_TEMPLATE = "https://kwork.ru/projects/{id}"

# Полный набор браузерных заголовков. Ключевой — X-Requested-With.
HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
    "Origin": "https://kwork.ru",
    "Referer": "https://kwork.ru/projects",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
}

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    """Убирает HTML-теги из описания, превращая <br> в переносы строк."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    return html.unescape(text).strip()


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class Project:
    """Нормализованный проект Kwork."""

    id: int
    name: str
    description: str
    url: str
    price_limit: float           # бюджет «от», ₽
    possible_price_limit: float  # бюджет «до», ₽
    offers: int                  # число откликов
    views: int
    date_create: str
    category_id: str
    customer: str
    customer_url: str


class KworkAuthError(RuntimeError):
    """Лента не отдала ожидаемый JSON — антибот, редирект или смена API."""


class KworkClient:
    """Тонкий асинхронный клиент над лентой проектов Kwork."""

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def _fetch_page(self, category: str, page: int) -> dict:
        payload = {"c": str(category), "page": str(page)}
        async with self._session.post(PROJECTS_URL, data=payload, headers=HEADERS) as resp:
            resp.raise_for_status()
            try:
                data = await resp.json(content_type=None)
            except Exception as exc:  # не JSON => скорее всего отдали HTML
                raise KworkAuthError(
                    f"Ответ не JSON (категория {category}, стр. {page})"
                ) from exc

        if not data.get("success"):
            raise KworkAuthError(f"success != true (категория {category})")
        try:
            return data["data"]["pagination"]
        except (KeyError, TypeError) as exc:
            raise KworkAuthError(f"Неожиданная структура ответа (категория {category})") from exc

    async def fetch_projects(self, category: str, max_pages: int = 0) -> list[Project]:
        """Возвращает проекты категории. max_pages=0 — все страницы."""
        first = await self._fetch_page(category, 1)
        last_page = _to_int(first.get("last_page")) or 1
        if max_pages > 0:
            last_page = min(last_page, max_pages)

        projects = [self._parse(item, category) for item in first.get("data", [])]
        for page in range(2, last_page + 1):
            pagination = await self._fetch_page(category, page)
            projects.extend(self._parse(item, category) for item in pagination.get("data", []))
        return projects

    @staticmethod
    def _parse(item: dict, category: str) -> Project:
        pid = _to_int(item.get("id"))
        user = item.get("user") or {}
        return Project(
            id=pid,
            name=html.unescape(str(item.get("name", "")).strip()),
            description=_clean_html(str(item.get("description", ""))),
            url=PROJECT_URL_TEMPLATE.format(id=pid),
            price_limit=_to_float(item.get("priceLimit")),
            possible_price_limit=_to_float(item.get("possiblePriceLimit")),
            offers=_to_int(item.get("kwork_count")),
            views=_to_int(item.get("views_dirty")),
            date_create=str(item.get("date_create", "")),
            category_id=str(item.get("category_id", category)),
            customer=str(user.get("username", "")),
            customer_url=str(item.get("wantUserGetProfileUrl", "")),
        )
