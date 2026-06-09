"""Главный цикл снайпера: poll → dedupe → filter → notify.

Параллельно крутится aiogram Dispatcher, который ловит нажатия инлайн-кнопки
«🔄 Обновить» под карточками и перерисовывает сообщение свежими данными
(или помечает проект удалённым/закрытым).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict

import aiohttp
from aiogram import Dispatcher, F
from aiogram.types import CallbackQuery

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


async def _snipe_loop(
    client: KworkClient, storage: Storage, notifier: Notifier, settings: Settings
) -> None:
    healthy = True
    heartbeat_interval = settings.heartbeat_hours * 3600  # 0 = выключен
    last_heartbeat = time.monotonic()
    sent_since_heartbeat = 0

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
                    storage.save_project(project.id, asdict(project))
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


def _register_callbacks(
    dp: Dispatcher, client: KworkClient, storage: Storage, notifier: Notifier, settings: Settings
) -> None:
    async def on_refresh(callback: CallbackQuery) -> None:
        data = callback.data or ""
        try:
            project_id = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            await callback.answer()
            return
        if callback.message is None:
            await callback.answer("Сообщение недоступно")
            return

        stored = storage.get_project(project_id)
        category = str(
            (stored or {}).get("category_id")
            or (settings.categories[0] if settings.categories else "11")
        )
        try:
            live = await client.fetch_one(project_id, category)
        except Exception as exc:
            log.warning("Обновление %s не удалось: %s", project_id, exc)
            await callback.answer("Не удалось обновить, попробуй ещё раз")
            return

        if live is not None:
            storage.save_project(project_id, asdict(live))
            await notifier.update_message(callback.message, live, deleted=False)
            await callback.answer(f"Обновлено: 👁 {live.views} · 💬 {live.offers}")
        else:
            if stored:
                try:
                    await notifier.update_message(callback.message, Project(**stored), deleted=True)
                except Exception as exc:
                    log.warning("Не отрисовать удалённый %s: %s", project_id, exc)
            await callback.answer("Проект удалён или закрыт", show_alert=True)

    dp.callback_query.register(on_refresh, F.data.startswith("upd:"))


async def _run_polling(dp: Dispatcher, bot) -> None:
    """Поллинг кнопок — best-effort: при сбое перезапускаем, не роняя снайпер."""
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False, drop_pending_updates=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Поллинг кнопок упал: %s. Перезапуск через 15 сек.", exc)
            await asyncio.sleep(15)


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
    dp = Dispatcher()
    categories = ", ".join(settings.categories)

    log.info(
        "Запуск. Категории: %s. Интервал: %s сек. Telegram: %s. Пульс: %s.",
        categories,
        settings.poll_interval,
        "через прокси" if settings.telegram_proxy else "напрямую",
        f"каждые {settings.heartbeat_hours} ч" if settings.heartbeat_hours else "выкл",
    )

    first_run = storage.count() == 0

    async with aiohttp.ClientSession() as session:
        client = KworkClient(session)
        _register_callbacks(dp, client, storage, notifier, settings)
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

            await asyncio.gather(
                _snipe_loop(client, storage, notifier, settings),
                _run_polling(dp, notifier.bot),
            )
        finally:
            await notifier.close()
            storage.close()
