"""Maneja Telegram: comandos, carga de archivos y debate dinámico de Colmena BOT."""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import List

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
from core.limits import MAX_FILE_BYTES
from core.reader import SUPPORTED_EXTENSIONS, load_file
from core.report import build_report
from core.text_quality import analyze_text_quality
from core.utils import human_size, safe_remove, slugify, temp_path


log = logging.getLogger(__name__)


PAUSA_DEBATE = 1.0

MAX_LINEAS_SHOW = 70
MAX_LINEAS_NORMAL = 38
MAX_LINEAS_COMPACTO = 14
MAX_LINEAS_SILENCIOSO = 4


MODOS_VALIDOS = {"auto", "show", "normal", "compacto", "silencioso"}


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
    "Comandos útiles:\n"
    "/modo auto\n"
    "/modo show\n"
    "/modo normal\n"
    "/modo compacto\n"
    "/modo silencioso\n"
    "/humor on\n"
    "/humor off\n"
    "/reset"
)


HELP = (
    "🐝 Ayuda de Colmena BOT\n\n"
    "Formatos aceptados:\n"
    "- CSV\n"
    "- XLSX\n"
    "- XLSM\n\n"
    f"Tamaño máximo: {human_size(MAX_FILE_BYTES)}\n\n"
    "Modos:\n"
    "show → debate largo, más entretenido\n"
    "normal → debate equilibrado\n"
    "compacto → directo al grano\n"
    "silencioso → casi solo resumen y TXT\n"
    "auto → decide según archivo y uso\n\n"
    "Regla del modo auto:\n"
    "1er archivo: show\n"
    "2do archivo: normal\n"
    "3er archivo en adelante: compacto\n"
    "Si el archivo viene grave, vuelve a show.\n\n"
    "Comandos:\n"
    "/modo auto\n"
    "/modo show\n"
    "/modo normal\n"
    "/modo compacto\n"
    "/modo silencioso\n"
    "/humor on\n"
    "/humor off\n"
    "/reset"
)


def elegir(frases: List[str]) -> str:
    return random.choice(frases)


def get_user_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    context.user_data.setdefault("archivos_analizados", 0)
    context.user_data.setdefault("modo", "auto")
    context.user_data.setdefault("humor", True)
    return context.user_data


async def decir(update: Update, texto: str, pausa: float = PAUSA_DEBATE) -> None:
    msg = update.effective_message
    await msg.chat.send_action(ChatAction.TYPING)
    await asyncio.sleep(pausa)
    await msg.reply_text(texto)


async def enviar_lineas(update: Update, lineas: List[str], pausa: float = PAUSA_DEBATE) -> None:
    for linea in lineas:
        await decir(update, linea, pausa=pausa)


async def enviar_bloque(update: Update, lineas: List[str], max_chars: int = 3500) -> None:
    msg = update.effective_message
    buffer = ""

    for linea in lineas:
        candidato = buffer + "\n" + linea if buffer else linea

        if len(candidato) > max_chars:
            await msg.reply_text(buffer)
            await asyncio.sleep(0.4)
            buffer = linea
        else:
            buffer = candidato

    if buffer:
        await msg.reply_text(buffer)


def severidad(health_score: int) -> str:
    if health_score < 50:
        return "grave"
    if health_score < 70:
        return "media"
    if health_score < 85:
        return "leve"
    return "sano"


def decidir_modo(context: ContextTypes.DEFAULT_TYPE, health_score: int) -> str:
    state = get_user_state(context)
    modo_usuario = state.get("modo", "auto")

    if modo_usuario != "auto":
        return modo_usuario

    state["archivos_analizados"] += 1
    conteo = state["archivos_analizados"]

    sev = severidad(health_score)

    if sev == "grave":
        return "show"

    if sev == "media":
        return "normal"

    if conteo == 1:
        return "show"

    if conteo == 2:
        return "normal"

    return "compacto"


