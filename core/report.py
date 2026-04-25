"""Constructor: arma el debate de la colmena, el resumen para Telegram y el reporte TXT."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .analyzer import AnalysisReport, Finding
from .reader import LoadedFile
from .text_quality import TextQualityReport
from .utils import human_size, now_str, percentage, truncate


SEVERITY_ORDER = {"critico": 0, "alto": 1, "medio": 2, "bajo": 3}
SEVERITY_LABEL = {
    "critico": "🔴 CRÍTICO",
    "alto": "🟠 ALTO",
    "medio": "🟡 MEDIO",
    "bajo": "🟢 LEVE",
}


@dataclass
class ColmenaReport:
    debate_lines: List[str] = field(default_factory=list)  # mensajes para Telegram
    summary_lines: List[str] = field(default_factory=list)  # resumen corto Telegram
    txt_path: Optional[str] = None
    health_score: int = 100
    health_label: str = ""


def _sorted_findings(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))


def _debate(file: LoadedFile, analysis: AnalysisReport,
            text_quality: TextQualityReport) -> List[str]:
    """Genera el debate de la colmena en mensajes cortos estilo chat."""
    lines: List[str] = []
    lines.append("🐝 *Mesa de debate abierta.*")
    lines.append(
        f"👁️ *Lector:* archivo `{file.file_name}` ({human_size(file.file_size)}), "
        f"tipo `{file.extension}`."
    )

    if file.workbook_profile:
        wp = file.workbook_profile
        lines.append(
            f"👁️ *Lector:* {wp.sheet_count} hoja(s). Hoja sugerida con datos: "
            f"`{wp.best_sheet or 'ninguna'}`."
        )
        if wp.is_xlsm:
            lines.append(
                f"🛡️ *Inspector:* archivo `.xlsm` "
                + ("CON macros detectadas (NO ejecutadas)." if wp.has_macros else "sin macros visibles.")
            )
        if wp.inflated_workbook:
            lines.append("🛡️ *Inspector:* el libro se ve inflado para los datos reales que tiene.")
        for s in wp.sheets:
            if s.inflated:
                lines.append(
                    f"🧹 *Limpiador:* la hoja `{s.name}` declara "
                    f"{s.declared_rows}x{s.declared_cols} pero los datos reales son "
                    f"{s.real_rows}x{s.real_cols}. Rango usado falso por formato."
                )

    if file.safe_mode:
        lines.append("🛡️ *Inspector:* activé *modo seguro* para no colapsar el servidor.")
    if file.truncated:
        lines.append("🛡️ *Inspector:* analicé una *muestra* del archivo, no el 100%.")

    df = file.primary_df
    if df is None or df.empty:
        lines.append("⚖️ *Crítico:* no hay datos para analizar. Cierro la mesa.")
        return lines

    lines.append(
        f"📊 *Analista:* {analysis.rows:,} filas útiles x {analysis.cols} columnas. "
        f"Numéricas: {len(analysis.numeric_columns)}."
    )

    if analysis.duplicates:
        lines.append(f"🕵️ *Detective:* hay {analysis.duplicates} filas duplicadas. Confirmo el hallazgo.")
        lines.append("🧹 *Limpiador:* esto puede romper filtros o reportes.")
        lines.append("📊 *Analista:* puede afectar conteos, totales o decisiones.")
        lines.append("⚖️ *Crítico:* aceptado. Debe revisarse antes de usar el archivo.")

    if analysis.fully_empty_columns:
        lines.append(
            f"🧹 *Limpiador:* hay {len(analysis.fully_empty_columns)} columna(s) "
            "completamente vacías. Sugiero eliminarlas."
        )

    if analysis.high_null_columns:
        lines.append(
            f"🧹 *Limpiador:* hay {len(analysis.high_null_columns)} columna(s) "
            "con muchos vacíos. Decidir si conservarlas."
        )

    # Agrupamos hallazgos por severidad para no saturar el chat.
    by_sev = {"critico": [], "alto": [], "medio": [], "bajo": []}
    for f in analysis.findings:
        by_sev.setdefault(f.severity, []).append(f)

    for f in by_sev["critico"][:3]:
        lines.append(f"⚖️ *Crítico:* 🔴 {f.issue}. {f.details}")
    for f in by_sev["alto"][:5]:
        lines.append(f"🕵️ *Detective:* 🟠 {f.issue}.")

    if text_quality.findings:
        lines.append(f"🔤 *Detective fino:* encontré {len(text_quality.findings)} detalles humanos:")
        for tf in text_quality.findings[:5]:
            ej = f" Ej: {tf.examples[0]}" if tf.examples else ""
            lines.append(f"   • `{tf.column}` → {tf.issue} ({tf.count}).{ej}")

    if text_quality.typo_candidates:
        cols = list(text_quality.typo_candidates.keys())[:3]
        lines.append(f"🔤 *Detective fino:* posibles typos en {cols}.")

    lines.append("🧠 *Jefe:* consenso alcanzado.")
    lines.append(
        f"⚖️ *Crítico:* puntaje de salud → *{analysis.health_score}/100* "
        f"({analysis.health_label})."
    )
    return lines


def _summary(file: LoadedFile, analysis: AnalysisReport,
             text_quality: TextQualityReport) -> List[str]:
    s: List[str] = []
    s.append(f"📋 *Resumen — {file.file_name}*")
    s.append(f"• Tamaño: {human_size(file.file_size)} · Tipo: `{file.extension}`")
    s.append(f"• Filas analizadas: {analysis.rows:,} · Columnas: {analysis.cols}")
    s.append(f"• Duplicadas: {analysis.duplicates}")
    s.append(f"• Columnas vacías: {len(analysis.fully_empty_columns)}")
    s.append(f"• Columnas con muchos vacíos: {len(analysis.high_null_columns)}")
    s.append(f"• Hallazgos totales: {len(analysis.findings)} · Detalles finos: {len(text_quality.findings)}")
    s.append(f"• 🩺 Salud: *{analysis.health_score}/100* — {analysis.health_label}")
    if file.safe_mode:
        s.append("• 🛡️ Modo seguro activo (archivo pesado o `.xlsm`).")
    if file.truncated:
        s.append("• ✂️ Se analizó una muestra del archivo.")
    return s


def _recommendations(analysis: AnalysisReport, text_quality: TextQualityReport,
                     file: LoadedFile) -> List[str]:
    recs = [
        "1. Crear una *copia limpia* del archivo antes de editar.",
        "2. Conservar solo las columnas útiles.",
    ]
    if analysis.fully_empty_columns or analysis.high_null_columns:
        recs.append("3. Eliminar columnas vacías o de respaldo si no se usan.")
    if any("Dobles espacios" in tf.issue or "Espacios" in tf.issue for tf in text_quality.findings):
        recs.append("4. Corregir dobles espacios y textos con espacios sobrantes.")
    if any("Correos" in tf.issue or "letras repetidas" in tf.issue.lower() for tf in text_quality.findings):
        recs.append("5. Revisar correos con letras repetidas o nombres raros.")
    if text_quality.typo_candidates:
        recs.append("6. Validar manualmente los typos sugeridos por la colmena.")
    recs.append("7. Guardar una versión liviana y final para trabajo real.")
    if file.workbook_profile and file.workbook_profile.is_xlsm:
        recs.append("8. Si no necesitas las macros, guarda como `.xlsx` para reducir riesgo.")
    return recs


def _build_txt(file: LoadedFile, analysis: AnalysisReport,
               text_quality: TextQualityReport) -> str:
    out: List[str] = []
    p = out.append

    p("=" * 70)
    p("🐝 COLMENA BOT — REPORTE DE ANÁLISIS")
    p("=" * 70)
    p(f"Archivo:       {file.file_name}")
    p(f"Tamaño:        {human_size(file.file_size)}")
    p(f"Tipo:          {file.extension}")
    p(f"Generado:      {now_str()}")
    p(f"Modo seguro:   {'sí' if file.safe_mode else 'no'}")
    p(f"Muestra parcial: {'sí' if file.truncated else 'no'}")
    p("")

    if file.workbook_profile:
        wp = file.workbook_profile
        p("--- Inspector (workbook profile) ---")
        p(f"Hojas totales: {wp.sheet_count}")
        p(f"¿Es .xlsm?: {'sí' if wp.is_xlsm else 'no'}")
        p(f"¿Macros detectadas?: {'sí (NO se ejecutaron)' if wp.has_macros else 'no'}")
        p(f"¿Libro inflado?: {'sí' if wp.inflated_workbook else 'no'}")
        p(f"Hoja sugerida: {wp.best_sheet}")
        for s in wp.sheets:
            tag = " (rango usado FALSO por formato)" if s.inflated else ""
            p(f"  · {s.name}: declarada {s.declared_rows}x{s.declared_cols} | "
              f"real {s.real_rows}x{s.real_cols} | celdas con datos: {s.non_empty_cells}{tag}")
        for n in wp.notes:
            p(f"  ⚠ {n}")
        p("")

    p("--- Resumen general ---")
    p(f"Filas analizadas:          {analysis.rows}")
    p(f"Columnas analizadas:       {analysis.cols}")
    p(f"Duplicadas:                {analysis.duplicates}")
    p(f"Columnas vacías:           {len(analysis.fully_empty_columns)}")
    p(f"Columnas con muchos vacíos:{len(analysis.high_null_columns)}")
    p(f"Columnas numéricas:        {len(analysis.numeric_columns)}")
    p(f"PUNTAJE DE SALUD:          {analysis.health_score}/100 — {analysis.health_label}")
    p("")

    if analysis.fully_empty_columns:
        p("--- Columnas completamente vacías ---")
        for c in analysis.fully_empty_columns:
            p(f"  · {c}")
        p("")
    if analysis.high_null_columns:
        p("--- Columnas con muchos vacíos ---")
        for c in analysis.high_null_columns:
            p(f"  · {c}")
        p("")

    if analysis.duplicate_examples:
        p("--- Ejemplos de filas duplicadas ---")
        for row in analysis.duplicate_examples:
            preview = " | ".join(f"{k}={truncate(str(v), 30)}" for k, v in list(row.items())[:6])
            p(f"  · {preview}")
        p("")

    p("--- Hallazgos por severidad ---")
    if not analysis.findings:
        p("  Sin hallazgos relevantes. 🎉")
    else:
        for f in _sorted_findings(analysis.findings):
            p(f"[{SEVERITY_LABEL.get(f.severity, f.severity.upper())}] "
              f"{('('+f.column+') ') if f.column else ''}{f.issue}")
            if f.details:
                p(f"    detalle: {f.details}")
            if f.examples:
                p(f"    ejemplos: {', '.join(f.examples)}")
            if f.count:
                p(f"    casos: {f.count}")
    p("")

    p("--- Detalles finos del texto (Detective fino) ---")
    if not text_quality.findings and not text_quality.typo_candidates:
        p("  Texto limpio según los chequeos automáticos.")
    else:
        for tf in text_quality.findings:
            p(f"  · {tf.column}: {tf.issue} (casos: {tf.count})")
            for ex in tf.examples:
                p(f"      ej → {ex}")
        if text_quality.typo_candidates:
            p("")
            p("  Posibles typos / parejas muy parecidas (validar a mano):")
            for col, pairs in text_quality.typo_candidates.items():
                p(f"    · {col}:")
                for a, b in pairs:
                    p(f"        '{a}'  ≈  '{b}'")
    p("")

    p("--- Estadísticas por columna ---")
    for c in analysis.columns:
        p(f"• {c.name}  [{c.dtype}]  no-nulos={c.non_null} nulos={c.nulls} "
          f"únicos={c.unique} (vacío {percentage(c.null_ratio, 1)}%)")
        if c.numeric_stats:
            ns = c.numeric_stats
            p(f"    min={ns['min']:.4g} max={ns['max']:.4g} mean={ns['mean']:.4g} "
              f"median={ns['median']:.4g} sum={ns['sum']:.4g} std={ns['std']:.4g}")
        if c.top_categories:
            tops = ", ".join(f"{t['value']}({t['count']})" for t in c.top_categories[:5])
            p(f"    top: {tops}")
        if c.email_domains:
            doms = ", ".join(f"{d['domain']}({d['count']})" for d in c.email_domains[:5])
            p(f"    dominios: {doms}")
        if c.sample_values:
            p(f"    muestra: {c.sample_values}")
    p("")

    p("--- Recomendaciones de la colmena ---")
    for r in _recommendations(analysis, text_quality, file):
        p(f"  {r}")
    p("")

    p("--- Veredicto del Jefe 🧠 ---")
    if analysis.health_score >= 75:
        p("  El archivo es razonablemente confiable, pero aplica las recomendaciones.")
    elif analysis.health_score >= 50:
        p("  El archivo tiene problemas claros. Limpia antes de usarlo en decisiones.")
    else:
        p("  El archivo NO es confiable tal cual. Limpia y vuelve a pasarlo por la colmena.")
    p("")
    p("=" * 70)
    p("Fin del reporte. 🐝")
    p("=" * 70)
    return "\n".join(out)


def build_report(file: LoadedFile, analysis: AnalysisReport,
                 text_quality: TextQualityReport, txt_output_path: str) -> ColmenaReport:
    debate = _debate(file, analysis, text_quality)
    summary = _summary(file, analysis, text_quality)

    txt = _build_txt(file, analysis, text_quality)
    with open(txt_output_path, "w", encoding="utf-8") as f:
        f.write(txt)

    return ColmenaReport(
        debate_lines=debate,
        summary_lines=summary,
        txt_path=txt_output_path,
        health_score=analysis.health_score,
        health_label=analysis.health_label,
    )
