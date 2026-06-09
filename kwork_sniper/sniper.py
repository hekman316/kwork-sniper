"""Главный цикл снайпера: poll → dedupe → filter → notify."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from .config import Settings, load_settings
from .kwork import KworkAuthError, KworkClient, Project
from .notifier import Notifier
from .storage import Storage

log = logging.getLogger("kwork_sniper")

_MAX_BACKOFF = 600  # потолок паузы при сбоях, сек
_SEND_PAUSE = 0.3   # пауза между сообщениями (вежливость к Telegram), сек


def passes_filter(project: Project, settings: Settings) -> bool:
    haystack = f"{project.name}\n{project.description}".lower()

    if settings.keywords and not any(k in haystack for k in settings.keywords):
        return False
    if settings.exclude_keywords and any(k in haystack for k in settings.exclude_keywords):
        return False
    if settings.max_offers and project.offers > settings.max_offers:
        return False
    if settings.min_budget:
        budget = project.possible_price_limit or project.price_limit
        if budget and budget < settings.min_budget:
            return False
    if settings.min_hired_percent and project.customer_hired_percent < settings.min_hired_percent:
        return False
    if settings.min_customer_projects and project.customer_projects < settings.min_customer_projects:
        return False
    return True


async def _collect_new(
    client: KworkClient, storage: Storage, settings: Settings
) -> list[Project]:
    """Опрашивает все категории, отмечает новые id в БД и возвращает новые проекты,
    отсортированные по дате создания (старые → свежие)."""
    new_projects: list[Project] = []
    for category in settings.categories:
        try:
            projects = await client.fetch_projects(category, max_pages=settings.max_pages)
        except KworkAuthError as exc:
            log.warning("Категория %s пропущена: %s", category, exc)
            continue

        for project in projects:
            if storage.is_seen(project.id):
                continue
            storage.add(project.id)
            new_projects.append(project)

    new_projects.sort(key=lambda p: p.date_create)
    return new_projects


async def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    storage = Storage(settings.db_path)
    notifier = Notifier(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        settings.telegram_proxy,
    )
    categories = ", ".join(settings.categories)

    log.info(
        "Запуск. Категории: %s. Интервал: %s сек. Telegram: %s. Пульс: %s.",
        categories,
        settings.poll_interval,
        "через прокси" if settings.telegram_proxy else "напрямую",
        f"каждые {settings.heartbeat_hours} ч" if settings.heartbeat_hours else "выкл",
    )

    first_run = storage.count() == 0
    healthy = True

    heartbeat_interval = settings.heartbeat_hours * 3600  # 0 = выключен
    last_heartbeat = time.monotonic()
    sent_since_heartbeat = 0

    async with aiohttp.ClientSession() as session:
        client = KworkClient(session)
        try:
            if first_run:
                seeded = await _collect_new(client, storage, settings)
                log.info(
                    "Первый запуск: засеяно %s текущих проектов без уведомлений.",
                    len(seeded),
                )
                await notifier.send_text(
                    f"✅ Kwork-снайпер запущен. Слежу за категориями: {categories}."
                )

            while True:
                # Пульс: раз в heartbeat_interval подтверждаем, что бот жив.
                if heartbeat_interval and time.monotonic() - last_heartbeat >= heartbeat_interval:
                    last_heartbeat = time.monotonic()
                    log.info("Пульс: в базе %s, новых за период %s", storage.count(), sent_since_heartbeat)
                    try:
                        await notifier.send_text(
                            f"💓 Бот жив. В базе: {storage.count()} проектов. "
                            f"Новых отправлено за период: {sent_since_heartbeat}."
                        )
                    except Exception:
                        pass
                    sent_since_heartbeat = 0

                try:
                    new_projects = await _collect_new(client, storage, settings)
                    matched = [p for p in new_projects if passes_filter(p, settings)]
                    for project in matched:
                        try:
                            await notifier.send_project(project)
                        except Exception as exc:
                            log.error("Не отправлен проект %s: %s", project.id, exc)
                        await asyncio.sleep(_SEND_PAUSE)
                    sent_since_heartbeat += len(matched)

                    if matched:
                        log.info("Отправлено новых проектов: %s", len(matched))
                    elif new_projects:
                        log.info(
                            "Новых проектов: %s, под фильтр не подошёл ни один.",
                            len(new_projects),
                        )

                    if not healthy:
                        healthy = True
                        await notifier.send_text("✅ Снайпер восстановился, опрос идёт.")

                    await asyncio.sleep(settings.poll_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.error("Сбой цикла опроса: %s", exc)
                    if healthy:
                        healthy = False
                        try:
                            await notifier.send_text(f"⚠️ Снайпер: сбой опроса — {exc}")
                        except Exception:
                            pass
                    await asyncio.sleep(min(settings.poll_interval * 4, _MAX_BACKOFF))
        finally:
            await notifier.close()
            storage.close()
