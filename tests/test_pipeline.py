"""Verificación del pipeline: recalcula los agregados en pandas y los compara
contra lo que produjo DuckDB, más un set de invariantes de negocio.

Que un dashboard se vea lindo no significa que el número esté bien. Esto es lo
que te salva de presentar una métrica rota en una entrevista.

Uso:
    python -m tests.test_pipeline          # standalone, imprime el reporte
    pytest tests/test_pipeline.py          # si tenés pytest
"""
from __future__ import annotations

import glob

import pandas as pd

from src import config as cfg
from src.canasta import canasta_df, etiquetar
from src.transform import _filtrar_comparables

TOL = 1e-6


def _cargar():
    archivos = glob.glob(str(cfg.INTERIM / "fecha=*" / "*.parquet"))
    if not archivos:
        raise SystemExit("No hay datos. Corré: python -m tests.make_fixture && python -m src.clean")
    raw = pd.concat([pd.read_parquet(p) for p in archivos], ignore_index=True)
    # Mismo filtro de comparabilidad que aplica transform.py: si el test no lo
    # replica, compara peras con manzanas y falla por la razón equivocada.
    lab = _filtrar_comparables(etiquetar(raw).dropna(subset=["item"]))
    return raw, lab


def _proc(nombre: str) -> pd.DataFrame:
    return pd.read_csv(cfg.PROCESSED / f"{nombre}.csv", parse_dates=["fecha"])


# --- Reproducibilidad: DuckDB vs pandas --------------------------------------
def test_precio_item_coincide():
    _, lab = _cargar()
    esperado = (lab.groupby(["fecha", "item", "cadena", "provincia"])["precio_unitario"]
                   .agg(["median", "size"]).reset_index().query("size >= 3"))
    real = _proc("fact_precio_item")
    j = real.merge(esperado, on=["fecha", "item", "cadena", "provincia"])
    assert len(j) == len(real) == len(esperado), "difieren las filas entre DuckDB y pandas"
    assert (real.precio_mediano - j["median"]).abs().max() < TOL


def test_dispersion_coincide():
    _, lab = _cargar()
    base = (lab.groupby(["fecha", "item", "cadena", "provincia"])["precio_unitario"]
               .agg(["median", "size"]).reset_index().query("size >= 3"))
    esperado = (base.groupby(["fecha", "item", "provincia"])["median"]
                    .agg(["min", "max", "count"]).reset_index().query("count >= 3"))
    esperado["gap"] = 100 * (esperado["max"] / esperado["min"] - 1)
    real = _proc("fact_dispersion")
    j = real.merge(esperado, on=["fecha", "item", "provincia"])
    assert len(j) == len(real)
    assert (j.gap_pct - j.gap).abs().max() < TOL


def test_canasta_coincide():
    disp = _proc("fact_dispersion")
    cd = canasta_df()[["item", "cantidad_mes"]]
    esperado = (disp.merge(cd, on="item")
                    .assign(opt=lambda x: x.precio_min * x.cantidad_mes)
                    .groupby(["fecha", "provincia"])["opt"].sum().reset_index())
    real = _proc("fact_canasta")
    j = real.merge(esperado, on=["fecha", "provincia"])
    assert (j.canasta_optima - j.opt).abs().max() < TOL


# --- Invariantes de negocio ---------------------------------------------------
def test_orden_de_precios():
    d = _proc("fact_dispersion")
    assert (d.precio_min <= d.precio_med).all()
    assert (d.precio_med <= d.precio_max).all()
    assert (d.gap_pct >= 0).all()


def test_orden_de_escenarios():
    c = _proc("fact_canasta")
    assert (c.canasta_optima <= c.canasta_tipica).all()
    assert (c.canasta_tipica <= c.canasta_peor).all()


def test_precio_unitario_coherente():
    """precio_unitario tiene que ser exactamente precio / cantidad_base."""
    raw, _ = _cargar()
    con = raw[raw.cantidad_base.notna()]
    esperado = con.precio / con.cantidad_base
    assert (con.precio_unitario - esperado).abs().max() < TOL
    # Y donde no se pudo mapear la unidad, no se inventa un valor
    assert raw.loc[raw.unidad_base.isna(), "precio_unitario"].isna().all()


def test_limpieza_efectiva():
    raw, _ = _cargar()
    assert raw.precio.between(cfg.PRECIO_MIN, cfg.PRECIO_MAX).all(), "sobrevivió un precio fuera de rango"
    assert raw.duplicated(["fecha", "id_comercio", "id_sucursal", "ean"]).sum() == 0
    assert not raw.provincia.str.startswith("AR-").any(), "quedaron códigos ISO sin mapear"
    assert raw.precio.notna().all()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in tests:
        try:
            t()
            print(f"  OK   {t.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"  FALLA {t.__name__}: {e}")
    print(f"\n{len(tests) - fallos}/{len(tests)} verificaciones pasan")
    raise SystemExit(1 if fallos else 0)
