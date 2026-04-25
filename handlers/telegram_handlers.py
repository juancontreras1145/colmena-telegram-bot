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


PAUSA_DEBATE = 1.0
MAX_DEBATE_MENSAJES = 55


WELCOME = (
    "🐝 *Bienvenido a Colmena BOT*\n\n"
    "Soy una colmena de mini-bots que revisan tu archivo como un equipo de auditoría:\n"
    "👁️ Lector · 🛡️ Inspector · 🧹 Limpiador · 🕵️ Detective · 📊 Analista · "
    "🔤 Detective fino · ⚖️ Crítico · 🧠 Jefe · 📝 Constructor.\n\n"
    "📤 Envíame un archivo *CSV*, *XLSX* o *XLSM* y la colmena lo debate.\n"
    "Te devuelvo:\n"
    "• Debate paso a paso.\n"
    "• Resumen corto.\n"
    "• Puntaje de salud.\n"
    "• Reporte `.txt` descargable.\n\n"
    "Usa /ayuda para ver más detalles."
)


HELP = (
    "🐝 *Cómo funciona la colmena*\n\n"
    "1. Sube un archivo `CSV`, `XLSX` o `XLSM`.\n"
    f"2. Tamaño máximo: {human_size(MAX_FILE_BYTES)}.\n"
    "3. La colmena lo abre en *modo seguro*: nunca ejecuta macros.\n"
    "4. Si es muy grande, analiza una muestra inteligente para no caerse.\n"
    "5. Recibirás debate, resumen y reporte `.txt`.\n\n"
    "🔍 Detecta:\n"
    "• Celdas vacías.\n"
    "• Columnas inútiles.\n"
    "• Filas duplicadas.\n"
    "• Fechas/correos inválidos.\n"
    "• Valores raros.\n"
    "• Excel inflado.\n"
    "• Dobles espacios.\n"
    "• Typos.\n"
    "• Letras repetidas.\n"
    "• Correos sospechosos."
)


async def _send_chunked(
    update: Update,
    lines: List[str],
    parse_mode: str | None = ParseMode.MARKDOWN,
) -> None:
    """Envía resumen o textos largos agrupados."""
    buf = ""

    for line in lines:
        candidate = (buf + "\n" + line) if buf else line

        if len(candidate) > 3500:
            await update.effective_message.reply_text(buf, parse_mode=parse_mode)
            await asyncio.sleep(0.4)
            buf = line
        else:
            buf = candidate

    if buf:
        await update.effective_message.reply_text(buf, parse_mode=parse_mode)


async def _send_debate_line_by_line(update: Update, lines: List[str]) -> None:
    """Envía el debate como conversación viva, línea por línea."""
    msg = update.effective_message

    final_lines = _enrich_debate(lines)

    if len(final_lines) > MAX_DEBATE_MENSAJES:
        recortadas = len(final_lines) - MAX_DEBATE_MENSAJES
        final_lines = final_lines[:MAX_DEBATE_MENSAJES]
        final_lines.append(
            f"🧠 *Jefe:* hay {recortadas} intervención(es) más. Las dejo completas en el TXT."
        )

    for line in final_lines:
        await msg.chat.send_action(ChatAction.TYPING)
        await asyncio.sleep(PAUSA_DEBATE)
        await msg.reply_text(line, parse_mode=ParseMode.MARKDOWN)