def explicar_modo(modo: str, health_score: int) -> str:
    sev = severidad(health_score)

    if modo == "show":
        if sev == "grave":
            return "🐝 Modo show activado: este archivo viene delicado y merece mesa completa."
        return "🐝 Modo show activado: hoy la colmena conversa con ganas."

    if modo == "normal":
        return "🐝 Modo normal activado: debate claro, sin alargarlo de más."

    if modo == "compacto":
        return "🐝 Modo compacto activado: voy al grano para no repetir todo el show."

    if modo == "silencioso":
        return "🐝 Modo silencioso activado: análisis rápido, resumen y TXT."

    return "🐝 Modo auto activado."


def preparar_debate(lines: List[str], modo: str, health_score: int, humor: bool) -> List[str]:
    if modo == "show":
        return debate_show(lines, health_score, humor)

    if modo == "normal":
        return debate_normal(lines, health_score, humor)

    if modo == "compacto":
        return debate_compacto(lines, health_score, humor)

    if modo == "silencioso":
        return debate_silencioso(lines, health_score)

    return debate_normal(lines, health_score, humor)


def limitar_lineas(lines: List[str], modo: str) -> List[str]:
    limites = {
        "show": MAX_LINEAS_SHOW,
        "normal": MAX_LINEAS_NORMAL,
        "compacto": MAX_LINEAS_COMPACTO,
        "silencioso": MAX_LINEAS_SILENCIOSO,
    }

    limite = limites.get(modo, MAX_LINEAS_NORMAL)

    if len(lines) <= limite:
        return lines

    recortadas = len(lines) - limite
    return lines[:limite] + [
        f"🧠 Jefe: hay {recortadas} intervención(es) más. Las dejé completas en el reporte TXT."
    ]


def debate_show(lines: List[str], health_score: int, humor: bool) -> List[str]:
    out: List[str] = []

    out.extend([
        elegir([
            "🐝 La colmena se está organizando...",
            "🐝 Se abre la sala de revisión. Que entren los mini-bots.",
            "🐝 Colmena activada. Hoy nadie revisa solo.",
            "🐝 Mesa abierta. El archivo será interrogado con respeto.",
        ]),
        elegir([
            "🧠 Jefe: orden en la colmena. Primero leer, después opinar.",
            "🧠 Jefe: nadie se me arranca. Vamos por partes.",
            "🧠 Jefe: quiero hallazgos, no humo.",
            "🧠 Jefe: revisión completa, pero con cerebro.",
        ]),
        elegir([
            "👁️ Lector: abro el archivo y miro estructura.",
            "👁️ Lector: voy por hojas, filas, columnas y señales raras.",
            "👁️ Lector: si hay columnas fantasmas, las voy a ver.",
        ]),
        elegir([
            "🛡️ Inspector: modo seguro activado. Las macros no se ejecutan.",
            "🛡️ Inspector: aquí miramos, no apretamos botones peligrosos.",
            "🛡️ Inspector: si viene XLSM, lo trato con cuidado.",
        ]),
    ])

    if humor:
        out.append(elegir([
            "🐝 Obrera 7: traje café, esto puede ponerse interesante.",
            "🐝 Obrera 12: si el Excel pesa 12 MB y trae 40 filas, sospecho.",
            "🐝 Obrera 3: yo solo digo... los dobles espacios no se van solos.",
        ]))

    for line in lines:
        out.append(line)
        out.extend(reacciones(line, humor))

    out.extend([
        "🐝 Mesa chica final...",
        "🕵️ Detective: presenté los hallazgos.",
        "📊 Analista: estimé impacto.",
        "🧹 Limpiador: propuse limpieza.",
        "⚖️ Crítico: listo para veredicto.",
        frase_jefe_final(health_score),
    ])

    return out


