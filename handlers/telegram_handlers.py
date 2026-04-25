"""Maneja la interacción con Telegram: /start, /ayuda y carga de archivos."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.analyzer import analyze_dataframe
from core.limits import MAX_FILE_BYTES
from core.reader import SUPPORTED_EXTENSIONS, load_file
from core.report import build_report
from core.text_quality import analyze_text_quality
from core.utils import human_size, safe_remove, slugify, temp_path


log = logging.getLogger(__name__)


WELCOME = (
    "🐝 *Bienvenido a Colmena BOT*\n\n"
    "Soy una colmena de mini-bots que revisan tu archivo como un equipo de auditoría:\n"
    "👁️ Lector · 🛡️ Inspector · 🧹 Limpiador · 🕵️ Detective · 📊 Analista · "
    "🔤 Detective fino · ⚖️ Crítico · 🧠 Jefe · 📝 Constructor.\n\n"
    "📤 Envíame un archivo *CSV*, *XLSX* o *XLSM* y la colmena lo debate.\n"
    "Te devuelvo:\n"
    "• Mensajes estilo debate.\n"
    "• Resumen corto.\n"
    "• Puntaje de salud del archivo.\n"
    "• Reporte `.txt` descargable.\n\n"
    "Usa /ayuda para ver más detalles."
)

HELP = (
    "🐝 *Cómo funciona la colmena*\n\n"
    "1. Sube un archivo `CSV`, `XLSX` o `XLSM` (máx "
    f"{human_size(MAX_FILE_BYTES)}).\n"
    "2. La colmena lo abre en *modo seguro*: nunca ejecuta macros.\n"
    "3. Si es muy grande, analiza una muestra inteligente para no caerse.\n"
    "4. Recibirás los mensajes del debate, el resumen y un reporte `.txt`.\n\n"
    "🔍 Detecta:\n"
    "• Celdas y columnas vacías, filas vacías.\n"
    "• Filas duplicadas.\n"
    "• Fechas y correos inválidos.\n"
    "• Valores negativos, ceros y outliers.\n"
    "• Categorías repetidas y dominios de correos.\n"
    "• Excel inflado, hojas inútiles, rangos falsos por formato.\n"
    "• Dobles espacios, typos, letras repetidas y correos sospechosos."
)


async def _send_chunked(update: Update, lines: List[str], parse_mode: str = ParseMode.MARKDOWN) -> None:
    """Envía mensajes respetando el límite de Telegram (~4096 chars), agrupando líneas."""
    buf = ""
    for line in lines:
        candidate = (buf + "\n" + line) if buf else line
        if len(candidate) > 3500:
            await update.effective_message.reply_text(buf, parse_mode=parse_mode)
            await asyncio.sleep(0.2)
            buf = line
        else:
            buf = candidate
    if buf:
        await update.effective_message.reply_text(buf, parse_mode=parse_mode)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🐝 Soy Colmena BOT. Mándame un archivo `CSV`, `XLSX` o `XLSM` para que la colmena lo analice. "
        "Usa /ayuda para más info.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    document = msg.document
    if document is None:
        return

    file_name = document.file_name or "archivo"
    file_size = document.file_size or 0

    ext = os.path.splitext(file_name)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        await msg.reply_text(
            f"⚠️ Formato `{ext}` no soportado. Acepto CSV, XLSX o XLSM.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if file_size and file_size > MAX_FILE_BYTES:
        await msg.reply_text(
            f"⚠️ El archivo pesa {human_size(file_size)}. Máximo permitido: "
            f"{human_size(MAX_FILE_BYTES)}.",
        )
        return

    await msg.chat.send_action(ChatAction.TYPING)
    await msg.reply_text("🐝 Recibí el archivo. Convocando a la colmena...")

    download_path = temp_path(suffix=ext)
    txt_path = temp_path(suffix=".txt")
    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=download_path)

        # Trabajo pesado en hilo aparte para no bloquear el event loop.
        loop = asyncio.get_running_loop()
        loaded = await loop.run_in_executor(None, load_file, download_path, file_name)

        if loaded.error:
            await msg.reply_text(f"❌ {loaded.error}")
            return

        df = loaded.primary_df
        if df is None:
            await msg.reply_text(
                "❌ No encontré una hoja con datos para analizar. "
                "Revisa que el archivo no esté vacío."
            )
            return

        analysis = await loop.run_in_executor(None, analyze_dataframe, df)
        text_quality = await loop.run_in_executor(None, analyze_text_quality, df)

        report = await loop.run_in_executor(
            None, build_report, loaded, analysis, text_quality, txt_path
        )

        await _send_chunked(update, report.debate_lines)
        await asyncio.sleep(0.2)
        await _send_chunked(update, report.summary_lines)

        # Enviamos el TXT como documento.
        out_name = f"colmena_{slugify(os.path.splitext(file_name)[0])}.txt"
        with open(report.txt_path, "rb") as f:
            await msg.reply_document(
                document=f,
                filename=out_name,
                caption=(
                    f"📝 Reporte completo de la colmena.\n"
                    f"🩺 Salud: {report.health_score}/100 — {report.health_label}"
                ),
            )

    except Exception as exc:  # noqa: BLE001
        log.exception("Error procesando archivo")
        await msg.reply_text(f"❌ La colmena tropezó: {exc}")
    finally:
        safe_remove(download_path)
        safe_remove(txt_path)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["ayuda", "help"], cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
