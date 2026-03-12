from __future__ import annotations

import os


def main() -> None:
    mode = os.getenv("BOT_MODE", "webhook")
    if mode == "polling":
        from src.bot.main import run_polling
        run_polling()
    else:
        from src.bot.main import run_webhook
        run_webhook()


if __name__ == "__main__":
    main()