def debate_normal(lines: List[str], health_score: int, humor: bool) -> List[str]:
    out: List[str] = []

    out.extend([
        elegir([
            "🐝 Debate normal activado.",
            "🐝 Nueva revisión. Esta vez vamos más directo.",
            "🐝 La colmena entra en modo preciso.",
        ]),
        elegir([
            "🧠 Jefe: revisemos lo importante sin dar la lata.",
            "🧠 Jefe: precisión, mini-bots.",
            "🧠 Jefe: vamos al hueso del archivo.",
        ]),
    ])

    importantes = filtrar_importantes(lines)

    for line in importantes:
        out.append(line)
        low = line.lower()

        if "duplic" in low:
            out.append("🕵️ Detective: duplicados aceptados como riesgo. Pueden inflar resultados.")
        elif "vac" in low:
            out.append("🧹 Limpiador: vacío detectado. Hay que justificarlo o corregirlo.")
        elif "correo" in low or "email" in low:
            out.append("🕵️ Detective: si el correo falla, la automatización falla.")
        elif "typo" in low or "dobles espacios" in low or "detalles humanos" in low:
            out.append("🔤 Detective fino: detalle pequeño, pero de los que después molestan.")
        elif "macro" in low or "xlsm" in low:
            out.append("🛡️ Inspector: correcto, macros no ejecutadas.")
        elif "salud" in low or "puntaje" in low:
            out.append("⚖️ Crítico: puntaje leído como semáforo.")

    if humor:
        out.append(elegir([
            "🐝 Obrera 7: suficiente show, jefe. Ya entendimos el drama.",
            "🐝 Obrera 12: resumen decente, sin novela.",
            "🐝 Obrera 3: apruebo el formato, no me dormí.",
        ]))

    out.append(frase_jefe_final(health_score))
    return out


def debate_compacto(lines: List[str], health_score: int, humor: bool) -> List[str]:
    importantes = filtrar_importantes(lines)

    out: List[str] = []

    out.extend([
        elegir([
            "🐝 Modo compacto.",
            "🐝 Voy corto para no aburrirte.",
            "🐝 Resumen rápido de la colmena.",
            "🐝 Revisión express, sin perder lo importante.",
        ]),
        elegir([
            "🧠 Jefe: solo lo importante.",
            "🧠 Jefe: sin show largo, vamos al resultado.",
            "🧠 Jefe: golpes precisos.",
        ]),
    ])

    out.extend(importantes[:8])

    if health_score < 60:
        out.append("⚠️ Crítico: aunque estoy compacto, este archivo viene delicado.")
        out.append("🧠 Jefe: recomiendo mirar el TXT completo.")
    elif health_score < 85:
        out.append("⚖️ Crítico: usable, pero con detalles.")
    else:
        out.append("✅ Crítico: archivo bastante sano.")

    if humor:
        out.append(elegir([
            "🐝 Obrera 7: corto y al panal.",
            "🐝 Obrera 12: sin tesis, pero con alerta.",
            "🐝 Obrera 3: compacto no significa ciego.",
        ]))

    return out


def debate_silencioso(lines: List[str], health_score: int) -> List[str]:
    importantes = filtrar_importantes(lines)

    out = [
        "🐝 Modo silencioso.",
        f"🩺 Salud estimada: {health_score}/100.",
    ]

    out.extend(importantes[:2])
    out.append("📝 El detalle va en el TXT.")
    return out


def filtrar_importantes(lines: List[str]) -> List[str]:
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
        "outlier",
    ]

    importantes = []

    for line in lines:
        low = line.lower()
        if any(c in low for c in claves):
            importantes.append(line)

    return importantes or lines[:8]


