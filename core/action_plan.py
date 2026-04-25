"""Genera plan de acción priorizado."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class ActionPlan:
    high: list[str]
    medium: list[str]
    low: list[str]


def build_action_plan(domain_label: str, findings: Iterable[object]) -> ActionPlan:
    high: list[str] = []
    medium: list[str] = []
    low: list[str] = []

    for f in findings:
        priority = getattr(f, "priority", "media")
        title = getattr(f, "title", "Hallazgo")
        action = getattr(f, "action", "Revisar manualmente.")

        item = f"{title}: {action}"

        if priority == "alta":
            high.append(item)
        elif priority == "baja":
            low.append(item)
        else:
            medium.append(item)

    if not high and not medium:
        low.append("Crear copia limpia del archivo antes de editar.")
        low.append("Guardar una versión liviana para trabajo real.")

    if domain_label:
        low.append(f"Documentar que este archivo fue clasificado como: {domain_label}.")

    return ActionPlan(
        high=dedupe(high),
        medium=dedupe(medium),
        low=dedupe(low),
    )


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []

    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)

    return out


def format_action_plan(plan: ActionPlan) -> list[str]:
    lines: list[str] = []

    lines.append("🧭 PLAN DE ACCIÓN")
    lines.append("-" * 60)

    if plan.high:
        lines.append("🚨 Alta prioridad:")
        for i, item in enumerate(plan.high, start=1):
            lines.append(f"{i}. {item}")

    if plan.medium:
        lines.append("")
        lines.append("⚠️ Media prioridad:")
        for i, item in enumerate(plan.medium, start=1):
            lines.append(f"{i}. {item}")

    if plan.low:
        lines.append("")
        lines.append("✅ Baja prioridad:")
        for i, item in enumerate(plan.low, start=1):
            lines.append(f"{i}. {item}")

    return lines
