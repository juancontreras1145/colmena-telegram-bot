"""Detective fino del texto: dobles espacios, typos, letras repetidas, correos raros."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

import pandas as pd

from .limits import MIN_TEXT_LEN_FOR_REPEAT, REPEAT_LETTERS_THRESHOLD
from .utils import first_n, truncate


DOUBLE_SPACE_RE = re.compile(r"\s{2,}")
LEADING_TRAILING_SPACE_RE = re.compile(r"^\s+|\s+$")
REPEATED_LETTERS_RE = re.compile(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ])\1{" + str(REPEAT_LETTERS_THRESHOLD - 1) + r",}")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WEIRD_EMAIL_LOCAL_RE = re.compile(r"([A-Za-z])\1{2,}|\.{2,}|--")


@dataclass
class TextFinding:
    column: str
    issue: str
    examples: List[str] = field(default_factory=list)
    count: int = 0


@dataclass
class TextQualityReport:
    findings: List[TextFinding] = field(default_factory=list)
    typo_candidates: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)


def _is_text_series(s: pd.Series) -> bool:
    sample = s.dropna().astype(str).head(50)
    if sample.empty:
        return False
    text_like = sum(1 for v in sample if any(c.isalpha() for c in v))
    return text_like >= max(3, len(sample) // 2)


def _find_double_spaces(col: str, values: List[str]) -> TextFinding | None:
    hits = [v for v in values if DOUBLE_SPACE_RE.search(v)]
    if not hits:
        return None
    return TextFinding(
        column=col,
        issue="Dobles espacios dentro del texto",
        examples=[truncate(h, 60) for h in first_n(set(hits), 5)],
        count=len(hits),
    )


def _find_padding(col: str, values: List[str]) -> TextFinding | None:
    hits = [v for v in values if LEADING_TRAILING_SPACE_RE.search(v)]
    if not hits:
        return None
    return TextFinding(
        column=col,
        issue="Espacios al inicio o al final",
        examples=[truncate(repr(h), 60) for h in first_n(set(hits), 5)],
        count=len(hits),
    )


def _find_repeated_letters(col: str, values: List[str]) -> TextFinding | None:
    hits = []
    for v in values:
        if len(v) < MIN_TEXT_LEN_FOR_REPEAT:
            continue
        if REPEATED_LETTERS_RE.search(v):
            hits.append(v)
    if not hits:
        return None
    return TextFinding(
        column=col,
        issue=f"Letras repetidas sospechosas ({REPEAT_LETTERS_THRESHOLD}+ iguales seguidas)",
        examples=[truncate(h, 60) for h in first_n(set(hits), 5)],
        count=len(hits),
    )


def _find_weird_emails(col: str, values: List[str]) -> List[TextFinding]:
    out: List[TextFinding] = []
    invalid = []
    suspicious = []
    repeated = []
    for v in values:
        v_str = v.strip()
        if "@" not in v_str:
            continue
        if not EMAIL_RE.match(v_str):
            invalid.append(v_str)
            continue
        local = v_str.split("@", 1)[0]
        if WEIRD_EMAIL_LOCAL_RE.search(local) or REPEATED_LETTERS_RE.search(local):
            repeated.append(v_str)
        if local.endswith(".") or local.startswith(".") or ".." in v_str:
            suspicious.append(v_str)
    if invalid:
        out.append(TextFinding(
            column=col, issue="Correos con formato inválido",
            examples=[truncate(x, 60) for x in first_n(set(invalid), 5)],
            count=len(invalid),
        ))
    if repeated:
        out.append(TextFinding(
            column=col, issue="Correos con letras repetidas o patrones raros",
            examples=[truncate(x, 60) for x in first_n(set(repeated), 5)],
            count=len(repeated),
        ))
    if suspicious:
        out.append(TextFinding(
            column=col, issue="Correos con puntos sospechosos",
            examples=[truncate(x, 60) for x in first_n(set(suspicious), 5)],
            count=len(suspicious),
        ))
    return out


def _find_typo_candidates(col: str, values: List[str], threshold: float = 0.86) -> List[Tuple[str, str]]:
    """Encuentra pares de strings muy parecidos pero distintos (posibles typos).

    Lo limitamos a los 60 valores más frecuentes para no explotar.
    """
    from collections import Counter

    counter = Counter(v.strip() for v in values if v and v.strip())
    top = [v for v, _ in counter.most_common(60)]
    pairs: List[Tuple[str, str]] = []
    seen = set()
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            if a.lower() == b.lower():
                continue
            if abs(len(a) - len(b)) > 3:
                continue
            ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if threshold <= ratio < 1.0:
                key = tuple(sorted((a, b)))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((a, b))
                if len(pairs) >= 10:
                    return pairs
    return pairs


def analyze_text_quality(df: pd.DataFrame) -> TextQualityReport:
    report = TextQualityReport()
    if df is None or df.empty:
        return report

    for col in df.columns:
        s = df[col]
        if not _is_text_series(s):
            continue
        values = [str(v) for v in s.dropna().tolist()]
        if not values:
            continue

        for fn in (_find_double_spaces, _find_padding, _find_repeated_letters):
            f = fn(str(col), values)
            if f:
                report.findings.append(f)

        report.findings.extend(_find_weird_emails(str(col), values))

        typos = _find_typo_candidates(str(col), values)
        if typos:
            report.typo_candidates[str(col)] = typos

    return report