def reacciones(line: str, humor: bool) -> List[str]:
    out: List[str] = []
    low = line.lower()

    if "xlsm" in low or "macro" in low:
        out.append(elegir([
            "🛡️ Inspector: macros vistas, manos quietas.",
            "🛡️ Inspector: las macros se miran, no se ejecutan.",
            "⚖️ Crítico: archivo con macros merece respeto.",
        ]))

    if "modo seguro" in low:
        out.append(elegir([
            "🛡️ Inspector: modo seguro no es cobardía, es supervivencia.",
            "🧠 Jefe: mejor lento y vivo que rápido y caído.",
            "🐝 Obrera 12: nada de comerse el Excel completo de una.",
        ]))

    if "muestra" in low:
        out.append(elegir([
            "📊 Analista: muestra aceptada si el archivo es gigante.",
            "⚖️ Crítico: orientación fuerte, no sentencia absoluta.",
            "🧠 Jefe: si hay incendio, igual se nota en la muestra.",
        ]))

    if "filas útiles" in low or "columnas" in low:
        out.append(elegir([
            "👁️ Lector: ya tengo el mapa del terreno.",
            "📊 Analista: con estructura clara, se puede trabajar.",
            "🧹 Limpiador: si hay columnas basura, las voy a mirar feo.",
        ]))

    if "duplicada" in low or "duplicadas" in low or "duplicado" in low:
        out.append(elegir([
            "🕵️ Detective: duplicado encontrado. Huele a copia o proceso repetido.",
            "📊 Analista: esto puede inflar totales.",
            "⚖️ Crítico: revisar antes de usar en informe.",
        ]))

    if "vacía" in low or "vacías" in low or "vacíos" in low:
        out.append(elegir([
            "🧹 Limpiador: los vacíos no siempre son error, pero siempre piden explicación.",
            "🧠 Jefe: vacío sin justificación es sospechoso.",
            "📊 Analista: vacíos pueden torcer promedios y filtros.",
        ]))

    if "rango usado falso" in low or "inflado" in low:
        out.append(elegir([
            "🧹 Limpiador: clásico Excel con gimnasio: pesa mucho y trae poco.",
            "⚖️ Crítico: copiar rango útil a archivo nuevo suena razonable.",
            "🐝 Obrera 7: ese Excel necesita dieta.",
        ]))

    if "detalles humanos" in low or "detective fino" in low:
        out.append(elegir([
            "🔤 Detective fino: aquí entran las cosas que el ojo cansado deja pasar.",
            "🐝 Obrera 7: doble espacio detectado, mi momento ha llegado.",
            "🕵️ Detective: esto no rompe todo, pero es traicionero.",
        ]))

    if "dobles espacios" in low:
        out.append(elegir([
            "🧹 Limpiador: doble espacio parece chico, pero ensucia búsquedas.",
            "📊 Analista: también afecta comparaciones exactas.",
            "🔤 Detective fino: dos espacios, dos sospechas.",
        ]))

    if "typo" in low or "posibles typos" in low:
        out.append(elegir([
            "🔤 Detective fino: no acuso, sugiero revisar. Soy sapo, no juez.",
            "⚖️ Crítico: todo typo sugerido debe validarse manualmente.",
            "🧠 Jefe: marcar sospechoso, no culpable.",
        ]))

    if "correo" in low or "email" in low:
        out.append(elegir([
            "🕵️ Detective: si el correo está raro, el envío puede fallar.",
            "📊 Analista: conviene separar inválidos, raros y dominios.",
            "⚖️ Crítico: correo sospechoso no se automatiza sin mirar.",
        ]))

    if "puntaje de salud" in low or "salud" in low:
        out.append(elegir([
            "⚖️ Crítico: el puntaje no es castigo, es semáforo.",
            "🧠 Jefe: si está bajo, no se llora: se limpia.",
            "📊 Analista: sirve para priorizar, no para humillar al Excel.",
        ]))

    if humor and random.random() < 0.12:
        out.append(elegir([
            "🐝 Obrera random: anotado en el panal.",
            "🐝 Obrera 4: esto merece amarillo fosforescente.",
            "🐝 Zángano junior: entendí poco, pero se ve sospechoso.",
            "🐝 Obrera 9: sigo revisando, no molesten.",
        ]))

    return out