def _enrich_debate(lines: List[str]) -> List[str]:
    """Agrega más debate, humor y sensación de mini-bots discutiendo."""
    out: List[str] = []

    out.append("🐝 *La colmena se está organizando...*")
    out.append("🧠 *Jefe:* nadie se me arranca. Primero miramos, después opinamos.")
    out.append("👁️ *Lector:* recibido. Abriendo el archivo con cuidado.")
    out.append("🛡️ *Inspector:* modo paranoico saludable activado. No ejecutamos macros.")

    for line in lines:
        out.append(line)

        low = line.lower()

        if "xlsm" in low or "macro" in low:
            out.append("🛡️ *Inspector:* las macros se miran, no se tocan. Aquí nadie apreta botones raros.")
            out.append("⚖️ *Crítico:* buena práctica. Archivo con macros merece respeto.")

        if "modo seguro" in low:
            out.append("🧠 *Jefe:* prefiero ir lento y volver vivo que hacerme el valiente y caerme.")
            out.append("🐝 *Obrera 12:* entendido jefe, nada de comernos el Excel completo de una.")

        if "muestra" in low:
            out.append("📊 *Analista:* trabajar con muestra es válido si el archivo es gigante.")
            out.append("⚖️ *Crítico:* pero lo anoto: los resultados son orientación, no sentencia final.")

        if "filas útiles" in low or "columnas" in low:
            out.append("👁️ *Lector:* ya tengo el mapa del terreno.")
            out.append("🧹 *Limpiador:* si hay columnas basura, las voy a mirar feo.")

        if "duplicada" in low or "duplicadas" in low:
            out.append("🕵️ *Detective:* duplicado encontrado. Esto huele a copia, pegado o proceso repetido.")
            out.append("📊 *Analista:* ojo, esto puede inflar totales.")
            out.append("⚖️ *Crítico:* consenso: revisar antes de usar en informe.")

        if "vacía" in low or "vacías" in low or "vacíos" in low:
            out.append("🧹 *Limpiador:* los vacíos no siempre son error, pero siempre merecen explicación.")
            out.append("🧠 *Jefe:* anotado. Vacío sin justificación es sospechoso.")

        if "rango usado falso" in low or "inflado" in low:
            out.append("🧹 *Limpiador:* clásico Excel con gimnasio: pesa mucho y trae poco.")
            out.append("⚖️ *Crítico:* recomendación probable: copiar rango útil a archivo nuevo.")

        if "detalles humanos" in low or "detective fino" in low:
            out.append("🔤 *Detective fino:* aquí entran las cosas que el ojo cansado deja pasar.")
            out.append("🐝 *Obrera 7:* doble espacio detectado, mi momento ha llegado.")

        if "dobles espacios" in low:
            out.append("🧹 *Limpiador:* doble espacio parece chico, pero ensucia búsquedas y coincidencias.")
            out.append("📊 *Analista:* también puede afectar comparaciones exactas.")

        if "typo" in low or "posibles typos" in low:
            out.append("🔤 *Detective fino:* no acuso, sugiero revisar. Soy sapo, no juez.")
            out.append("⚖️ *Crítico:* correcto. Todo typo sugerido debe validarse manualmente.")

        if "correo" in low or "email" in low:
            out.append("🕵️ *Detective:* si el correo está raro, el envío puede fallar.")
            out.append("📊 *Analista:* conviene separar inválidos, raros y dominios.")

        if "puntaje de salud" in low or "salud" in low:
            out.append("⚖️ *Crítico:* el puntaje no es castigo, es semáforo.")
            out.append("🧠 *Jefe:* si está bajo, no se llora: se limpia.")

    out.append("🐝 *Mesa chica final...*")
    out.append("🕵️ *Detective:* hallazgos presentados.")
    out.append("📊 *Analista:* impacto estimado.")
    out.append("🧹 *Limpiador:* acciones de limpieza sugeridas.")
    out.append("⚖️ *Crítico:* listo para veredicto.")
    out.append("🧠 *Jefe:* consenso alcanzado. Constructor, arma el reporte.")

    return out


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🐝 Soy Colmena BOT. Mándame un archivo `CSV`, `XLSX` o `XLSM` y activo el debate.",
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
            f"⚠️ El archivo pesa {human_size(file_size)}. Máximo permitido: {human_size(MAX_FILE_BYTES)}."
        )
        return

    await msg.chat.send_action(ChatAction.TYPING)
    await msg.reply_text("🐝 Recibí el archivo. Convocando a la colmena...")

    download_path = temp_path(suffix=ext)
    txt_path = temp_path(suffix=".txt")

    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=download_path)

        await msg.reply_text("👁️ Lector: descargué el archivo. Lo voy a inspeccionar.")
        await asyncio.sleep(PAUSA_DEBATE)

        await msg.reply_text("🛡️ Inspector: abriendo en modo seguro.")
        await asyncio.sleep(PAUSA_DEBATE)

        loop = asyncio.get_running_loop()

        loaded = await loop.run_in_executor(None, load_file, download_path, file_name)

        if loaded.error:
            await msg.reply_text(f"❌ {loaded.error}")
            return

        df = loaded.primary_df

        if df is None:
            await msg.reply_text(
                "❌ No encontré una hoja con datos para analizar. Revisa que el archivo no esté vacío."
            )
            return

        await msg.reply_text("📊 Analista: datos cargados. Empieza la revisión pesada.")
        await asyncio.sleep(PAUSA_DEBATE)

        analysis = await loop.run_in_executor(None, analyze_dataframe, df)

        await msg.reply_text("🔤 Detective fino: revisando textos, correos, espacios y typos.")
        await asyncio.sleep(PAUSA_DEBATE)

        text_quality = await loop.run_in_executor(None, analyze_text_quality, df)

        await msg.reply_text("📝 Constructor: preparando debate, resumen y TXT.")
        await asyncio.sleep(PAUSA_DEBATE)

        report = await loop.run_in_executor(
            None,
            build_report,
            loaded,
            analysis,
            text_quality,
            txt_path,
        )

        await _send_debate_line_by_line(update, report.debate_lines)

        await asyncio.sleep(PAUSA_DEBATE)

        await msg.reply_text("📋 *Resumen corto de la colmena:*", parse_mode=ParseMode.MARKDOWN)
        await _send_chunked(update, report.summary_lines)

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

        await asyncio.sleep(PAUSA_DEBATE)

        await msg.reply_text("✅ Colmena finalizada. Puedes enviarme otro archivo.")

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