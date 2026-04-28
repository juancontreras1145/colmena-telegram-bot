"""Lee CSV/XLSX/XLSM en modo seguro y devuelve DataFrames listos para analizar."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .limits import (
    HEAVY_FILE_BYTES,
    MAX_COLS,
    MAX_ROWS,
    SAFE_MAX_COLS,
    SAFE_MAX_ROWS,
)
from .workbook_profiler import WorkbookProfile, profile_workbook


SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xlsm", ".apk")


@dataclass
class LoadedFile:
    path: str
    file_name: str
    file_size: int
    extension: str
    safe_mode: bool
    sheets: Dict[str, pd.DataFrame] = field(default_factory=dict)
    primary_sheet: Optional[str] = None
    workbook_profile: Optional[WorkbookProfile] = None
    notes: List[str] = field(default_factory=list)
    truncated: bool = False
    error: Optional[str] = None

    @property
    def primary_df(self) -> Optional[pd.DataFrame]:
        if self.primary_sheet and self.primary_sheet in self.sheets:
            return self.sheets[self.primary_sheet]
        if self.sheets:
            return next(iter(self.sheets.values()))
        return None


def _detect_csv_separator(path: str) -> str:
    """Adivina el separador CSV mirando la primera línea no vacía."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    candidates = [",", ";", "\t", "|"]
                    counts = {c: line.count(c) for c in candidates}
                    best = max(counts, key=counts.get)
                    return best if counts[best] > 0 else ","
                    break
    except Exception:  # noqa: BLE001
        pass
    return ","


def _read_csv(path: str, safe_mode: bool, file: LoadedFile) -> None:
    sep = _detect_csv_separator(path)
    max_rows = SAFE_MAX_ROWS if safe_mode else MAX_ROWS
    max_cols = SAFE_MAX_COLS if safe_mode else MAX_COLS

    try:
        df = pd.read_csv(
            path,
            sep=sep,
            engine="python",
            on_bad_lines="skip",
            dtype=str,
            keep_default_na=True,
            nrows=max_rows + 1,
            encoding="utf-8",
            encoding_errors="replace",
        )
    except UnicodeDecodeError:
        df = pd.read_csv(
            path,
            sep=sep,
            engine="python",
            on_bad_lines="skip",
            dtype=str,
            keep_default_na=True,
            nrows=max_rows + 1,
            encoding="latin-1",
        )

    if len(df) > max_rows:
        df = df.head(max_rows)
        file.truncated = True
        file.notes.append(f"CSV recortado a las primeras {max_rows:,} filas por modo seguro.")

    if df.shape[1] > max_cols:
        df = df.iloc[:, :max_cols]
        file.truncated = True
        file.notes.append(f"CSV recortado a las primeras {max_cols} columnas por modo seguro.")

    file.sheets["datos"] = df
    file.primary_sheet = "datos"


def _read_excel(path: str, safe_mode: bool, file: LoadedFile) -> None:
    profile = profile_workbook(path)
    file.workbook_profile = profile

    if profile.has_macros:
        file.notes.append(
            "El archivo es .xlsm con macros. La colmena las detectó pero NUNCA las ejecuta."
        )
    if profile.inflated_workbook:
        file.notes.append("El libro parece inflado: pesa mucho para los datos reales.")

    max_rows = SAFE_MAX_ROWS if safe_mode else MAX_ROWS
    max_cols = SAFE_MAX_COLS if safe_mode else MAX_COLS

    sheets_to_load: List[str] = []
    if profile.best_sheet:
        sheets_to_load.append(profile.best_sheet)
    # En modo seguro nos quedamos sólo con la mejor hoja.
    if not safe_mode:
        for s in profile.sheets:
            if s.name not in sheets_to_load and s.non_empty_cells > 0:
                sheets_to_load.append(s.name)
                if len(sheets_to_load) >= 5:
                    break

    if not sheets_to_load:
        file.notes.append("No encontré hojas con datos reales.")
        return

    for sheet_name in sheets_to_load:
        try:
            df = pd.read_excel(
                path,
                sheet_name=sheet_name,
                engine="openpyxl",
                dtype=object,
                nrows=max_rows + 1,
            )
        except Exception as exc:  # noqa: BLE001
            file.notes.append(f"No pude leer la hoja '{sheet_name}': {exc}")
            continue

        if len(df) > max_rows:
            df = df.head(max_rows)
            file.truncated = True
            file.notes.append(
                f"Hoja '{sheet_name}' recortada a {max_rows:,} filas por modo seguro."
            )
        if df.shape[1] > max_cols:
            df = df.iloc[:, :max_cols]
            file.truncated = True
            file.notes.append(
                f"Hoja '{sheet_name}' recortada a {max_cols} columnas por modo seguro."
            )

        file.sheets[sheet_name] = df

    file.primary_sheet = profile.best_sheet or (sheets_to_load[0] if sheets_to_load else None)


def load_file(path: str, original_name: str) -> LoadedFile:
    """Carga el archivo y devuelve un LoadedFile con DataFrames y metadatos."""
    file_size = os.path.getsize(path)
    extension = os.path.splitext(original_name)[1].lower()
    safe_mode = file_size >= HEAVY_FILE_BYTES or extension == ".xlsm"

    file = LoadedFile(
        path=path,
        file_name=original_name,
        file_size=file_size,
        extension=extension,
        safe_mode=safe_mode,
    )

    if extension not in SUPPORTED_EXTENSIONS:
        file.error = f"Formato no soportado: {extension}. Usa CSV, XLSX, XLSM o APK."
        return file

    try:
        if extension == ".csv":
            _read_csv(path, safe_mode, file)
        else:
            _read_excel(path, safe_mode, file)
    except Exception as exc:  # noqa: BLE001
        file.error = f"No pude leer el archivo: {exc}"

    return file