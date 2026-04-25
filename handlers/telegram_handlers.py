"""Maneja la interacción con Telegram: /start, /ayuda y carga de archivos."""
from __future__ import annotations

import asyncio
import logging
import os
import random
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
MAX_DEBATE_COMPLETO = 55
MAX_DEBATE_MEDIO = 28
MAX_DEBATE_COMPACTO = 10


WELCOME = (
    "🐝 *Bienvenido a Colmena BOT*\n\n"
    "Soy una colmena de mini-bots que revisan archivos como un equipo de auditoría:\n"
    "👁️ Lector · 🛡️ Inspector · 🧹 Limpiador · 🕵️ Detective · 📊 Analista · "
    "🔤 Detective fino · ⚖️ Crítico · 🧠 Jefe · 📝 Constructor.\n\n"
    "📤 Envíame un archivo *CSV*, *XLSX* o *XLSM* y la colmena lo debate.\n\n"
    "La primera revisión es más teatral. Las siguientes se vuelven más directas para no aburrir."
)


HELP = (
    "🐝 *Cómo funciona la colmena*\n\n"
    "1. Sube un archivo `CSV`, `XLSX` o `XLSM`.\n"
    f"2. Tamaño máximo: {human_size(MAX_FILE_BYTES)}.\n"
    "3. La colmena lo abre en *modo seguro*: nunca ejecuta macros.\n"
    "4. Si es muy grande, analiza una muestra inteligente.\n"
    "5. Recibirás debate, resumen y reporte `.txt`.\n\n"
    "Modos automáticos:\n"
    "• 1er archivo: debate completo.\n"
    "• 2do archivo: debate medio.\n"
    "• 3er archivo en adelante: compacto.\n"
    "• Si el archivo viene grave: vuelve el debate completo."
)


def elegir(frases: List[str]) -> str:
    return random.choice(frases)


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


async def _send_debate_line_by_line(
    update: Update,
    lines: List[str],
    modo: str,
    health_score: int,
) -> None:
    """Envía el debate según modo: completo, medio o compacto."""
    msg = update.effective_message

    if modo == "completo":
        final_lines = _debate_completo(lines, health_score)
        max_lines = MAX_DEBATE_COMPLETO
    elif modo == "medio":
        final_lines = _debate_medio(lines, health_score)
        max_lines = MAX_DEBATE_MEDIO
    else:
        final_lines = _debate_compacto(lines, health_score)
        max_lines = MAX_DEBATE_COMPACTO

    if len(final_lines) > max_lines:
        recortadas = len(final_lines) - max_lines
        final_lines = final_lines[:max_lines]
        final_lines.append(
            f"🧠 *Jefe:* hay {recortadas} intervención(es) más. Van completas en el TXT."
        )

    for line in final_lines:
        await msg.chat.send_action(ChatAction.TYPING)
        await asyncio.sleep(PAUSA_DEBATE)
        await msg.reply_text(line, parse_mode=ParseMode.MARKDOWN)


def _debate_completo(lines: List[str], health_score: int) -> List[str]:
    out: List[str] = []

    out.append(elegir([
        "🐝 *La colmena se está organizando...*",
        "🐝 *Se abre la sala de revisión. Que entren los mini-bots.*",
        "🐝 *Colmena activada. Hoy nadie revisa solo.*",
    ]))

    out.append(elegir([
        "🧠 *Jefe:* nadie se me arranca. Primero miramos, después opinamos.",
        "🧠 *Jefe:* orden en la colmena. Lector primero, críticos después.",
        "🧠 *Jefe:* revisión completa. Sin dramas, pero sin hacerse los ciegos.",
    ]))

    out.append(elegir([
        "👁️ *Lector:* recibido. Abriendo el archivo con cuidado.",
        "👁️ *Lector:* voy a mirar estructura, hojas, filas y columnas.",
        "👁️ *Lector:* entrando al archivo. Si hay columnas fantasmas, las pillo.",
    ]))

    out.append(elegir([
        "🛡️ *Inspector:* modo seguro activado. No ejecutamos macros.",
        "🛡️ *Inspector:* aquí se inspecciona, no se aprietan botones raros.",
        "🛡️ *Inspector:* si es XLSM, miro macros pero no las ejecuto.",
    ]))

    for line in lines:
        out.append(line)
        out.extend(_reacciones_por_linea(line))

    out.append("🐝 *Mesa chica final...*")
    out.append("🕵️ *Detective:* hallazgos presentados.")
    out.append("📊 *Analista:* impacto estimado.")
    out.append("🧹 *Limpiador:* acciones de limpieza sugeridas.")
    out.append("⚖️ *Crítico:* listo para veredicto.")
    out.append(_frase_jefe_final(health_score))

    return out


