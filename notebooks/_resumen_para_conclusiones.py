"""Imprime, de una sola vez, los números que van en las conclusiones de los
notebooks 01 y 02.

    python notebooks/_resumen_para_conclusiones.py

No calcula nada nuevo: junta lo que los notebooks ya muestran repartido en
varias celdas, para poder redactar las conclusiones sin ir buscando cada número.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RADAR_DATA_DIR", os.path.expanduser("~/sepa-data"))

import duckdb
import pandas as pd

from src import config as cfg
from src.canasta import cobertura

PARQUET = str(cfg.INTERIM / "fecha=*" / "*.parquet")
con = duckdb.connect()
dias = sorted(p.name.split("=")[1] for p in cfg.INTERIM.glob("fecha=*"))
assert dias, f"No hay datos en {cfg.INTERIM}"


def t(titulo: str) -> None:
    print(f"\n{'=' * 62}\n{titulo}\n{'=' * 62}")


t("1. VOLUMEN Y ESTABILIDAD")
cal = pd.read_csv(cfg.INTERIM / "_calidad.csv")
print(f"Días: {len(dias)} ({dias[0]} a {dias[-1]})")
print(f"Filas crudas totales:  {cal.filas_crudas.sum():,}")
print(f"Filas finales totales: {cal.filas_finales.sum():,}")
print(f"Descarte por calidad:  {100*(1-cal.filas_finales.sum()/cal.filas_crudas.sum()):.3f}%")
print(f"Cadenas por día:       {cal.cadenas.min()} a {cal.cadenas.max()}")
print(f"Sucursales por día:    {cal.sucursales.min():,} a {cal.sucursales.max():,}")
print(f"EANs únicos por día:   {cal.eans_unicos.min():,} a {cal.eans_unicos.max():,}")

t("2. CONCENTRACIÓN POR CADENA")
conc = con.execute(f"""
    SELECT cadena, count(*) AS filas,
           round(100.0*count(*)/sum(count(*)) OVER (), 1) AS pct,
           count(DISTINCT id_sucursal) AS sucursales
    FROM read_parquet('{PARQUET}') GROUP BY 1 ORDER BY filas DESC
""").df()
print(conc.head(10).to_string(index=False))
print(f"\nTop 1 concentra: {conc.pct.iloc[0]:.1f}%  |  Top 3: {conc.pct.head(3).sum():.1f}%")

t("3. COBERTURA GEOGRÁFICA")
prov = con.execute(f"""
    SELECT provincia, count(*) AS filas, count(DISTINCT cadena) AS cadenas
    FROM read_parquet('{PARQUET}') GROUP BY 1 ORDER BY filas DESC
""").df()
comp = prov[prov.cadenas >= 3]
print(f"Provincias totales: {len(prov)}  |  con 3+ cadenas: {len(comp)}")
print(f"Esas cubren el {100*comp.filas.sum()/prov.filas.sum():.1f}% de los registros")
print("\nProvincias NO comparables (<3 cadenas):")
print(prov[prov.cadenas < 3][["provincia", "cadenas", "filas"]].to_string(index=False))

t("4. TAMAÑO DEL ENVASE: LAS DOS FUENTES")
f = cal[["fecha", "pct_tamano_desc", "pct_sin_tamano", "pct_fuentes_discrepan"]]
print(f.to_string(index=False))
print(f"\nDiscrepancia entre fuentes: {f.pct_fuentes_discrepan.min():.1f}% a "
      f"{f.pct_fuentes_discrepan.max():.1f}% (promedio {f.pct_fuentes_discrepan.mean():.1f}%)")
print(f"Tamaño desde descripción:   {f.pct_tamano_desc.mean():.1f}% promedio")
print(f"Sin tamaño resoluble:       {f.pct_sin_tamano.mean():.1f}% promedio")

t("5. ESTABILIDAD DE LA MUESTRA")
estab = con.execute(f"""
    WITH s AS (SELECT cadena, id_comercio, id_sucursal, count(DISTINCT fecha) AS d
               FROM read_parquet('{PARQUET}') GROUP BY 1,2,3)
    SELECT d AS dias_reportados, count(*) AS sucursales FROM s GROUP BY 1 ORDER BY 1
""").df()
print(estab.to_string(index=False))
tot = estab.sucursales.sum()
compl = estab[estab.dias_reportados == len(dias)].sucursales.sum()
print(f"\nSucursales presentes los {len(dias)} días: {compl:,} de {tot:,} ({100*compl/tot:.1f}%)")

cad = con.execute(f"""
    SELECT cadena, count(DISTINCT fecha) AS dias FROM read_parquet('{PARQUET}')
    GROUP BY 1 ORDER BY dias
""").df()
inc = cad[cad.dias < len(dias)]
print(f"\nCadenas que NO reportan los {len(dias)} días: {len(inc)}")
if len(inc):
    print(inc.to_string(index=False))

t("6. CATÁLOGO: MISMO EAN, DISTINTAS DESCRIPCIONES")
d = con.execute(f"""
    SELECT max(n) AS max_desc_por_ean,
           round(avg(n), 2) AS promedio,
           count(*) FILTER (WHERE n > 1) AS eans_con_varias,
           count(*) AS eans_totales
    FROM (SELECT ean, count(DISTINCT descripcion) AS n
          FROM read_parquet('{PARQUET}') GROUP BY 1)
""").df().iloc[0]
print(f"Máximo de descripciones para un mismo EAN: {int(d.max_desc_por_ean)}")
print(f"EANs con más de una descripción: {int(d.eans_con_varias):,} de "
      f"{int(d.eans_totales):,} ({100*d.eans_con_varias/d.eans_totales:.1f}%)")

t("7. COBERTURA DE LA CANASTA")
m = con.execute(f"""
    SELECT ean, descripcion, precio, precio_unitario, unidad_base
    FROM read_parquet('{PARQUET}') USING SAMPLE 500000 ROWS
""").df()
cob = cobertura(m)
print(f"La canasta capta el {100*cob.filas.sum()/len(m):.1f}% de las filas\n")
cols = [c for c in ("categoria", "item", "filas", "eans", "pct_unidad_ok") if c in cob.columns]
print(cob[cols].to_string(index=False))

print("\n" + "=" * 62)
print("Copiá TODO esto y pegámelo.")
print("=" * 62)
