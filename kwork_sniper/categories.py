"""Справочник кодов категорий Kwork.

Код категории — число из адресной строки фильтра проектов:
    https://kwork.ru/projects?fc=41   →   код 41
В запросе к ленте тот же код передаётся параметром `c`.

Запустить как таблицу:  python -m kwork_sniper.categories
"""

from __future__ import annotations

# Подкатегории раздела «Разработка и IT» (parent 11) —
# основное для ботов / парсинга / автоматизации.
IT_CATEGORIES: dict[str, str] = {
    "41": "Скрипты и боты",
    "37": "Создание сайта",
    "38": "Доработка и настройка сайта",
    "79": "Вёрстка",
    "80": "Десктоп-программирование",
    "39": "Мобильные приложения",
    "40": "Игры",
    "255": "Серверы и хостинг",
    "81": "Юзабилити, тестирование",
}

# Разделы верхнего уровня (для широкого мониторинга).
PARENT_CATEGORIES: dict[str, str] = {
    "11": "Разработка и IT",
    "15": "Дизайн",
    "5": "Тексты и переводы",
    "17": "SEO и трафик",
    "45": "Соцсети и реклама",
    "7": "Аудио, видео, съёмка",
    "83": "Бизнес и жизнь",
}

ALL_CATEGORIES: dict[str, str] = {**PARENT_CATEGORIES, **IT_CATEGORIES}


def category_name(code: str | int) -> str:
    """Человекочитаемое название по коду; для неизвестного — заглушка."""
    return ALL_CATEGORIES.get(str(code), f"Категория {code}")


if __name__ == "__main__":
    print("Коды категорий Kwork (значение для KWORK_CATEGORIES в .env):\n")
    print("— Разработка и IT —")
    for code, name in IT_CATEGORIES.items():
        print(f"  {code:>4}  {name}")
    print("\n— Разделы верхнего уровня —")
    for code, name in PARENT_CATEGORIES.items():
        print(f"  {code:>4}  {name}")
