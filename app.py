"""Colmena BOT — punto de entrada.

Arranca el bot de Telegram en modo long polling.
Mantén este archivo lo más pequeño posible: toda la lógica vive en `handlers/` y `core/`.
"""
from __future__ import annotations

import logging
import os
import sys

from telegram.ext import Application

from handlers.telegram_handlers import register_handlers


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # httpx es muy ruidoso; lo bajamos a WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    log = logging.getLogger("colmena")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log.error("Falta la variable de entorno TELEGRAM_BOT_TOKEN.")
        sys.exit(1)

    app = Application.builder().token(token).build()
    register_handlers(app)

    log.info("🐝 Colmena BOT despierta. Escuchando archivos en Telegram...")
    app.run_polling(allowed_updates=None, drop_pending_updates=True)


if __name__ == "__main__":
    main()
