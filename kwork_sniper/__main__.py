"""Точка входа: python -m kwork_sniper"""

from __future__ import annotations

import asyncio

from .sniper import run


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
