"""Funciones comunes a toda la colmena."""
from __future__ import annotations

import os
import tempfile
import unicodedata
from datetime import datetime
from typing import Iterable


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = "".join(c if c.isalnum() or c in "-_" else "_" for c in value).strip("_")
    return value or "archivo"


def temp_path(suffix: str = "") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


def safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def truncate(text: str, limit: int = 80) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def first_n(items: Iterable, n: int = 5) -> list:
    out = []
    for i, item in enumerate(items):
        if i >= n:
            break
        out.append(item)
    return out


def percentage(part: float, total: float) -> float:
    if not total:
        return 0.0
    return round(part * 100 / total, 2)
