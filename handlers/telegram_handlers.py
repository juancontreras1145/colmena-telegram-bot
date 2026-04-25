"""Maneja Telegram: comandos, carga de archivos y debate dinámico de Colmena BOT."""
from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.analyzer import analyze_dataframe
from core.debate_engine import (
    DebateConfig,
    ESTILOS_VALIDOS,
    MODOS_VALIDOS,
    crear_debate,
    decidir_modo,
    explicar_modo,
    get_user_state,
)
from core.limits import MAX_FILE_BYTES
from core.reader import SUPPORTED_EXTENSIONS, load_file
from core.report import build_report
from core.text_quality import analyze_text_quality
from core.utils import human_size, safe_remove, slugify, temp_path


log = logging.getLogger(__name__)

PAUSA_MENSAJE = 1.0


WELCOME = (
    "🐝 Bienvenido a Colmena BOT\n\n"
    "Soy una colmena de mini-bots que revisan archivos como un equipo:\n"
    "👁️ Lector\n"
    "🛡️ Inspector\n"
    "🧹 Limpiador\n"
    "🕵️ Detective\n"
    "📊 Analista\n"
    "🔤 Detective fino\n"
    "⚖️ Crítico\n"
    "🧠 Jefe\n"
    "📝 Constructor\n\n"
    "Envíame un archivo CSV, XLSX o XLSM.\n\n"
    "Comandos:\n"
    "/modo auto | show | normal | compacto | silencioso\n"
    "/estilo equilibrado | serio | humor | duro\n"
    "/humor on | off\n"
    "/pausa 1\n"
    "/estado\n"
    "/reset"
)


HELP = (
    "🐝 Ayuda de Colmena BOT\n\n"
    "Formatos aceptados:\n"
    "- CSV\n"
    "- XLSX\n"
    "- XLSM\n\n"
    "El bot nunca ejecuta macros.\n\n"
    "Modos:\n"
    "auto: decide solo\n"
    "show: debate largo\n"
    "normal: equilibrio\n"
    "compacto: directo\n"
    "silencioso: casi solo TXT\n\n"
    "Estilos:\n"
    "equilibrado: útil + algo de humor\n"
    "serio: más sobrio\n"
    "humor: más obreras opinando\n"
    "duro: crítico exigente\n\n"
    "Ejemplos:\n"
    "/modo compacto\n"
    "/estilo humor\n"
    "/humor off\n"
    "/pausa 0.5\n"
    "/reset"
)


def get_user_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    context.user_data.setdefault("archivos_analizados", 0)
    context.user_data.setdefault("modo", "auto")
    context.user_data.setdefault("humor", True)
    context.user_data.setdefault("estilo", "equilibrado")
    context.user_data.setdefault("pausa", PAUSA_MENSAJE)
    return context.user_data


async def decir(update: Update, texto: str, pausa: float | None = None) -> None:
    msg = update.effective_message
    state = get_user_state_from_update_context(update)
    delay = PAUSA_MENSAJE if pausa is None else pausa

    if state:
        delay = float(state.get("pausa", delay))

    await msg.chat.send_action(ChatAction.TYPING)
    await asyncio.sleep(delay)
    await msg.reply_text(texto)


def get_user_state_from_update_context(update: Update) -> dict | None:
    # Placeholder seguro: la pausa real se controla en enviar_lineas().
    return None


async def enviar_lineas(update: Update, context: ContextTypes.DEFAULT_TYPE, lineas: list[str]) -> None:
    state = get_user_state(context)
    pausa = float(state.get("pausa", PAUSA_MENSAJE))

    for linea in lineas:
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        await asyncio.sleep(pausa)
        await update.effective_message.reply_text(linea)


async def enviar_bloque(update: Update, lineas: list[str], max_chars: int = 3500) -> None:
    msg = update.effective_message
    buffer = ""

    for linea in lineas:
        candidato = buffer + "\n" + linea if buffer else linea

        if len(candidato) > max_chars:
            await msg.reply_text(buffer)
            await asyncio.sleep(0.3)
            buffer = linea
        else:
            buffer = candidato

    if buffer:
        await msg.reply_text(buffer)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)
    state["archivos_analizados"] = 0
    await update.effective_message.reply_text(WELCOME)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)
    state["archivos_analizados"] = 0
    await update.effective_message.reply_text(
        "🔄 Reiniciado. El próximo archivo volverá a sentirse como primera revisión."
    )


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)

    texto = (
        "🐝 Estado actual de la colmena\n\n"
        f"Archivos analizados en esta conversación: {state.get('archivos_analizados', 0)}\n"
        f"Modo: {state.get('modo', 'auto')}\n"
        f"Estilo: {state.get('estilo', 'equilibrado')}\n"
        f"Humor: {'on' if state.get('humor', True) else 'off'}\n"
        f"Pausa: {state.get('pausa', PAUSA_MENSAJE)} segundo(s)"
    )

    await update.effective_message.reply_text(texto)


async def cmd_modo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)

    if not context.args:
        await update.effective_message.reply_text(
            f"Modo actual: {state.get('modo', 'auto')}\n\n"
            "Opciones:\n"
            "/modo auto\n"
            "/modo show\n"
            "/modo normal\n"
            "/modo compacto\n"
            "/modo silencioso"
        )
        return

    nuevo = context.args[0].lower().strip()

    if nuevo not in MODOS_VALIDOS:
        await update.effective_message.reply_text(
            "Modo no válido. Usa: auto, show, normal, compacto o silencioso."
        )
        return

    state["modo"] = nuevo
    await update.effective_message.reply_text(f"🐝 Modo cambiado a: {nuevo}")