def _debate_medio(lines: List[str], health_score: int) -> List[str]:
    out: List[str] = []

    out.append(elegir([
        "🐝 *Segunda ronda. Esta vez vamos más directo.*",
        "🐝 *La colmena ya calentó motores. Debate medio activado.*",
        "🐝 *Revisión nueva. Menos teatro, más hallazgo.*",
    ]))

    out.append(elegir([
        "🧠 *Jefe:* resumamos lo importante y no demos la lata.",
        "🧠 *Jefe:* mini-bots, precisión. Nada de discurso eterno.",
        "🧠 *Jefe:* vamos al hueso del archivo.",
    ]))

    importantes = _filtrar_lineas_importantes(lines)

    for line in importantes:
        out.append(line)

        low = line.lower()

        if "duplic" in low:
            out.append("🕵️ *Detective:* duplicado aceptado. Puede inflar resultados.")
        elif "vac" in low:
            out.append("🧹 *Limpiador:* vacío detectado. Hay que justificarlo o corregirlo.")
        elif "correo" in low or "email" in low:
            out.append("🕵️ *Detective:* correo raro puede romper envíos.")
        elif "typo" in low or "dobles espacios" in low or "detalles humanos" in low:
            out.append("🔤 *Detective fino:* detalle pequeño, pero de esos que después molestan.")
        elif "salud" in low or "puntaje" in low:
            out.append("⚖️ *Crítico:* puntaje tomado como semáforo, no como sentencia.")

    out.append(_frase_jefe_final(health_score))

    return out


def _debate_compacto(lines: List[str], health_score: int) -> List[str]:
    importantes = _filtrar_lineas_importantes(lines)

    out: List[str] = []
    out.append(elegir([
        "🐝 *Modo compacto activado.*",
        "🐝 *Voy corto para no aburrirte.*",
        "🐝 *Resumen rápido de la colmena.*",
    ]))

    out.append(elegir([
        "🧠 *Jefe:* ya conocemos el proceso. Solo lo importante.",
        "🧠 *Jefe:* lectura rápida, golpes precisos.",
        "🧠 *Jefe:* sin show largo, vamos al resultado.",
    ]))

    for line in importantes[:6]:
        out.append(line)

    if health_score < 60:
        out.append("⚠️ *Crítico:* aunque estoy en compacto, este archivo viene delicado.")
        out.append("🧠 *Jefe:* recomiendo mirar el TXT completo.")
    elif health_score < 85:
        out.append("⚖️ *Crítico:* usable, pero hay detalles.")
    else:
        out.append("✅ *Crítico:* archivo bastante sano.")

    return out


def _filtrar_lineas_importantes(lines: List[str]) -> List[str]:
    claves = [
        "duplic",
        "vac",
        "correo",
        "email",
        "fecha",
        "macro",
        "xlsm",
        "modo seguro",
        "muestra",
        "filas útiles",
        "columnas",
        "salud",
        "puntaje",
        "detalles humanos",
        "dobles espacios",
        "typo",
        "inflado",
        "rango usado",
        "negativo",
        "cero",
        "sospech",
    ]

    importantes = []

    for line in lines:
        low = line.lower()

        if any(c in low for c in claves):
            importantes.append(line)

    return importantes or lines[:8]


