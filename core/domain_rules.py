"""Reglas inteligentes por tipo de archivo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class DomainFinding:
    priority: str
    title: str
    detail: str
    action: str


def norm(text: object) -> str:
    return str(text or "").strip().lower()


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)

    for c in cols:
        name = norm(c)
        for cand in candidates:
            if cand in name:
                return c

    return None


def apply_domain_rules(df: pd.DataFrame, domain: str) -> list[DomainFinding]:
    if domain == "correos":
        return rules_correos(df)

    if domain == "despacho":
        return rules_despacho(df)

    if domain == "inventario":
        return rules_inventario(df)

    if domain == "productividad":
        return rules_productividad(df)

    if domain == "ventas":
        return rules_ventas(df)

    return rules_generico(df)


def rules_correos(df: pd.DataFrame) -> list[DomainFinding]:
    findings: list[DomainFinding] = []

    correo_col = find_col(df, ["correo", "email", "mail"])
    tienda_col = find_col(df, ["tienda", "sucursal", "local"])
    cco_col = find_col(df, ["cco", "bcc"])

    if cco_col:
        empty_ratio = df[cco_col].isna().mean()
        if empty_ratio >= 0.95:
            findings.append(DomainFinding(
                "media",
                "CCO casi o totalmente vacío",
                f"La columna '{cco_col}' está vacía en {round(empty_ratio * 100, 1)}% de las filas.",
                "Eliminar CCO si no se usa, o documentar para qué existe.",
            ))

    if correo_col:
        duplicated = df[correo_col].dropna().astype(str).str.strip().duplicated().sum()
        if duplicated > 0:
            findings.append(DomainFinding(
                "media",
                "Correos repetidos",
                f"Hay {duplicated} correo(s) repetido(s).",
                "Revisar si un mismo correo corresponde realmente a varias tiendas/personas.",
            ))

        domains = (
            df[correo_col]
            .dropna()
            .astype(str)
            .str.extract(r"@(.+)$")[0]
            .dropna()
            .str.lower()
            .value_counts()
        )

        if len(domains) > 1:
            findings.append(DomainFinding(
                "media",
                "Dominios mezclados",
                f"Se detectaron varios dominios de correo: {dict(domains.head(5))}",
                "Validar si todos los dominios son esperados antes de automatizar envíos.",
            ))

    if tienda_col and correo_col:
        tmp = df[[tienda_col, correo_col]].dropna().astype(str)
        grouped = tmp.groupby(tienda_col)[correo_col].nunique()
        conflicts = grouped[grouped > 1]

        if len(conflicts) > 0:
            findings.append(DomainFinding(
                "alta",
                "Tiendas con más de un correo",
                f"{len(conflicts)} tienda(s) tienen más de un correo asociado.",
                "Validar si son cambios legítimos o errores antes de usar la base.",
            ))

    return findings


def rules_despacho(df: pd.DataFrame) -> list[DomainFinding]:
    findings: list[DomainFinding] = []

    tda_col = find_col(df, ["tda", "tienda", "sucursal"])
    cajas_col = find_col(df, ["caja", "cajas"])
    bultos_col = find_col(df, ["bulto", "bultos"])
    pedido_col = find_col(df, ["pedido", "orden", "documento"])
    estado_col = find_col(df, ["estado", "status"])

    duplicated_rows = df.duplicated().sum()
    if duplicated_rows > 0:
        findings.append(DomainFinding(
            "alta",
            "Filas duplicadas en despacho",
            f"Hay {duplicated_rows} fila(s) duplicada(s). En despacho esto puede inflar cajas, bultos o totales.",
            "Validar si son filas de detalle legítimas o duplicados reales antes de reportar.",
        ))

    if tda_col:
        missing = df[tda_col].isna().sum()
        if missing > 0:
            findings.append(DomainFinding(
                "alta",
                "TDA / tienda vacía",
                f"La columna '{tda_col}' tiene {missing} valor(es) vacío(s).",
                "No reportar despacho sin identificar tienda/TDA.",
            ))

    for col in [cajas_col, bultos_col]:
        if not col:
            continue

        nums = pd.to_numeric(df[col], errors="coerce")
        zeros = (nums == 0).sum()
        negatives = (nums < 0).sum()

        if zeros > 0:
            findings.append(DomainFinding(
                "media",
                f"{col} en cero",
                f"La columna '{col}' tiene {zeros} valor(es) en cero.",
                "Revisar si corresponde a despacho sin cajas/bultos o error de captura.",
            ))

        if negatives > 0:
            findings.append(DomainFinding(
                "alta",
                f"{col} negativo",
                f"La columna '{col}' tiene {negatives} valor(es) negativos.",
                "Corregir antes de usar en totales operativos.",
            ))

    if pedido_col:
        duplicated_orders = df[pedido_col].dropna().astype(str).duplicated().sum()
        if duplicated_orders > 0:
            findings.append(DomainFinding(
                "media",
                "Pedidos repetidos",
                f"La columna '{pedido_col}' tiene {duplicated_orders} pedido(s) repetido(s).",
                "Validar si cada pedido puede tener varias líneas o si hay duplicación real.",
            ))

    if estado_col and cajas_col:
        nums = pd.to_numeric(df[cajas_col], errors="coerce")
        estados = df[estado_col].astype(str).str.lower()
        suspicious = ((nums == 0) & estados.str.contains("complet|cerrad|ok", na=False)).sum()

        if suspicious > 0:
            findings.append(DomainFinding(
                "alta",
                "Despachos completados con cajas en cero",
                f"Hay {suspicious} fila(s) con estado completado/ok y cajas en cero.",
                "Revisar estas filas antes de considerarlas cerradas.",
            ))

    return findings


def rules_inventario(df: pd.DataFrame) -> list[DomainFinding]:
    findings: list[DomainFinding] = []

    sku_col = find_col(df, ["sku", "codigo", "código"])
    stock_col = find_col(df, ["stock", "cantidad", "existencia"])

    if sku_col:
        duplicated = df[sku_col].dropna().astype(str).duplicated().sum()
        if duplicated > 0:
            findings.append(DomainFinding(
                "media",
                "SKU repetidos",
                f"Hay {duplicated} SKU repetido(s).",
                "Validar si son ubicaciones distintas o duplicados reales.",
            ))

    if stock_col:
        nums = pd.to_numeric(df[stock_col], errors="coerce")
        negatives = (nums < 0).sum()
        if negatives > 0:
            findings.append(DomainFinding(
                "alta",
                "Stock negativo",
                f"La columna '{stock_col}' tiene {negatives} valor(es) negativos.",
                "Revisar antes de usar inventario como fuente confiable.",
            ))

    return findings


def rules_productividad(df: pd.DataFrame) -> list[DomainFinding]:
    findings: list[DomainFinding] = []

    operador_col = find_col(df, ["operador", "usuario", "user"])
    unidades_col = find_col(df, ["unidad", "unidades", "cantidad"])

    if operador_col:
        missing = df[operador_col].isna().sum()
        if missing > 0:
            findings.append(DomainFinding(
                "media",
                "Operadores vacíos",
                f"La columna '{operador_col}' tiene {missing} valor(es) vacío(s).",
                "No calcular productividad sin operador asociado.",
            ))

    if unidades_col:
        nums = pd.to_numeric(df[unidades_col], errors="coerce")
        negatives = (nums < 0).sum()
        if negatives > 0:
            findings.append(DomainFinding(
                "alta",
                "Unidades negativas",
                f"La columna '{unidades_col}' tiene {negatives} valor(es) negativos.",
                "Revisar captura antes de calcular productividad.",
            ))

    return findings


def rules_ventas(df: pd.DataFrame) -> list[DomainFinding]:
    findings: list[DomainFinding] = []

    total_col = find_col(df, ["total", "monto", "venta", "precio"])

    if total_col:
        nums = pd.to_numeric(df[total_col], errors="coerce")
        negatives = (nums < 0).sum()
        zeros = (nums == 0).sum()

        if negatives > 0:
            findings.append(DomainFinding(
                "alta",
                "Ventas/montos negativos",
                f"La columna '{total_col}' tiene {negatives} valor(es) negativos.",
                "Validar si son notas de crédito o errores.",
            ))

        if zeros > 0:
            findings.append(DomainFinding(
                "media",
                "Ventas/montos en cero",
                f"La columna '{total_col}' tiene {zeros} valor(es) en cero.",
                "Revisar si son registros válidos o incompletos.",
            ))

    return findings


def rules_generico(df: pd.DataFrame) -> list[DomainFinding]:
    findings: list[DomainFinding] = []

    empty_cols = [c for c in df.columns if df[c].isna().mean() >= 0.95]
    if empty_cols:
        findings.append(DomainFinding(
            "media",
            "Columnas casi vacías",
            f"Hay {len(empty_cols)} columna(s) con 95% o más de vacíos.",
            "Eliminar columnas sin uso o confirmar por qué existen.",
        ))

    return findings