async def cmd_estilo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)

    if not context.args:
        await update.effective_message.reply_text(
            f"Estilo actual: {state.get('estilo', 'equilibrado')}\n\n"
            "Opciones:\n"
            "/estilo equilibrado\n"
            "/estilo serio\n"
            "/estilo humor\n"
            "/estilo duro"
        )
        return

    nuevo = context.args[0].lower().strip()

    if nuevo not in ESTILOS_VALIDOS:
        await update.effective_message.reply_text(
            "Estilo no válido. Usa: equilibrado, serio, humor o duro."
        )
        return

    state["estilo"] = nuevo

    if nuevo == "humor":
        state["humor"] = True

    await update.effective_message.reply_text(f"🎭 Estilo cambiado a: {nuevo}")


async def cmd_humor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)

    if not context.args:
        estado = "on" if state.get("humor", True) else "off"
        await update.effective_message.reply_text(
            f"Humor actual: {estado}\n\nUsa /humor on o /humor off"
        )
        return

    valor = context.args[0].lower().strip()

    if valor in {"on", "si", "sí", "true", "1"}:
        state["humor"] = True
        await update.effective_message.reply_text("🐝 Humor activado.")
    elif valor in {"off", "no", "false", "0"}:
        state["humor"] = False
        await update.effective_message.reply_text("🧘 Humor desactivado. Colmena seria.")
    else:
        await update.effective_message.reply_text("Usa /humor on o /humor off")


async def cmd_pausa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)

    if not context.args:
        await update.effective_message.reply_text(
            f"Pausa actual: {state.get('pausa', PAUSA_MENSAJE)} segundo(s)\n\n"
            "Ejemplos:\n"
            "/pausa 1\n"
            "/pausa 0.5\n"
            "/pausa 2"
        )
        return

    try:
        nueva = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.effective_message.reply_text("Pausa inválida. Ejemplo: /pausa 1")
        return

    if nueva < 0:
        nueva = 0

    if nueva > 5:
        nueva = 5

    state["pausa"] = nueva
    await update.effective_message.reply_text(f"⏱️ Pausa cambiada a {nueva} segundo(s).")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (update.effective_message.text or "").lower().strip()

    if texto in {"reset", "reiniciar"}:
        await cmd_reset(update, context)
        return

    await update.effective_message.reply_text(
        "🐝 Mándame un archivo CSV, XLSX o XLSM y activo la colmena.\n\n"
        "Comandos útiles:\n"
        "/modo compacto\n"
        "/modo show\n"
        "/estilo humor\n"
        "/humor off\n"
        "/estado\n"
        "/reset"
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
            f"⚠️ Formato {ext} no soportado. Acepto CSV, XLSX o XLSM."
        )
        return

    if file_size and file_size > MAX_FILE_BYTES:
        await msg.reply_text(
            f"⚠️ El archivo pesa {human_size(file_size)}. Máximo permitido: {human_size(MAX_FILE_BYTES)}."
        )
        return

    state = get_user_state(context)

    await msg.chat.send_action(ChatAction.TYPING)
    await msg.reply_text("🐝 Recibí el archivo. Convocando a la colmena...")

    download_path = temp_path(suffix=ext)
    txt_path = temp_path(suffix=".txt")

    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=download_path)

        await enviar_lineas(update, context, [
            "👁️ Lector: descargué el archivo. Lo voy a inspeccionar.",
            "🛡️ Inspector: abriendo en modo seguro.",
        ])

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

        await enviar_lineas(update, context, [
            "📊 Analista: datos cargados. Empieza la revisión pesada.",
        ])

        analysis = await loop.run_in_executor(None, analyze_dataframe, df)

        await enviar_lineas(update, context, [
            "🔤 Detective fino: revisando textos, correos, espacios y typos.",
        ])

        text_quality = await loop.run_in_executor(None, analyze_text_quality, df)

        await enviar_lineas(update, context, [
            "📝 Constructor: preparando debate, resumen y TXT.",
        ])

        report = await loop.run_in_executor(
            None,
            build_report,
            loaded,
            analysis,
            text_quality,
            txt_path,
        )

        modo = decidir_modo(state, report.health_score)

        config = DebateConfig(
            modo=modo,
            estilo=state.get("estilo", "equilibrado"),
            humor=bool(state.get("humor", True)),
            health_score=report.health_score,
            archivo_numero=state.get("archivos_analizados", 1),
        )

        await msg.reply_text(explicar_modo(config))

        debate = crear_debate(report.debate_lines, config)

        await enviar_lineas(update, context, debate)

        await enviar_lineas(update, context, [
            "📋 Resumen corto de la colmena:",
        ])

        await enviar_bloque(update, report.summary_lines)

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

        await enviar_lineas(update, context, [
            "✅ Colmena finalizada. Puedes enviarme otro archivo.",
        ])

    except Exception as exc:  # noqa: BLE001
        log.exception("Error procesando archivo")
        await msg.reply_text(f"❌ La colmena tropezó: {exc}")

    finally:
        safe_remove(download_path)
        safe_remove(txt_path)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["ayuda", "help"], cmd_help))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("estado", cmd_estado))
    app.add_handler(CommandHandler("modo", cmd_modo))
    app.add_handler(CommandHandler("estilo", cmd_estilo))
    app.add_handler(CommandHandler("humor", cmd_humor))
    app.add_handler(CommandHandler("pausa", cmd_pausa))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))