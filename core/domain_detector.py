"""Detecta el tipo de archivo según sus columnas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class DomainResult:
    domain: str
    label: str
    confidence: int
    reasons: list[str]
    priority_columns: list[str]


DOMAIN_PROFILES = {
    "correos": {
        "label": "Lista de correos / contactos",
        "keywords": ["correo", "email", "mail", "tienda", "cc", "cco"],
        "priority": ["tienda", "correo", "email", "cc1", "cc2", "cco"],
    },
    "despacho": {
        "label": "Despacho / logística",
        "keywords": ["tda", "suc", "sucursal", "tienda", "caja", "cajas", "bulto", "bultos", "pedido", "despacho"],
        "priority": ["tda", "suc desc", "tienda", "pedido", "cajas", "bultos", "fecha"],
    },
    "inventario": {
        "label": "Inventario / stock",
        "keywords": ["sku", "producto", "stock", "inventario", "cantidad", "ubicacion", "bodega"],
        "priority": ["sku", "producto", "stock", "cantidad", "bodega"],
    },
    "productividad": {
        "label": "Productividad / operadores",
        "keywords": ["operador", "usuario", "unidades", "productividad", "proceso", "fecha", "mueble"],
        "priority": ["operador", "usuario", "unidades", "proceso", "fecha"],
    },
    "ventas": {
        "label": "Ventas / comercial",
        "keywords": ["venta", "ventas", "monto", "precio", "total", "cliente", "boleta", "factura"],
        "priority": ["venta", "monto", "precio", "total", "cliente"],
    },
}


def normalize(text: object) -> str:
    return str(text or "").strip().lower()


def detect_domain(columns: Iterable[object]) -> DomainResult:
    cols = [normalize(c) for c in columns]
    joined = " ".join(cols)

    scores: dict[str, int] = {}
    reasons_by_domain: dict[str, list[str]] = {}

    for domain, profile in DOMAIN_PROFILES.items():
        score = 0
        reasons = []

        for kw in profile["keywords"]:
            if any(kw in col for col in cols):
                score += 12
                reasons.append(f"columna relacionada con '{kw}'")

        for kw in profile["keywords"]:
            if kw in joined:
                score += 3

        scores[domain] = score
        reasons_by_domain[domain] = reasons[:6]

    best_domain = max(scores, key=scores.get)
    best_score = scores[best_domain]

    if best_score <= 0:
        return DomainResult(
            domain="generico",
            label="Archivo genérico",
            confidence=20,
            reasons=["No se detectó un patrón fuerte por columnas."],
            priority_columns=[],
        )

    confidence = min(95, max(35, best_score))
    profile = DOMAIN_PROFILES[best_domain]

    return DomainResult(
        domain=best_domain,
        label=profile["label"],
        confidence=confidence,
        reasons=reasons_by_domain[best_domain] or ["Coincidencia parcial por nombres de columnas."],
        priority_columns=profile["priority"],
    )
