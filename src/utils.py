"""Utilidades compartidas: logging, normalización de nombres, lectura tolerante."""
from __future__ import annotations

import csv
import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger


log = get_logger(__name__)


def slugify_col(col: str) -> str:
    """'Productos Precio Lista ' -> 'productos_precio_lista'."""
    s = unicodedata.normalize("NFKD", str(col)).encode("ascii", "ignore").decode()
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def sniff_delimiter(path: Path, n_bytes: int = 8192) -> str:
    """SEPA publicó archivos con ',', ';' y '|' según la época. No adivines."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(n_bytes)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;|\t").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        counts = {d: first.count(d) for d in ",;|\t"}
        return max(counts, key=counts.get) if max(counts.values()) else ","


def read_sepa_csv(path: Path, required: list[str], optional: list[str] | None = None) -> pd.DataFrame:
    """Lee un CSV de SEPA normalizando nombres y quedándose con las columnas útiles.

    Falla ruidosamente si falta una columna núcleo: preferimos romper el pipeline
    antes que publicar un número mal calculado.
    """
    optional = optional or []
    sep = sniff_delimiter(path)
    df = pd.read_csv(
        path,
        sep=sep,
        dtype=str,
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="skip",
        low_memory=False,
    )
    df.columns = [slugify_col(c) for c in df.columns]

    faltan = [c for c in required if c not in df.columns]
    if faltan:
        raise ValueError(
            f"{path.name}: faltan columnas núcleo {faltan}. "
            f"Columnas encontradas: {list(df.columns)[:25]}"
        )

    cols = required + [c for c in optional if c in df.columns]
    return df[cols].copy()


def to_number(s: pd.Series) -> pd.Series:
    """Convierte texto a float tolerando '1.234,56', '1,234.56', '$ 1234' y ''."""
    x = (
        s.astype(str)
        .str.replace(r"[^\d,.\-]", "", regex=True)
        .str.strip()
    )
    # Si tiene ambos separadores, el ÚLTIMO es el decimal.
    tiene_ambos = x.str.contains(r"\.") & x.str.contains(",")
    coma_ultima = x.str.rfind(",") > x.str.rfind(".")

    fmt_es = (tiene_ambos & coma_ultima) | (~tiene_ambos & x.str.contains(","))
    x = x.where(~fmt_es, x.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    x = x.where(fmt_es, x.str.replace(",", "", regex=False))
    return pd.to_numeric(x, errors="coerce")


def fmt_pesos(v: float) -> str:
    return f"${v:,.0f}".replace(",", ".")
