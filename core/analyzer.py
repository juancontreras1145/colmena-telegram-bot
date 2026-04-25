"""Analista + Detective: errores duros, métricas, duplicados, valores raros, etc."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .limits import HIGH_NULL_RATIO, OUTLIER_STD_FACTOR
from .utils import first_n, percentage, truncate


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_HINT_RE = re.compile(r"(fecha|date|fec_|dia|day|mes|month|year|anio|año|emit)", re.IGNORECASE)
EMAIL_HINT_RE = re.compile(r"(mail|correo|email)", re.IGNORECASE)
QTY_HINT_RE = re.compile(r"(cant|qty|cajas|unidad|stock|monto|total|precio|valor)", re.IGNORECASE)


@dataclass
class ColumnStat:
    name: str
    dtype: str
    non_null: int
    nulls: int
    unique: int
    null_ratio: float
    sample_values: List[str] = field(default_factory=list)
    numeric_stats: Optional[Dict[str, float]] = None
    top_categories: Optional[List[Dict[str, Any]]] = None
    email_domains: Optional[List[Dict[str, Any]]] = None


@dataclass
class Finding:
    severity: str  # "critico" | "alto" | "medio" | "bajo"
    column: Optional[str]
    issue: str
    details: str = ""
    examples: List[str] = field(default_factory=list)
    count: int = 0


@dataclass
class AnalysisReport:
    rows: int = 0
    cols: int = 0
    columns: List[ColumnStat] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    duplicates: int = 0
    duplicate_examples: List[Dict[str, Any]] = field(default_factory=list)
    fully_empty_columns: List[str] = field(default_factory=list)
    fully_empty_rows: int = 0
    high_null_columns: List[str] = field(default_factory=list)
    numeric_columns: List[str] = field(default_factory=list)
    health_score: int = 100  # 0..100
    health_label: str = ""

    def add(self, severity: str, column: Optional[str], issue: str, details: str = "",
            examples: Optional[List[str]] = None, count: int = 0) -> None:
        self.findings.append(Finding(
            severity=severity, column=column, issue=issue, details=details,
            examples=examples or [], count=count,
        ))


def _try_parse_date(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (datetime, pd.Timestamp)):
        return True
    s = str(value).strip()
    if not s:
        return False
    try:
        pd.to_datetime(s, errors="raise", dayfirst=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _coerce_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _column_stats(df: pd.DataFrame) -> List[ColumnStat]:
    stats: List[ColumnStat] = []
    total = len(df)
    for col in df.columns:
        s = df[col]
        non_null = int(s.notna().sum())
        nulls = int(s.isna().sum())
        unique = int(s.nunique(dropna=True))
        sample = [truncate(str(v), 40) for v in first_n(s.dropna().tolist(), 5)]
        col_stat = ColumnStat(
            name=str(col),
            dtype=str(s.dtype),
            non_null=non_null,
            nulls=nulls,
            unique=unique,
            null_ratio=round(nulls / total, 4) if total else 0.0,
            sample_values=sample,
        )

        numeric = _coerce_numeric(s.dropna())
        if not numeric.empty and numeric.notna().sum() >= max(3, len(s.dropna()) * 0.6):
            col_stat.numeric_stats = {
                "min": float(numeric.min()),
                "max": float(numeric.max()),
                "mean": float(numeric.mean()),
                "median": float(numeric.median()),
                "sum": float(numeric.sum()),
                "std": float(numeric.std()) if len(numeric) > 1 else 0.0,
                "count": int(numeric.count()),
            }

        if col_stat.numeric_stats is None and unique > 0 and unique <= max(20, total // 10):
            top = s.dropna().astype(str).value_counts().head(8)
            col_stat.top_categories = [
                {"value": truncate(idx, 40), "count": int(cnt)} for idx, cnt in top.items()
            ]

        if EMAIL_HINT_RE.search(str(col)):
            domains = []
            for v in s.dropna().astype(str):
                if "@" in v:
                    domains.append(v.split("@", 1)[1].lower().strip())
            if domains:
                top = Counter(domains).most_common(8)
                col_stat.email_domains = [{"domain": d, "count": c} for d, c in top]

        stats.append(col_stat)
    return stats


def _detect_duplicates(df: pd.DataFrame, report: AnalysisReport) -> None:
    if df.empty:
        return
    dup_mask = df.duplicated(keep=False)
    dup_count = int(dup_mask.sum())
    report.duplicates = dup_count
    if dup_count == 0:
        return
    examples = df[dup_mask].head(3).fillna("").astype(str).to_dict(orient="records")
    report.duplicate_examples = examples
    report.add(
        severity="alto",
        column=None,
        issue=f"Filas duplicadas: {dup_count}",
        details="Las filas exactamente repetidas distorsionan conteos, totales y promedios.",
        count=dup_count,
    )


def _detect_empty_structure(df: pd.DataFrame, report: AnalysisReport) -> None:
    total = len(df)
    if total == 0:
        report.add("critico", None, "Hoja sin filas con datos", "El archivo está vacío.")
        return

    fully_empty_cols = [str(c) for c in df.columns if df[c].isna().all()]
    if fully_empty_cols:
        report.fully_empty_columns = fully_empty_cols
        report.add(
            severity="medio",
            column=None,
            issue=f"Columnas completamente vacías: {len(fully_empty_cols)}",
            details=", ".join(truncate(c, 30) for c in fully_empty_cols[:8]),
            count=len(fully_empty_cols),
        )

    fully_empty_rows = int(df.isna().all(axis=1).sum())
    report.fully_empty_rows = fully_empty_rows
    if fully_empty_rows > 0:
        report.add(
            severity="medio",
            column=None,
            issue=f"Filas completamente vacías: {fully_empty_rows}",
            details="Inflan el archivo y rompen filtros y conteos.",
            count=fully_empty_rows,
        )

    high_null_cols: List[str] = []
    for col in df.columns:
        ratio = df[col].isna().mean() if total else 0
        if ratio >= HIGH_NULL_RATIO and ratio < 1.0:
            high_null_cols.append(f"{col} ({percentage(ratio, 1)}% vacío)")
    if high_null_cols:
        report.high_null_columns = high_null_cols
        report.add(
            severity="medio",
            column=None,
            issue=f"Columnas con muchos vacíos: {len(high_null_cols)}",
            details=", ".join(high_null_cols[:8]),
            count=len(high_null_cols),
        )


def _detect_dates(df: pd.DataFrame, report: AnalysisReport) -> None:
    for col in df.columns:
        if not DATE_HINT_RE.search(str(col)):
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        invalid = []
        for v in s:
            if not _try_parse_date(v):
                invalid.append(str(v))
        if invalid:
            report.add(
                severity="alto",
                column=str(col),
                issue=f"Fechas inválidas en '{col}'",
                details="Detectadas con nombre tipo fecha pero formato roto.",
                examples=[truncate(x, 40) for x in first_n(set(invalid), 5)],
                count=len(invalid),
            )


def _detect_emails(df: pd.DataFrame, report: AnalysisReport) -> None:
    for col in df.columns:
        if not EMAIL_HINT_RE.search(str(col)):
            continue
        s = df[col].dropna().astype(str)
        if s.empty:
            continue
        invalid = [v for v in s if not EMAIL_RE.match(v.strip())]
        if invalid:
            report.add(
                severity="alto",
                column=str(col),
                issue=f"Correos inválidos en '{col}'",
                details="No cumplen formato usuario@dominio.tld",
                examples=[truncate(x, 60) for x in first_n(set(invalid), 5)],
                count=len(invalid),
            )


def _detect_numeric_anomalies(df: pd.DataFrame, report: AnalysisReport) -> None:
    for col in df.columns:
        s = _coerce_numeric(df[col])
        valid = s.dropna()
        if valid.empty or len(valid) < 3:
            continue
        report.numeric_columns.append(str(col))

        negatives = valid[valid < 0]
        zeros = valid[valid == 0]
        is_qty_like = bool(QTY_HINT_RE.search(str(col)))

        if is_qty_like and len(negatives) > 0:
            report.add(
                severity="alto",
                column=str(col),
                issue=f"Valores negativos en columna tipo cantidad/monto: '{col}'",
                details=f"{len(negatives)} valores menores que cero.",
                examples=[str(round(v, 2)) for v in first_n(negatives.tolist(), 5)],
                count=int(len(negatives)),
            )
        if is_qty_like and len(zeros) > 0:
            report.add(
                severity="medio",
                column=str(col),
                issue=f"Cajas/cantidades en cero en '{col}'",
                details=f"{len(zeros)} registros con valor 0.",
                count=int(len(zeros)),
            )

        if len(valid) >= 10 and valid.std() > 0:
            mean, std = valid.mean(), valid.std()
            high_threshold = mean + OUTLIER_STD_FACTOR * std
            extremes = valid[valid > high_threshold]
            if len(extremes) > 0:
                report.add(
                    severity="medio",
                    column=str(col),
                    issue=f"Valores extremadamente altos en '{col}'",
                    details=(
                        f"{len(extremes)} valores por encima de "
                        f"{OUTLIER_STD_FACTOR}σ ({round(high_threshold, 2)})."
                    ),
                    examples=[str(round(v, 2)) for v in first_n(extremes.tolist(), 5)],
                    count=int(len(extremes)),
                )


def _detect_repeated_categories(df: pd.DataFrame, report: AnalysisReport,
                                 column_stats: List[ColumnStat]) -> None:
    for cs in column_stats:
        if not cs.top_categories:
            continue
        top = cs.top_categories[0]
        if top["count"] >= 3 and top["count"] / max(cs.non_null, 1) >= 0.5:
            report.add(
                severity="bajo",
                column=cs.name,
                issue=f"Categoría dominante en '{cs.name}'",
                details=(
                    f"'{top['value']}' aparece {top['count']} veces "
                    f"({percentage(top['count'], cs.non_null)}% de la columna)."
                ),
                count=top["count"],
            )


def _compute_health(report: AnalysisReport) -> None:
    score = 100
    severity_weight = {"critico": 30, "alto": 12, "medio": 6, "bajo": 2}
    for f in report.findings:
        score -= severity_weight.get(f.severity, 1)
    if report.duplicates:
        score -= min(15, report.duplicates // 5)
    score = max(0, min(100, score))
    report.health_score = score
    if score >= 90:
        label = "Excelente"
    elif score >= 75:
        label = "Buena"
    elif score >= 55:
        label = "Aceptable, con mejoras"
    elif score >= 35:
        label = "Frágil, requiere limpieza"
    else:
        label = "Crítica, no usar tal cual"
    report.health_label = label


def analyze_dataframe(df: pd.DataFrame) -> AnalysisReport:
    report = AnalysisReport()
    if df is None:
        report.add("critico", None, "Sin datos", "No se pudo cargar la hoja.")
        _compute_health(report)
        return report

    report.rows = int(len(df))
    report.cols = int(df.shape[1])
    report.columns = _column_stats(df)

    _detect_empty_structure(df, report)
    _detect_duplicates(df, report)
    _detect_dates(df, report)
    _detect_emails(df, report)
    _detect_numeric_anomalies(df, report)
    _detect_repeated_categories(df, report, report.columns)

    _compute_health(report)
    return report
