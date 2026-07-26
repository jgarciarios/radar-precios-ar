"""Agregados analíticos sobre el Parquet limpio, usando DuckDB.

DuckDB consulta los Parquet directamente desde disco: podés trabajar con
decenas de millones de filas en una notebook de 8GB sin cargar nada en RAM.
Eso es el punto técnico fuerte del proyecto — mostralo en la entrevista.

Uso:
    python -m src.transform

Salidas en data/processed/ (todas listas para Power BI):
    dim_item.csv                 catálogo de la canasta
    fact_precio_item.csv         precio por item x cadena x provincia x fecha
    fact_dispersion.csv          min/max/mediana y spread por item x provincia x fecha
    fact_canasta.csv             costo de la canasta por escenario y fecha
    fact_ranking_cadenas.csv     qué tan cara es cada cadena vs el mercado
    resumen_hallazgos.json       los 3 números del pitch
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from src import config as cfg
from src.canasta import canasta_df, etiquetar
from src.utils import fmt_pesos, get_logger

log = get_logger("transform")

PARQUET_GLOB = str(cfg.INTERIM / "fecha=*" / "*.parquet")


def _cargar_etiquetado(con: duckdb.DuckDBPyConnection) -> None:
    """Lee el parquet, etiqueta con la canasta y registra la tabla en DuckDB."""
    df = con.execute(f"""
        SELECT fecha, cadena, provincia, ean, descripcion,
               precio, unidad_base, precio_unitario, fuente_tamano
        FROM read_parquet('{PARQUET_GLOB}')
    """).df()
    if df.empty:
        raise SystemExit("No hay datos en data/interim/. Corré extract.py y clean.py primero.")

    log.info("Filas limpias: %s | fechas: %s", f"{len(df):,}", df["fecha"].nunique())
    lab = etiquetar(df).dropna(subset=["item"])
    log.info("Filas dentro de la canasta: %s (%.1f%%)", f"{len(lab):,}", 100 * len(lab) / len(df))
    lab = _filtrar_comparables(lab)
    con.register("precios", lab)
    con.register("dim_item", canasta_df())


def _filtrar_comparables(lab):
    """Deja solo filas comparables dentro de cada item, en dos pasos.

    Paso 1 — UNIDAD. Cada item declara su unidad base esperada (kg, l o un).
    Todo lo que venga en otra unidad se descarta: comparar una gaseosa vendida
    por unidad contra una vendida por litro no mide diferencia de precio.

    Paso 2 — RANGO. Sobre el precio YA normalizado a $/kg, $/l o $/un, descarto
    lo que se aleja más de ciertos factores de la mediana del item. Es la red de
    seguridad para lo que el patrón de texto capturó de más (ej. "CERVEZA" que
    trae un pack de 24). Uso mediana y factores, no desvío estándar, porque la
    distribución está contaminada justo por lo que quiero sacar.

    Ninguno de los dos pasos es limpieza de datos: los precios descartados
    suelen ser correctos. Es comparabilidad, y por eso se reporta aparte.
    """
    n0 = len(lab)

    # Paso 1: unidad esperada
    ok_unidad = lab["unidad_base"] == lab["unidad_esperada"]
    perdidas = (
        lab[~ok_unidad].groupby(["item", "unidad_base"], dropna=False)
        .size().rename("filas").reset_index()
        .sort_values("filas", ascending=False)
    )
    if len(perdidas):
        log.warning("Descarté %s filas (%.1f%%) por venir en otra unidad. Top 5:\n%s",
                    f"{(~ok_unidad).sum():,}", 100 * (~ok_unidad).mean(),
                    perdidas.head(5).to_string(index=False))
    lab = lab[ok_unidad & lab["precio_unitario"].notna()
              & (lab["precio_unitario"] > 0)]

    if lab.empty:
        raise SystemExit(
            "No quedó ninguna fila comparable. Revisá src/unidades.py: "
            "probablemente las unidades del origen no se están mapeando."
        )

    # Paso 2: rango sobre el precio unitario, calibrado con la fuente confiable
    #
    # No todas las filas valen lo mismo. Donde el tamaño salió de la DESCRIPCIÓN
    # ("FIDEO GUISERO 500 GR") el dato es sólido; donde salió de las columnas de
    # presentación puede ser el "1 gr" para una botella de 900 ml que produce
    # precios de $38.000.000 por litro.
    #
    # Entonces: calculo la mediana de referencia SOLO con las filas confiables y
    # audito todas contra esa referencia. Usar la mediana de todo sería dejar que
    # el ruido defina qué es normal.
    conf = lab[lab["fuente_tamano"] == "descripcion"]
    n_conf = conf.groupby("item")["precio_unitario"].size()
    ref = conf.groupby("item")["precio_unitario"].median()
    # Si un item no tiene suficientes filas confiables, no hay contra qué
    # calibrar: uso su propia mediana y lo dejo registrado.
    ref_todos = lab.groupby("item")["precio_unitario"].median()
    sin_referencia = sorted(set(ref_todos.index) - set(n_conf[n_conf >= 30].index))
    if sin_referencia:
        log.warning("Items sin referencia confiable (uso su propia mediana): %s",
                    ", ".join(sin_referencia))
    referencia = ref.where(n_conf >= 30).combine_first(ref_todos)

    med = lab["item"].map(referencia)
    ratio = lab["precio_unitario"] / med
    ok = ratio.between(cfg.ITEM_RATIO_MIN, cfg.ITEM_RATIO_MAX)

    if (~ok).any():
        det = (lab[~ok].groupby(["item", "fuente_tamano"], dropna=False)
               .agg(filas=("precio_unitario", "size"),
                    pu_min=("precio_unitario", "min"),
                    pu_max=("precio_unitario", "max"))
               .reset_index().sort_values("filas", ascending=False))
        det["referencia"] = det["item"].map(referencia).round(0)
        log.warning("Descarté %s filas (%.1f%%) fuera de rango contra la referencia "
                    "confiable de su item. Top 6:\n%s",
                    f"{(~ok).sum():,}", 100 * (~ok).mean(),
                    det.head(6).round(0).to_string(index=False))
        det.to_csv(cfg.PROCESSED / "_descartes_comparabilidad.csv", index=False)

    lab = lab[ok]
    log.info("Comparables: %s de %s filas (%.1f%%)",
             f"{len(lab):,}", f"{n0:,}", 100 * len(lab) / max(n0, 1))
    return lab


def construir(con: duckdb.DuckDBPyConnection) -> dict:
    out = cfg.PROCESSED

    # 1) Precio representativo por item x cadena x provincia x fecha ----------
    # Mediana, no promedio: es robusta a los outliers que sobrevivieron al clean.
    con.execute("""
        CREATE OR REPLACE TABLE fact_precio_item AS
        SELECT fecha, item, categoria, cadena, provincia,
               median(precio_unitario)      AS precio_mediano,
               count(*)                     AS n_observaciones,
               count(DISTINCT ean)          AS n_eans
        FROM precios
        GROUP BY 1,2,3,4,5
        HAVING count(*) >= 3
    """)

    # 2) Dispersión: el hallazgo principal ------------------------------------
    con.execute("""
        CREATE OR REPLACE TABLE fact_dispersion AS
        WITH base AS (
            SELECT fecha, item, categoria, provincia, cadena, precio_mediano
            FROM fact_precio_item
        )
        SELECT fecha, item, categoria, provincia,
               count(DISTINCT cadena)                       AS cadenas_comparadas,
               min(precio_mediano)                          AS precio_min,
               median(precio_mediano)                       AS precio_med,
               max(precio_mediano)                          AS precio_max,
               max(precio_mediano) - min(precio_mediano)    AS gap_pesos,
               100.0 * (max(precio_mediano) / nullif(min(precio_mediano),0) - 1) AS gap_pct,
               arg_min(cadena, precio_mediano)              AS cadena_mas_barata,
               arg_max(cadena, precio_mediano)              AS cadena_mas_cara
        FROM base
        GROUP BY 1,2,3,4
        HAVING count(DISTINCT cadena) >= 3
    """)

    # 3) Canasta: 3 escenarios de compra --------------------------------------
    #    optima  = comprás cada item donde está más barato (imposible en la
    #              práctica, pero marca el piso teórico)
    #    tipica  = comprás todo a precio mediano de mercado
    #    peor    = comprás todo donde está más caro
    # El costo sale de multiplicar precio x cantidad mensual del hogar tipo,
    # así el número es en pesos reales y auditable, no un índice abstracto.
    con.execute("""
        CREATE OR REPLACE TABLE fact_canasta AS
        SELECT d.fecha, d.provincia,
               sum(d.precio_min * i.cantidad_mes) AS canasta_optima,
               sum(d.precio_med * i.cantidad_mes) AS canasta_tipica,
               sum(d.precio_max * i.cantidad_mes) AS canasta_peor,
               count(DISTINCT d.item)             AS items_cubiertos,
               sum(i.cantidad_mes) / (SELECT sum(cantidad_mes) FROM dim_item)
                                                  AS cobertura_ponderada
        FROM fact_dispersion d
        JOIN dim_item i USING (item)
        GROUP BY 1,2
    """)

    # 4) Ranking de cadenas: índice 100 = mediana del mercado -----------------
    con.execute("""
        CREATE OR REPLACE TABLE fact_ranking_cadenas AS
        WITH ref AS (
            SELECT fecha, item, provincia, median(precio_mediano) AS ref_precio
            FROM fact_precio_item GROUP BY 1,2,3
        )
        SELECT p.fecha, p.cadena, p.provincia,
               count(DISTINCT p.item)                                  AS items,
               100.0 * median(p.precio_mediano / nullif(r.ref_precio,0)) AS indice_vs_mercado
        FROM fact_precio_item p
        JOIN ref r USING (fecha, item, provincia)
        GROUP BY 1,2,3
        HAVING count(DISTINCT p.item) >= 10
    """)

    for t in ("dim_item", "fact_precio_item", "fact_dispersion",
              "fact_canasta", "fact_ranking_cadenas"):
        df = con.execute(f"SELECT * FROM {t}").df()
        df.to_csv(out / f"{t}.csv", index=False)
        log.info("%-22s -> %s filas", t, f"{len(df):,}")

    return _hallazgos(con)


def _hallazgos(con: duckdb.DuckDBPyConnection) -> dict:
    """Los 3 números que vas a decir en la entrevista. Si esto sale vacío,
    el proyecto no está terminado."""
    h: dict = {}

    top = con.execute("""
        SELECT item, provincia, round(gap_pct,1) AS gap_pct,
               round(precio_min,0) AS min, round(precio_max,0) AS max,
               cadena_mas_barata, cadena_mas_cara
        FROM fact_dispersion
        WHERE fecha = (SELECT max(fecha) FROM fact_dispersion)
        ORDER BY gap_pct DESC LIMIT 10
    """).df()
    h["top_dispersion"] = top.to_dict("records")
    h["gap_mediano_pct"] = float(con.execute(
        "SELECT median(gap_pct) FROM fact_dispersion"
    ).fetchone()[0] or 0)

    can = con.execute("""
        SELECT round(avg(canasta_optima),0) AS optima,
               round(avg(canasta_tipica),0) AS tipica,
               round(avg(canasta_peor),0)   AS peor
        FROM fact_canasta
        WHERE fecha = (SELECT max(fecha) FROM fact_canasta)
    """).df().iloc[0].to_dict()
    h["canasta"] = can
    if can["tipica"]:
        h["ahorro_mensual_pesos"] = float(can["tipica"] - can["optima"])
        h["ahorro_mensual_pct"] = round(100 * (1 - can["optima"] / can["tipica"]), 1)

    var = con.execute("""
        WITH x AS (
            SELECT fecha, avg(canasta_tipica) AS v FROM fact_canasta GROUP BY 1
        )
        SELECT strftime(min(fecha), '%d/%m/%Y') AS f0,
               strftime(max(fecha), '%d/%m/%Y') AS f1,
               count(*)                         AS dias,
               100.0 * (max_by(v, fecha) / nullif(min_by(v, fecha),0) - 1) AS var_pct
        FROM x
    """).df().iloc[0].to_dict()
    h["variacion_canasta"] = var

    (cfg.PROCESSED / "resumen_hallazgos.json").write_text(
        json.dumps(h, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return h


def imprimir_pitch(h: dict) -> None:
    print("\n" + "=" * 66)
    print("HALLAZGOS — esto es lo que contás en 2 minutos")
    print("=" * 66)
    if h.get("gap_mediano_pct"):
        print(f"1) Para el producto mediano de la canasta, la cadena más cara cobra")
        print(f"   {h['gap_mediano_pct']:.0f}% más que la más barata, en la misma provincia.")
    if h.get("top_dispersion"):
        t = h["top_dispersion"][0]
        print(f"   Caso extremo: {t['item']} en {t['provincia']} varía {t['gap_pct']}% "
              f"({fmt_pesos(t['min'])} vs {fmt_pesos(t['max'])}).")
    if h.get("ahorro_mensual_pesos"):
        c = h["canasta"]
        print(f"2) La canasta mensual del hogar tipo cuesta {fmt_pesos(c['tipica'])} a precio")
        print(f"   de mercado y {fmt_pesos(c['optima'])} comprando cada item donde está más barato:")
        print(f"   {fmt_pesos(h['ahorro_mensual_pesos'])}/mes de diferencia ({h['ahorro_mensual_pct']}%).")
    v = h.get("variacion_canasta", {})
    if v.get("var_pct") is not None:
        print(f"3) La canasta se movió {v['var_pct']:.1f}% en {int(v['dias'])} días "
              f"({v['f0']} a {v['f1']}).")
    print("=" * 66 + "\n")


def run() -> dict:
    con = duckdb.connect()
    _cargar_etiquetado(con)
    h = construir(con)
    imprimir_pitch(h)
    return h


if __name__ == "__main__":
    run()
