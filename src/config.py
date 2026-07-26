"""Configuración central del proyecto Radar de Precios AR."""
from __future__ import annotations

import os
from pathlib import Path

# --- Rutas -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
# Los datos crudos de SEPA pesan GB. Si tenés poco espacio en el disco del
# repo, apuntá RADAR_DATA_DIR a un disco externo:  export RADAR_DATA_DIR=/mnt/d/sepa
DATA = Path(os.environ.get("RADAR_DATA_DIR", ROOT / "data"))
RAW = DATA / "raw"            # ZIPs y CSVs crudos tal como vienen (gitignored)
INTERIM = DATA / "interim"    # parquet particionado, ya limpio
PROCESSED = DATA / "processed"  # agregados finales, listos para Power BI
REPORTS = ROOT / "reports"

for _p in (RAW, INTERIM, PROCESSED, REPORTS / "figs"):
    _p.mkdir(parents=True, exist_ok=True)

# --- Fuente ------------------------------------------------------------------
# Portal CKAN donde se publican los recursos diarios de SEPA (minoristas).
CKAN_BASE = "https://datos.produccion.gob.ar"
CKAN_PACKAGE = "sepa-precios"
CKAN_API = f"{CKAN_BASE}/api/3/action/package_show?id={CKAN_PACKAGE}"

# --- Esquema esperado --------------------------------------------------------
# Los ZIP diarios traen, por comercio, tres CSVs. Los nombres de columna siguen
# la Resolución 678/2020, pero el portal cambió el formato mas de una vez:
# por eso el loader normaliza nombres y solo EXIGE las columnas núcleo.
# TRAMPA DEL ESQUEMA (verificado contra archivos reales, 2026-07-24):
# el código de barras NO está en `productos_ean`. Está en `id_producto`.
# El campo `productos_ean` es la CANTIDAD de EANs del producto y vale 1
# en prácticamente todas las filas. Confundirlos hace que el pipeline
# descarte el 100% de los datos sin avisar.
#     12|1|170|7792180005205|1|ACEITE OLIVA ...
#      ^      ^ id_producto  ^ productos_ean (cantidad, no código)
PRODUCTOS_CORE = [
    "id_comercio",
    "id_sucursal",
    "id_producto",            # <- este es el EAN
    "productos_descripcion",
    "productos_precio_lista",
]
PRODUCTOS_OPCIONALES = [
    "id_bandera",
    "productos_ean",          # cantidad de EANs, no el código
    "productos_marca",
    "productos_cantidad_presentacion",
    "productos_unidad_medida_presentacion",
    "productos_precio_referencia",
    "productos_cantidad_referencia",
    "productos_unidad_medida_referencia",
]
SUCURSALES_CORE = ["id_comercio", "id_sucursal", "sucursales_provincia"]
SUCURSALES_OPCIONALES = [
    "id_bandera",
    "sucursales_nombre",
    "sucursales_tipo",
    "sucursales_localidad",
    "sucursales_latitud",
    "sucursales_longitud",
]
COMERCIO_CORE = ["id_comercio", "comercio_razon_social"]
COMERCIO_OPCIONALES = ["id_bandera", "comercio_cuit", "comercio_bandera_nombre"]

# --- Provincias --------------------------------------------------------------
# SEPA publica la provincia como código ISO 3166-2:AR. Sin este mapeo el
# dashboard muestra "AR-T" y nadie entiende nada.
PROVINCIAS_ISO = {
    "AR-A": "Salta", "AR-B": "Buenos Aires", "AR-C": "CABA", "AR-D": "San Luis",
    "AR-E": "Entre Ríos", "AR-F": "La Rioja", "AR-G": "Santiago del Estero",
    "AR-H": "Chaco", "AR-J": "San Juan", "AR-K": "Catamarca", "AR-L": "La Pampa",
    "AR-M": "Mendoza", "AR-N": "Misiones", "AR-P": "Formosa", "AR-Q": "Neuquén",
    "AR-R": "Río Negro", "AR-S": "Santa Fe", "AR-T": "Tucumán", "AR-U": "Chubut",
    "AR-V": "Tierra del Fuego", "AR-W": "Corrientes", "AR-X": "Córdoba",
    "AR-Y": "Jujuy", "AR-Z": "Santa Cruz",
}

# --- Reglas de calidad -------------------------------------------------------
PRECIO_MIN = 1.0          # por debajo de esto es error de carga
PRECIO_MAX = 5_000_000.0  # electrodomésticos/materiales entran acá
EAN_LEN_VALIDAS = {8, 12, 13, 14}

# Corte de outliers: descarta precios que se desvían más de N veces la mediana
# del MISMO EAN en el MISMO día (protege contra comas decimales mal cargadas).
OUTLIER_RATIO_MAX = 10.0
OUTLIER_RATIO_MIN = 0.1

# Guardrail: ninguna regla de limpieza debería descartar más de este % de las
# filas. Si lo supera, el pipeline corta y muestra ejemplos de lo que estaba
# tirando. Nació de un bug real: una regla mal escrita descartó el 100% de los
# datos y el proceso siguió como si nada, escribiendo un parquet vacío.
MAX_DESCARTE_POR_REGLA = 0.20

# Comparabilidad dentro de un item de la canasta.
# Problema real detectado con datos del 2026-07-24: el patrón "BANANA" capturaba
# la banana suelta ($25) y el kilo de banana ($7.025) como si fueran el mismo
# producto, dando una "dispersión" del 28.000%. No es dispersión de precios:
# son presentaciones distintas.
# Solución: dentro de cada item se descartan los precios que se alejan más de
# estos factores de la mediana del item. Es un filtro de COMPARABILIDAD, no de
# calidad del dato — el precio puede ser correcto y aun así no ser comparable.
# Con la referencia calibrada sobre filas confiables se puede apretar el rango:
# antes la mediana estaba contaminada y había que ser permisivo.
ITEM_RATIO_MIN = 0.35
ITEM_RATIO_MAX = 3.0
