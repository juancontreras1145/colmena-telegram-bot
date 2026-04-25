"""Motor de debate dinámico para Colmena BOT.

Este módulo decide:
- qué tan largo será el debate
- qué tono usar
- qué mensajes mostrar
- cómo evitar repetir siempre lo mismo
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List


MODOS_VALIDOS = {"auto", "show", "normal", "compacto", "silencioso"}
ESTILOS_VALIDOS = {"equilibrado", "serio", "humor", "duro"}

MAX_LINEAS = {
    "show": 75,
    "normal": 42,
    "compacto": 16,
    "silencioso": 5,
}


@dataclass
class DebateConfig:
    modo: str
    estilo: str
    humor: bool
    health_score: int
    archivo_numero: int


def elegir(frases: List[str]) -> str:
    return random.choice(frases)


def severidad(health_score: int) -> str:
    if health_score < 45:
        return "grave"
    if health_score < 65:
        return "media"
    if health_score < 85:
        return "leve"
    return "sano"


def decidir_modo(user_data: dict, health_score: int) -> str:
    modo_usuario = user_data.get("modo", "auto")

    if modo_usuario != "auto":
        return modo_usuario

    user_data["archivos_analizados"] = user_data.get("archivos_analizados", 0) + 1
    conteo = user_data["archivos_analizados"]

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


def explicar_modo(config: DebateConfig) -> str:
    sev = severidad(config.health_score)

    if config.modo == "show":
        if sev == "grave":
            return "🐝 Modo show activado: este archivo viene delicado, así que llamé a toda la colmena."
        return "🐝 Modo show activado: revisión completa, con debate y mini-bots opinando."

    if config.modo == "normal":
        return "🐝 Modo normal activado: debate claro, sin hacerlo eterno."

    if config.modo == "compacto":
        return "🐝 Modo compacto activado: voy directo a lo importante."

    if config.modo == "silencioso":
        return "🐝 Modo silencioso activado: casi todo irá al reporte TXT."

    return "🐝 Modo auto activado."


def crear_debate(report_lines: List[str], config: DebateConfig) -> List[str]:
    if config.modo == "show":
        lineas = debate_show(report_lines, config)
    elif config.modo == "normal":
        lineas = debate_normal(report_lines, config)
    elif config.modo == "compacto":
        lineas = debate_compacto(report_lines, config)
    elif config.modo == "silencioso":
        lineas = debate_silencioso(report_lines, config)
    else:
        lineas = debate_normal(report_lines, config)

    return limitar_lineas(lineas, config.modo)


def limitar_lineas(lineas: List[str], modo: str) -> List[str]:
    limite = MAX_LINEAS.get(modo, 42)

    if len(lineas) <= limite:
        return lineas

    sobrantes = len(lineas) - limite

    return lineas[:limite] + [
        f"🧠 Jefe: hay {sobrantes} intervención(es) más. Las dejé completas en el TXT."
    ]


def debate_show(lines: List[str], config: DebateConfig) -> List[str]:
    out: List[str] = []

    out.extend(apertura_show(config))

    importantes = filtrar_importantes(lines)

    if importantes:
        out.append("🧠 Jefe: primero van los puntos importantes. Después discutimos impacto.")
    else:
        out.append("🧠 Jefe: no veo alertas fuertes, pero igual haremos una pasada seria.")

    for line in lines:
        out.append(line)
        out.extend(reacciones(line, config))

    out.extend(cierre_debate(config))

    return out


def debate_normal(lines: List[str], config: DebateConfig) -> List[str]:
    out: List[str] = []

    out.extend([
        elegir([
            "🐝 Debate normal activado.",
            "🐝 Nueva revisión. Esta vez vamos al grano.",
            "🐝 Colmena en modo preciso.",
            "🐝 Revisión equilibrada: ni show eterno ni silencio total.",
        ]),
        elegir([
            "🧠 Jefe: quiero lo importante, sin relleno.",
            "🧠 Jefe: mini-bots, precisión.",
            "🧠 Jefe: al hueso del archivo.",
        ]),
    ])

    importantes = filtrar_importantes(lines)

    for line in importantes:
        out.append(line)
        out.extend(reacciones_resumidas(line, config))

    out.append(frase_jefe_final(config.health_score))

    return out


def debate_compacto(lines: List[str], config: DebateConfig) -> List[str]:
    importantes = filtrar_importantes(lines)

    out: List[str] = [
        elegir([
            "🐝 Modo compacto.",
            "🐝 Voy corto para no aburrirte.",
            "🐝 Resumen rápido de la colmena.",
            "🐝 Revisión express.",
        ]),
        elegir([
            "🧠 Jefe: solo lo importante.",
            "🧠 Jefe: sin show largo, vamos al resultado.",
            "🧠 Jefe: golpes precisos.",
        ]),
    ]

    out.extend(importantes[:10])

    if config.health_score < 60:
        out.append("⚠️ Crítico: aunque voy compacto, este archivo viene delicado.")
        out.append("🧠 Jefe: recomiendo revisar el TXT completo.")
    elif config.health_score < 85:
        out.append("⚖️ Crítico: archivo usable, pero con detalles.")
    else:
        out.append("✅ Crítico: archivo bastante sano.")

    if config.humor:
        out.append(elegir([
            "🐝 Obrera 7: corto y al panal.",
            "🐝 Obrera 12: sin novela, pero con alerta.",
            "🐝 Obrera 3: compacto no significa ciego.",
        ]))

    return out


def debate_silencioso(lines: List[str], config: DebateConfig) -> List[str]:
    importantes = filtrar_importantes(lines)

    out = [
        "🐝 Modo silencioso.",
        f"🩺 Salud estimada: {config.health_score}/100.",
    ]

    out.extend(importantes[:2])
    out.append("📝 El detalle completo va en el TXT.")

    return out


def apertura_show(config: DebateConfig) -> List[str]:
    out = []

    out.append(elegir([
        "🐝 La colmena se está organizando...",
        "🐝 Se abre la sala de revisión. Que entren los mini-bots.",
        "🐝 Colmena activada. Hoy nadie revisa solo.",
        "🐝 Mesa abierta. El archivo será interrogado con respeto.",
    ]))

    out.append(elegir([
        "🧠 Jefe: orden en la colmena. Primero mirar, después opinar.",
        "🧠 Jefe: nadie se me arranca. Vamos por partes.",
        "🧠 Jefe: quiero hallazgos, no humo.",
        "🧠 Jefe: revisión completa, pero con cerebro.",
    ]))

    out.append(elegir([
        "👁️ Lector: abro el archivo y reviso estructura.",
        "👁️ Lector: voy por hojas, filas, columnas y señales raras.",
        "👁️ Lector: si hay columnas fantasmas, las voy a ver.",
    ]))

    out.append(elegir([
        "🛡️ Inspector: modo seguro activado. Las macros no se ejecutan.",
        "🛡️ Inspector: aquí miramos, no apretamos botones peligrosos.",
        "🛡️ Inspector: si viene XLSM, lo trato con cuidado.",
    ]))

    if config.humor and config.estilo in {"equilibrado", "humor"}:
        out.append(elegir([
            "🐝 Obrera 7: traje café, esto puede ponerse interesante.",
            "🐝 Obrera 12: si el Excel pesa 12 MB y trae 40 filas, sospecho.",
            "🐝 Obrera 3: yo solo digo... los dobles espacios no se van solos.",
            "🐝 Zángano junior: prometo no tocar macros.",
        ]))

    if config.estilo == "duro":
        out.append("⚖️ Crítico: hoy no venimos a ser simpáticos. Venimos a encontrar problemas.")

    if config.estilo == "serio":
        out.append("⚖️ Crítico: mantendremos tono serio y revisión objetiva.")

    return out


def cierre_debate(config: DebateConfig) -> List[str]:
    out = [
        "🐝 Mesa chica final...",
        "🕵️ Detective: hallazgos presentados.",
        "📊 Analista: impacto estimado.",
        "🧹 Limpiador: acciones de limpieza sugeridas.",
        "⚖️ Crítico: listo para veredicto.",
        frase_jefe_final(config.health_score),
    ]

    if config.humor and config.estilo in {"equilibrado", "humor"}:
        out.append(elegir([
            "🐝 Obrera 7: cierro el panal, pero dejo el TXT en la mesa.",
            "🐝 Obrera 12: si alguien ignora el reporte, yo no fui.",
            "🐝 Zángano junior: sobrevivimos al Excel.",
        ]))

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
        "crítica",
        "grave",
        "inconsist",
    ]

    importantes = []

    for line in lines:
        low = line.lower()
        if any(c in low for c in claves):
            importantes.append(line)

    return importantes or lines[:8]


def reacciones_resumidas(line: str, config: DebateConfig) -> List[str]:
    low = line.lower()

    if "duplic" in low:
        return ["🕵️ Detective: duplicado aceptado como riesgo. Puede inflar resultados."]

    if "vac" in low:
        return ["🧹 Limpiador: vacío detectado. Hay que justificarlo o corregirlo."]

    if "correo" in low or "email" in low:
        return ["🕵️ Detective: si el correo falla, la automatización falla."]

    if "typo" in low or "dobles espacios" in low or "detalles humanos" in low:
        return ["🔤 Detective fino: detalle pequeño, pero de los que después molestan."]

    if "macro" in low or "xlsm" in low:
        return ["🛡️ Inspector: correcto, macros no ejecutadas."]

    if "salud" in low or "puntaje" in low:
        return ["⚖️ Crítico: puntaje leído como semáforo."]

    return []


def reacciones(line: str, config: DebateConfig) -> List[str]:
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

    if config.estilo == "duro" and random.random() < 0.18:
        out.append(elegir([
            "⚖️ Crítico: esto no lo dejaría pasar sin evidencia.",
            "⚖️ Crítico: aceptable solo si alguien lo justifica.",
            "⚖️ Crítico: sospechoso hasta que se demuestre lo contrario.",
        ]))

    if config.humor and config.estilo in {"equilibrado", "humor"} and random.random() < 0.12:
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
