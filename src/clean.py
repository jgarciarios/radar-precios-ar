"""Limpia los CSV crudos de SEPA y los deja en Parquet particionado por fecha.

Uso:
    python -m src.clean                      # procesa todo lo que haya en data/raw/
    python -m src.clean --fecha 2026-07-14
    python -m src.clean --forzar             # reprocesa aunque ya exista el parquet

Cada decisión de limpieza queda registrada en data/interim/_calidad.csv,
que después se muestra en el notebook 02 y en el README. Eso es lo que
diferencia una limpieza defendible de un dropna() a ciegas.
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from src import config as cfg
from src.tamano import parsear_series
from src.unidades import normalizar, unidades_no_reconocidas
from src.utils import get_logger, read_sepa_csv, to_number

log = get_logger("clean")

CALIDAD_PATH = cfg.INTERIM / "_calidad.csv"


class DescarteExcesivo(RuntimeError):
    """Una regla de limpieza descartó más filas de las razonables."""


def _aplicar_regla(df, conservar, nombre: str, metricas: dict,
                   cols_ejemplo=("id_producto", "productos_descripcion",
                                 "productos_precio_lista"),
                   ignorar_guardrail: bool = False):
    """Aplica una regla, registra cuánto descartó y CORTA si se pasa del umbral.

    El punto no es la métrica: es que cuando una regla se come el 90% de los
    datos, veas EJEMPLOS de lo que estaba tirando en vez de un parquet vacío.
    """
    antes = len(df)
    descartadas = df[~conservar]
    n = len(descartadas)
    metricas[f"desc_{nombre}"] = n

    if antes and n / antes > cfg.MAX_DESCARTE_POR_REGLA:
        cols = [c for c in cols_ejemplo if c in descartadas.columns]
        muestra = descartadas[cols].head(5).to_string(index=False) if cols else "(sin columnas)"
        msg = (f"La regla '{nombre}' descartó {n:,}/{antes:,} filas "
               f"({100*n/antes:.1f}%), por encima del umbral de "
               f"{100*cfg.MAX_DESCARTE_POR_REGLA:.0f}%.")
        log.error("%s\nEjemplos de lo que estaba descartando:\n%s", msg, muestra)
        if not ignorar_guardrail:
            raise DescarteExcesivo(
                msg + " Revisá la regla en clean.py o el esquema en config.py. "
                "Si estás seguro de que está bien, corré con --ignorar-guardrail."
            )
        log.warning("Guardrail ignorado por pedido explícito, sigo.")

    return df[conservar]


def _buscar(carpeta: Path, patron: str) -> list[Path]:
    """SEPA nombra los archivos de formas distintas según el comercio."""
    return sorted(p for p in carpeta.rglob("*.csv") if patron in p.name.lower())


def _leer_muchos(paths: list[Path], required, optional) -> pd.DataFrame:
    frames = []
    for p in paths:
        try:
            frames.append(read_sepa_csv(p, required, optional))
        except Exception as e:  # noqa: BLE001
            log.warning("Salteo %s: %s", p.relative_to(cfg.RAW), e)
    if not frames:
        return pd.DataFrame(columns=required)
    return pd.concat(frames, ignore_index=True)


def limpiar_dia(carpeta: Path, forzar: bool = False,
                ignorar_guardrail: bool = False) -> Path | None:
    fecha_str = carpeta.name
    try:
        fecha = dt.datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        log.warning("Carpeta con nombre no-fecha, salteo: %s", carpeta)
        return None

    out = cfg.INTERIM / f"fecha={fecha:%Y-%m-%d}" / "precios.parquet"
    if out.exists() and not forzar:
        log.info("Ya procesado %s", fecha)
        return out

    log.info("--- Limpiando %s ---", fecha)
    metricas: dict[str, int | float] = {"fecha": fecha_str}

    productos = _leer_muchos(_buscar(carpeta, "producto"), cfg.PRODUCTOS_CORE, cfg.PRODUCTOS_OPCIONALES)
    sucursales = _leer_muchos(_buscar(carpeta, "sucursal"), cfg.SUCURSALES_CORE, cfg.SUCURSALES_OPCIONALES)
    comercios = _leer_muchos(_buscar(carpeta, "comercio"), cfg.COMERCIO_CORE, cfg.COMERCIO_OPCIONALES)

    if productos.empty:
        log.error("Sin productos para %s", fecha)
        return None

    metricas["filas_crudas"] = len(productos)

    # 1) Tipos ---------------------------------------------------------------
    productos["precio"] = to_number(productos["productos_precio_lista"])
    # OJO: el código de barras está en `id_producto`, NO en `productos_ean`
    # (ver el comentario en config.py). Saco los ceros a izquierda porque cada
    # cadena rellena distinto el mismo código: 0000002674407 == 2674407.
    productos["ean"] = (
        productos["id_producto"].astype(str).str.replace(r"\D", "", regex=True).str.lstrip("0")
    )
    productos["descripcion"] = (
        productos["productos_descripcion"].astype(str).str.strip().str.upper()
    )

    # 1.b) Tamaño del envase y precio por unidad base ------------------------
    # Dos fuentes posibles, y NO coinciden:
    #   (a) la descripción: "FIDEO GUISERO 500 GR"
    #   (b) las columnas productos_cantidad/unidad_medida_presentacion
    # Medido sobre 14,5M de filas reales: (b) declara "1 un" para el 39% de los
    # envases con peso, y a veces "1 gr" para una botella de 900 ml, lo que da
    # precios de $97.000.000 por litro. Por eso mando (a) y uso (b) de respaldo.
    desc_parse = parsear_series(productos["descripcion"])
    productos["cantidad_desc"] = desc_parse["cantidad_desc"]
    productos["unidad_desc"] = desc_parse["unidad_desc"]

    if {"productos_cantidad_presentacion",
        "productos_unidad_medida_presentacion"} <= set(productos.columns):
        pres = normalizar(productos["productos_cantidad_presentacion"],
                          productos["productos_unidad_medida_presentacion"])
        productos["cantidad_pres"] = pres["cantidad_base"]
        productos["unidad_pres"] = pres["unidad_base"]
        sin_mapear = unidades_no_reconocidas(
            productos["productos_unidad_medida_presentacion"], top=8)
        if len(sin_mapear):
            log.info("Unidades del campo de presentación que no mapeo:\n%s",
                     sin_mapear.to_string())
    else:
        productos["cantidad_pres"] = float("nan")
        productos["unidad_pres"] = None

    # La descripción gana; la presentación completa lo que falta.
    productos["unidad_base"] = productos["unidad_desc"].fillna(productos["unidad_pres"])
    productos["cantidad_base"] = productos["cantidad_desc"].fillna(productos["cantidad_pres"])
    productos["fuente_tamano"] = pd.Series(
        pd.NA, index=productos.index, dtype="object")
    productos.loc[productos["cantidad_pres"].notna(), "fuente_tamano"] = "presentacion"
    productos.loc[productos["cantidad_desc"].notna(), "fuente_tamano"] = "descripcion"

    productos["precio_unitario"] = productos["precio"] / productos["cantidad_base"]

    # Cuánto se contradicen las dos fuentes. Si esto es alto, no se puede
    # confiar en las columnas de presentación ni como respaldo.
    ambas = productos["cantidad_desc"].notna() & productos["cantidad_pres"].notna() \
        & (productos["unidad_desc"] == productos["unidad_pres"])
    if ambas.any():
        r = productos.loc[ambas, "cantidad_desc"] / productos.loc[ambas, "cantidad_pres"]
        metricas["pct_fuentes_discrepan"] = round(
            100 * (~r.between(0.95, 1.05)).mean(), 2)
    metricas["pct_tamano_desc"] = round(100 * productos["cantidad_desc"].notna().mean(), 2)
    metricas["pct_sin_tamano"] = round(100 * productos["cantidad_base"].isna().mean(), 2)
    log.info("Tamaño resuelto: %.1f%% desde la descripción | %.1f%% sin resolver | "
             "discrepancia entre fuentes: %s%%",
             metricas["pct_tamano_desc"], metricas["pct_sin_tamano"],
             metricas.get("pct_fuentes_discrepan", "n/d"))

    # 2) Nulos en campos núcleo ----------------------------------------------
    productos = _aplicar_regla(
        productos,
        productos["precio"].notna() & ~productos["ean"].isin(["", "nan", "0"]),
        "nulos", metricas, ignorar_guardrail=ignorar_guardrail)

    # 3) EAN con largo inválido ----------------------------------------------
    # Rango amplio a propósito: conviven EAN-13, EAN-8 y códigos internos de
    # balanza para productos a granel, que son más cortos y igual sirven.
    largo = productos["ean"].str.len()
    productos = _aplicar_regla(
        productos, largo.between(4, 14).fillna(False),
        "ean_invalido", metricas, ignorar_guardrail=ignorar_guardrail)

    # 4) Precios fuera de rango físico ---------------------------------------
    productos = _aplicar_regla(
        productos, productos["precio"].between(cfg.PRECIO_MIN, cfg.PRECIO_MAX),
        "precio_fuera_rango", metricas, ignorar_guardrail=ignorar_guardrail)

    # 5) Duplicados exactos (mismo EAN, misma sucursal, mismo día) ------------
    productos = _aplicar_regla(
        productos,
        ~productos.duplicated(subset=["id_comercio", "id_sucursal", "ean"], keep="last"),
        "duplicados", metricas, ignorar_guardrail=ignorar_guardrail)

    # 6) Outliers relativos a la mediana del MISMO EAN ese día ----------------
    # Un precio 100x la mediana casi siempre es una coma decimal mal cargada.
    med = productos.groupby("ean")["precio"].transform("median")
    n_por_ean = productos.groupby("ean")["precio"].transform("size")
    ratio = productos["precio"] / med
    outlier = (n_por_ean >= 5) & (~ratio.between(cfg.OUTLIER_RATIO_MIN, cfg.OUTLIER_RATIO_MAX))
    productos = _aplicar_regla(productos, ~outlier.fillna(False), "outliers",
                               metricas, ignorar_guardrail=ignorar_guardrail)

    # 7) Enriquecer con sucursal y comercio -----------------------------------
    if not sucursales.empty:
        sucursales = sucursales.drop_duplicates(subset=["id_comercio", "id_sucursal"])
        productos = productos.merge(sucursales, on=["id_comercio", "id_sucursal"], how="left",
                                    suffixes=("", "_suc"))
    if not comercios.empty:
        comercios = comercios.drop_duplicates(subset=["id_comercio"])
        cols = ["id_comercio", "comercio_razon_social"] + \
               [c for c in ("comercio_bandera_nombre",) if c in comercios.columns]
        productos = productos.merge(comercios[cols], on="id_comercio", how="left")

    productos["cadena"] = (
        productos.get("comercio_bandera_nombre", pd.Series(index=productos.index, dtype=object))
        .fillna(productos.get("comercio_razon_social"))
        .fillna("SIN_IDENTIFICAR")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    prov_raw = (
        productos.get("sucursales_provincia", pd.Series(index=productos.index, dtype=object))
        .fillna("SIN_DATO").astype(str).str.strip().str.upper()
    )
    # El campo viene como código ISO ("AR-X"). Si algún comercio ya manda el
    # nombre, lo dejamos pasar tal cual en vez de perder la fila.
    productos["provincia"] = prov_raw.map(cfg.PROVINCIAS_ISO).fillna(
        prov_raw.str.title().replace({"Sin_Dato": "Sin dato"})
    )
    productos["fecha"] = pd.Timestamp(fecha)

    metricas["filas_finales"] = len(productos)
    metricas["pct_descartado"] = round(
        100 * (1 - len(productos) / max(metricas["filas_crudas"], 1)), 2
    )
    metricas["eans_unicos"] = productos["ean"].nunique()
    metricas["sucursales"] = productos.groupby(["id_comercio", "id_sucursal"]).ngroups
    metricas["cadenas"] = productos["cadena"].nunique()

    cols_finales = ["fecha", "id_comercio", "id_sucursal", "cadena", "provincia",
                    "ean", "descripcion", "precio",
                    "cantidad_base", "unidad_base", "precio_unitario",
                    "fuente_tamano"]
    # Las columnas de presentación permiten después normalizar a precio por
    # kilo/litro, que es la forma correcta de comparar productos de distinto
    # tamaño. Las arrastro aunque todavía no las use en el índice.
    for extra in ("productos_marca", "productos_cantidad_presentacion",
                  "productos_unidad_medida_presentacion",
                  "sucursales_localidad", "sucursales_latitud",
                  "sucursales_longitud"):
        if extra in productos.columns:
            cols_finales.append(extra)

    out.parent.mkdir(parents=True, exist_ok=True)
    productos[cols_finales].to_parquet(out, index=False, compression="snappy")
    log.info("%s -> %s filas (descarté %.2f%%)", fecha, f"{len(productos):,}", metricas["pct_descartado"])

    _registrar_calidad(metricas)
    return out


def _registrar_calidad(m: dict) -> None:
    fila = pd.DataFrame([m])
    if CALIDAD_PATH.exists():
        hist = pd.read_csv(CALIDAD_PATH)
        hist = hist[hist["fecha"] != m["fecha"]]
        fila = pd.concat([hist, fila], ignore_index=True)
    fila.sort_values("fecha").to_csv(CALIDAD_PATH, index=False)


def run(fecha: str | None = None, forzar: bool = False,
        ignorar_guardrail: bool = False) -> None:
    carpetas = [cfg.RAW / fecha] if fecha else sorted(
        p for p in cfg.RAW.iterdir() if p.is_dir() and p.name != "docs"
    )
    for c in carpetas:
        limpiar_dia(c, forzar=forzar, ignorar_guardrail=ignorar_guardrail)

    if CALIDAD_PATH.exists():
        print("\n=== Resumen de calidad ===")
        print(pd.read_csv(CALIDAD_PATH).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="YYYY-MM-DD; si se omite procesa todo data/raw/")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--ignorar-guardrail", action="store_true",
                    dest="ignorar_guardrail",
                    help="seguir aunque una regla descarte más del umbral")
    a = ap.parse_args()
    run(a.fecha, a.forzar, a.ignorar_guardrail)
