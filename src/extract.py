"""Descarga los recursos de SEPA desde el portal CKAN.

Cómo publica SEPA (importante entenderlo antes de tocar el código):
el portal NO publica un recurso por fecha. Publica **7 recursos rotativos**
nombrados por día de la semana ("Lunes", "Martes", ...), que se sobrescriben
cada semana. O sea: solo hay una ventana móvil de los últimos 7 días.

Consecuencia práctica: si querés una serie larga, tenés que bajar todos los
días y guardarte los datos. No podés reconstruir el pasado. Por eso el
pipeline es idempotente y acumulativo — cada corrida suma días al histórico.

La fecha real de cada recurso se resuelve en tres pasos, de más a menos confiable:
  1. la fecha que viene adentro del ZIP (SEPA nombra las carpetas con ella)
  2. el timestamp `last_modified` que expone CKAN
  3. la última ocurrencia de ese día de la semana en el calendario

Uso:
    python -m src.extract --listar
    python -m src.extract --todos              # los 7 días disponibles
    python -m src.extract --dia viernes lunes  # días puntuales
    python -m src.extract --aux                # metadata PDF + traductor de provincias
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import time
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

from src import config as cfg
from src.utils import get_logger

log = get_logger("extract")

UA = "radar-precios-ar/1.0 (proyecto de portfolio)"
FECHA_RE = re.compile(r"(20\d{2})[-_/](\d{2})[-_/](\d{2})")

DIAS_SEMANA = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}


def _sin_acentos(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().strip().lower()


# --- HTTP ---------------------------------------------------------------------
def _http_get(url: str, timeout: int = 120, reintentos: int = 4) -> bytes:
    last = None
    for i in range(reintentos):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            espera = 2 ** i
            log.warning("Fallo (intento %d/%d): %s. Reintento en %ds", i + 1, reintentos, e, espera)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo descargar {url}: {last}")


# --- Resolución de fecha ------------------------------------------------------
def _fecha_de_timestamp(rec: dict) -> dt.date | None:
    """CKAN expone last_modified / created en ISO. Es la fuente más confiable
    antes de abrir el ZIP."""
    for campo in ("last_modified", "created", "metadata_modified", "cache_last_updated"):
        v = rec.get(campo)
        if not v:
            continue
        try:
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
        except ValueError:
            continue
    return None


def _fecha_de_dia_semana(nombre: str, hoy: dt.date | None = None) -> dt.date | None:
    """'Viernes' -> el viernes más reciente que ya pasó (o hoy)."""
    hoy = hoy or dt.date.today()
    idx = DIAS_SEMANA.get(_sin_acentos(nombre))
    if idx is None:
        return None
    delta = (hoy.weekday() - idx) % 7
    return hoy - dt.timedelta(days=delta)


def _fecha_de_contenido(carpeta: Path) -> dt.date | None:
    """La verdad está adentro: SEPA nombra las carpetas internas con la fecha.
    Tomo la fecha más frecuente para no dejarme engañar por un directorio suelto."""
    fechas: Counter = Counter()
    for p in carpeta.rglob("*"):
        m = FECHA_RE.search(p.name)
        if m:
            try:
                fechas[dt.date(*map(int, m.groups()))] += 1
            except ValueError:
                pass
    return fechas.most_common(1)[0][0] if fechas else None


# --- CKAN ---------------------------------------------------------------------
def listar_recursos() -> list[dict]:
    pkg = json.loads(_http_get(cfg.CKAN_API))["result"]
    out = []
    for r in pkg.get("resources", []):
        nombre = r.get("name", "")
        out.append({
            "nombre": nombre,
            "url": r.get("url", ""),
            "formato": (r.get("format") or "").lower(),
            "es_diario": _sin_acentos(nombre) in DIAS_SEMANA,
            "fecha_estimada": _fecha_de_timestamp(r) or _fecha_de_dia_semana(nombre),
            "tamano_mb": round((r.get("size") or 0) / 1e6, 1) or None,
        })
    return out


# --- Descarga -----------------------------------------------------------------
def descargar(rec: dict) -> Path | None:
    fecha = rec["fecha_estimada"]
    if fecha is None:
        log.warning("Sin fecha resoluble, salteo: %s", rec["nombre"])
        return None

    zip_path = cfg.RAW / f"sepa_{fecha:%Y-%m-%d}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        log.info("Ya existe %s (%.0f MB), salteo", zip_path.name, zip_path.stat().st_size / 1e6)
        return zip_path

    log.info("Descargando '%s' -> %s ...", rec["nombre"], zip_path.name)
    data = _http_get(rec["url"], timeout=900)
    zip_path.write_bytes(data)
    log.info("OK %s (%.0f MB)", zip_path.name, len(data) / 1e6)
    return zip_path


def descomprimir(zip_path: Path) -> Path | None:
    """Descomprime (SEPA anida un ZIP por comercio) y corrige la fecha de la
    carpeta con la que realmente venía adentro del archivo."""
    fecha_prov = zip_path.stem.replace("sepa_", "")
    out = cfg.RAW / fecha_prov

    if out.exists() and any(out.rglob("*.csv")):
        log.info("Ya descomprimido %s", out.name)
        return out
    out.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out)
    except zipfile.BadZipFile:
        log.error("ZIP corrupto: %s. Borralo y volvé a bajarlo.", zip_path.name)
        return None

    for inner in list(out.rglob("*.zip")):
        try:
            with zipfile.ZipFile(inner) as z:
                z.extractall(inner.parent / inner.stem)
            inner.unlink()
        except zipfile.BadZipFile:
            log.warning("ZIP interno corrupto, lo dejo: %s", inner.name)

    # Corregir la fecha con la que trae el propio archivo.
    real = _fecha_de_contenido(out)
    if real and f"{real:%Y-%m-%d}" != fecha_prov:
        destino = cfg.RAW / f"{real:%Y-%m-%d}"
        log.info("Fecha corregida: %s -> %s (la traía el ZIP adentro)", fecha_prov, destino.name)
        if destino.exists():
            shutil.rmtree(out)
            return destino
        out.rename(destino)
        zip_path.rename(cfg.RAW / f"sepa_{real:%Y-%m-%d}.zip")
        out = destino

    n = len(list(out.rglob("*.csv")))
    log.info("%s -> %d CSVs", out.name, n)
    return out if n else None


def descargar_auxiliares() -> None:
    """El PDF de metadata es la especificación oficial de los campos y el xlsx
    traduce los códigos de provincia. Valen más que cualquier suposición mía."""
    destino = cfg.RAW / "docs"
    destino.mkdir(parents=True, exist_ok=True)
    for r in listar_recursos():
        if r["es_diario"] or r["formato"] not in ("pdf", "xlsx", "xls", "csv"):
            continue
        nombre = re.sub(r"[^\w.-]+", "_", r["nombre"]).strip("_")
        p = destino / f"{nombre}.{r['formato']}"
        if p.exists():
            log.info("Ya existe %s", p.name)
            continue
        p.write_bytes(_http_get(r["url"]))
        log.info("OK %s", p.name)
    log.info("Auxiliares en %s", destino)


def run(dias: list[str] | None, todos: bool) -> list[Path]:
    recursos = [r for r in listar_recursos() if r["es_diario"]]
    if dias:
        pedidos = {_sin_acentos(d) for d in dias}
        recursos = [r for r in recursos if _sin_acentos(r["nombre"]) in pedidos]
    elif not todos:
        recursos = recursos[:1]

    log.info("Recursos a procesar: %d", len(recursos))
    carpetas = []
    for r in recursos:
        try:
            z = descargar(r)
            if z:
                c = descomprimir(z)
                if c:
                    carpetas.append(c)
        except Exception as e:  # noqa: BLE001
            log.error("Falla en '%s': %s", r["nombre"], e)
    return carpetas


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Descarga recursos SEPA")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--todos", action="store_true", help="los 7 días disponibles")
    ap.add_argument("--dia", nargs="+", help="ej: --dia viernes lunes")
    ap.add_argument("--aux", action="store_true", help="metadata PDF + traductor de provincias")
    a = ap.parse_args()

    if a.listar:
        print(f"{'FECHA EST.':<12} {'FMT':<6} {'MB':>7}  NOMBRE")
        for r in listar_recursos():
            f = f"{r['fecha_estimada']}" if r["fecha_estimada"] else "-"
            mb = f"{r['tamano_mb']}" if r["tamano_mb"] else "-"
            print(f"{f:<12} {r['formato']:<6} {mb:>7}  {r['nombre'][:60]}")
        print("\nSEPA publica 7 recursos rotativos (uno por día de semana) que se")
        print("sobrescriben cada semana. Solo existe la ventana de los últimos 7 días.")
    elif a.aux:
        descargar_auxiliares()
    else:
        run(a.dia, a.todos)