def _reacciones_por_linea(line: str) -> List[str]:
    out: List[str] = []
    low = line.lower()

    if "xlsm" in low or "macro" in low:
        out.append(elegir([
            "🛡️ *Inspector:* macros vistas, manos quietas.",
            "🛡️ *Inspector:* las macros se miran, no se ejecutan.",
            "⚖️ *Crítico:* buen criterio. Archivo con macros merece respeto.",
        ]))

    if "modo seguro" in low:
        out.append(elegir([
            "🧠 *Jefe:* prefiero ir lento y volver vivo que hacerme el valiente y caerme.",
            "🐝 *Obrera 12:* entendido jefe, nada de comernos el Excel completo de una.",
            "🛡️ *Inspector:* modo seguro no es cobardía, es supervivencia.",
        ]))

    if "muestra" in low:
        out.append(elegir([
            "📊 *Analista:* trabajar con muestra es válido si el archivo es gigante.",
            "⚖️ *Crítico:* lo anoto: orientación fuerte, no sentencia absoluta.",
            "🧠 *Jefe:* muestra aceptada. Si hay incendio, igual se va a notar.",
        ]))

    if "filas útiles" in low or "columnas" in low:
        out.append(elegir([
            "👁️ *Lector:* ya tengo el mapa del terreno.",
            "🧹 *Limpiador:* si hay columnas basura, las voy a mirar feo.",
            "📊 *Analista:* con filas y columnas claras, ya podemos trabajar.",
        ]))

    if "duplicada" in low or "duplicadas" in low or "duplicado" in low:
        out.append(elegir([
            "🕵️ *Detective:* duplicado encontrado. Esto huele a copia o proceso repetido.",
            "📊 *Analista:* ojo, esto puede inflar totales.",
            "⚖️ *Crítico:* consenso: revisar antes de usar en informe.",
        ]))

    if "vacía" in low or "vacías" in low or "vacíos" in low:
        out.append(elegir([
            "🧹 *Limpiador:* los vacíos no siempre son error, pero siempre merecen explicación.",
            "🧠 *Jefe:* vacío sin justificación es sospechoso.",
            "📊 *Analista:* vacíos pueden torcer promedios y filtros.",
        ]))

    if "rango usado falso" in low or "inflado" in low:
        out.append(elegir([
            "🧹 *Limpiador:* clásico Excel con gimnasio: pesa mucho y trae poco.",
            "⚖️ *Crítico:* recomendación probable: copiar rango útil a archivo nuevo.",
            "🐝 *Obrera 7:* ese Excel necesita dieta.",
        ]))

    if "detalles humanos" in low or "detective fino" in low:
        out.append(elegir([
            "🔤 *Detective fino:* aquí entran las cosas que el ojo cansado deja pasar.",
            "🐝 *Obrera 7:* doble espacio detectado, mi momento ha llegado.",
            "🕵️ *Detective:* esto no rompe todo, pero es de esos detalles traicioneros.",
        ]))

    if "dobles espacios" in low:
        out.append(elegir([
            "🧹 *Limpiador:* doble espacio parece chico, pero ensucia búsquedas.",
            "📊 *Analista:* también afecta comparaciones exactas.",
            "🔤 *Detective fino:* dos espacios, dos sospechas.",
        ]))

    if "typo" in low or "posibles typos" in low:
        out.append(elegir([
            "🔤 *Detective fino:* no acuso, sugiero revisar. Soy sapo, no juez.",
            "⚖️ *Crítico:* correcto. Todo typo sugerido debe validarse manualmente.",
            "🧠 *Jefe:* marcar como sospechoso, no como culpable.",
        ]))

    if "correo" in low or "email" in low:
        out.append(elegir([
            "🕵️ *Detective:* si el correo está raro, el envío puede fallar.",
            "📊 *Analista:* conviene separar inválidos, raros y dominios.",
            "⚖️ *Crítico:* correo sospechoso no se automatiza sin mirar.",
        ]))

    if "puntaje de salud" in low or "salud" in low:
        out.append(elegir([
            "⚖️ *Crítico:* el puntaje no es castigo, es semáforo.",
            "🧠 *Jefe:* si está bajo, no se llora: se limpia.",
            "📊 *Analista:* puntaje sirve para priorizar, no para humillar al Excel.",
        ]))

    return out


def _frase_jefe_final(health_score: int) -> str:
    if health_score >= 85:
        return elegir([
            "🧠 *Jefe:* consenso alcanzado. Archivo sano, pero no inmortal.",
            "🧠 *Jefe:* aprobado con revisión normal. Que no se agrande el Excel.",
            "🧠 *Jefe:* la colmena queda tranquila. Buen archivo.",
        ])

    if health_score >= 60:
        return elegir([
            "🧠 *Jefe:* consenso alcanzado. Archivo usable, pero con tareas.",
            "🧠 *Jefe:* no está destruido, pero tampoco está para confiarse.",
            "🧠 *Jefe:* se puede trabajar, pero primero limpieza.",
        ])

    return elegir([
        "🧠 *Jefe:* consenso alcanzado. Este archivo necesita cariño urgente.",
        "🧠 *Jefe:* archivo delicado. No lo usaría sin limpieza previa.",
        "🧠 *Jefe:* aquí hay pega. La colmena recomienda limpiar antes de reportar.",
    ])


def _decidir_modo(context: ContextTypes.DEFAULT_TYPE, health_score: int) -> str:
    conteo = context.user_data.get("archivos_analizados", 0) + 1
    context.user_data["archivos_analizados"] = conteo

    if health_score < 60:
        return "completo"

    if conteo == 1:
        return "completo"

    if conteo == 2:
        return "medio"

    return "compacto"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["archivos_analizados"] = 0
    await update.effective_message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = update.effective_message.text or ""

    if texto.lower().strip() in ["/reset", "reset", "reiniciar"]:
        context.user_data["archivos_analizados"] = 0
        await update.effective_message.reply_text("🔄 Contador reiniciado. El próximo archivo tendrá debate completo.")
        return

    await update.effective_message.reply_text(
        "🐝 Mándame un archivo `CSV`, `XLSX` o `XLSM` y activo la colmena.\n\n"
        "Tip: escribe `reset` si quieres que el próximo análisis sea debate completo otra vez.",
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

        modo = _decidir_modo(context, report.health_score)

        if modo == "completo":
            await msg.reply_text("🐝 Modo debate completo activado.")
        elif modo == "medio":
            await msg.reply_text("🐝 Modo debate medio activado. Vamos más directo.")
        else:
            await msg.reply_text("🐝 Modo compacto activado. No repetiré todo el show.")

        await _send_debate_line_by_line(update, report.debate_lines, modo, report.health_score)

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