def frase_jefe_final(health_score: int) -> str:
    if health_score >= 85:
        return elegir([
            "🧠 Jefe: consenso alcanzado. Archivo sano, pero no inmortal.",
            "🧠 Jefe: aprobado con revisión normal.",
            "🧠 Jefe: la colmena queda tranquila. Buen archivo.",
        ])

    if health_score >= 60:
        return elegir([
            "🧠 Jefe: consenso alcanzado. Archivo usable, pero con tareas.",
            "🧠 Jefe: no está destruido, pero tampoco está para confiarse.",
            "🧠 Jefe: se puede trabajar, pero primero limpieza.",
        ])

    return elegir([
        "🧠 Jefe: consenso alcanzado. Este archivo necesita cariño urgente.",
        "🧠 Jefe: archivo delicado. No lo usaría sin limpieza previa.",
        "🧠 Jefe: aquí hay pega. Limpieza antes de reportar.",
    ])


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
        "🔄 Listo. Reinicié el contador. El próximo archivo usará debate completo si el modo está en auto."
    )


async def cmd_modo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_user_state(context)

    if not context.args:
        await update.effective_message.reply_text(
            f"Modo actual: {state.get('modo', 'auto')}\n\n"
            "Usa:\n"
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
            "Modo no válido.\n\n"
            "Opciones:\n"
            "auto, show, normal, compacto, silencioso"
        )
        return

    state["modo"] = nuevo
    await update.effective_message.reply_text(f"🐝 Modo cambiado a: {nuevo}")


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
        await update.effective_message.reply_text("🐝 Humor activado. Las obreras vuelven a opinar.")
    elif valor in {"off", "no", "false", "0"}:
        state["humor"] = False
        await update.effective_message.reply_text("🧘 Humor desactivado. Colmena seria.")
    else:
        await update.effective_message.reply_text("Usa /humor on o /humor off")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (update.effective_message.text or "").lower().strip()

    if texto in {"reset", "reiniciar"}:
        await cmd_reset(update, context)
        return

    await update.effective_message.reply_text(
        "🐝 Mándame un archivo CSV, XLSX o XLSM y activo la colmena.\n\n"
        "Comandos útiles:\n"
        "/modo auto\n"
        "/modo show\n"
        "/modo compacto\n"
        "/humor on\n"
        "/humor off\n"
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
    humor = bool(state.get("humor", True))

    await msg.chat.send_action(ChatAction.TYPING)
    await msg.reply_text("🐝 Recibí el archivo. Convocando a la colmena...")

    download_path = temp_path(suffix=ext)
    txt_path = temp_path(suffix=".txt")

    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=download_path)

        await decir(update, "👁️ Lector: descargué el archivo. Lo voy a inspeccionar.")
        await decir(update, "🛡️ Inspector: abriendo en modo seguro.")

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

        await decir(update, "📊 Analista: datos cargados. Empieza la revisión pesada.")

        analysis = await loop.run_in_executor(None, analyze_dataframe, df)

        await decir(update, "🔤 Detective fino: revisando textos, correos, espacios y typos.")

        text_quality = await loop.run_in_executor(None, analyze_text_quality, df)

        await decir(update, "📝 Constructor: preparando debate, resumen y TXT.")

        report = await loop.run_in_executor(
            None,
            build_report,
            loaded,
            analysis,
            text_quality,
            txt_path,
        )

        modo = decidir_modo(context, report.health_score)

        await msg.reply_text(explicar_modo(modo, report.health_score))

        debate = preparar_debate(
            report.debate_lines,
            modo=modo,
            health_score=report.health_score,
            humor=humor,
        )

        debate = limitar_lineas(debate, modo)

        await enviar_lineas(update, debate)

        await decir(update, "📋 Resumen corto de la colmena:")
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

        await decir(update, "✅ Colmena finalizada. Puedes enviarme otro archivo.")

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
    app.add_handler(CommandHandler("modo", cmd_modo))
    app.add_handler(CommandHandler("humor", cmd_humor))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))