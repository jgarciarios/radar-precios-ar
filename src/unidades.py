"""Normalización de unidades de medida a una base común: kg, l o un.

Por qué existe este módulo
--------------------------
SEPA publica `productos_precio_lista` como el precio del envase, sin normalizar.
Comparar esos precios entre cadenas es incorrecto cuando venden presentaciones
distintas del mismo producto. Casos reales encontrados en los datos del
2026-07-24:

    Cerveza  -> desde $110 (lata 269 ml) hasta $332.600 (barril 50 l)
    Banana   -> $799 la unidad vs $7.050 el kilo

Un filtro de outliers no arregla esto: los dos precios son correctos. Lo que
está mal es la comparación. La solución es dividir el precio por la cantidad
que trae el envase, llevado todo a una unidad base:

    precio_unitario = precio_lista / cantidad_base    ($/kg, $/l o $/un)

Recién ahí "la cerveza más barata" significa algo.

Las cadenas escriben la unidad como se les ocurre ('GR', 'gr.', 'grs', 'gramos',
'cm3', 'cc', 'ltr', 'LTS'), así que el mapeo es por texto normalizado.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Cada entrada: alias -> (unidad_base, factor para pasar a la unidad base)
_MAPA: dict[str, tuple[str, float]] = {}


def _reg(unidad_base: str, factor: float, *alias: str) -> None:
    for a in alias:
        _MAPA[a] = (unidad_base, factor)


# --- Masa -> kg ---------------------------------------------------------------
_reg("kg", 0.001, "g", "gr", "grs", "grm", "gra", "gram", "gramo", "gramos")
_reg("kg", 1.0, "kg", "kgs", "kgr", "kilo", "kilos", "kilogramo", "kilogramos")
_reg("kg", 0.000001, "mg", "miligramo", "miligramos")

# --- Volumen -> l -------------------------------------------------------------
_reg("l", 0.001, "ml", "mls", "mililitro", "mililitros", "cc", "cm3", "cm³")
_reg("l", 1.0, "l", "lt", "lts", "ltr", "ltrs", "litro", "litros")

# --- Conteo -> un -------------------------------------------------------------
_reg("un", 1.0, "un", "u", "ud", "uds", "uni", "unid", "unidad", "unidades",
     "rollo", "rollos", "sobre", "sobres", "bolsa", "bolsas", "pack", "packs",
     "botella", "botellas", "lata", "latas", "paquete", "paquetes", "envase")
_reg("un", 12.0, "docena", "docenas", "doc")
_reg("un", 6.0, "media docena")

# --- Códigos UN/CEFACT Rec 20 -------------------------------------------------
# Hallazgo sobre datos reales: SEPA mezcla texto libre ("gr", "LTS") con códigos
# del estándar internacional UN/CEFACT Recommendation 20 en el mismo campo, sin
# ninguna marca que los distinga. Solo 'ea' son 1.4 millones de filas por día.
# Sin esto se perdía el 13,5% de los registros por una unidad "desconocida" que
# en realidad estaba perfectamente estandarizada.
_reg("un", 1.0, "ea", "h87", "pce", "pk", "ct")          # each / piece / pack
_reg("kg", 1.0, "kgm")                                    # kilogram
_reg("kg", 0.001, "grm")                                  # gram
_reg("l", 1.0, "ltr")                                     # litre
_reg("l", 0.001, "mlt")                                   # millilitre
_reg("l", 0.001, "cmq")                                   # centímetro cúbico
_reg("l", 0.01, "clt", "cl")                              # centilitro
_reg("l", 0.1, "dlt")                                     # decilitro

# Unidades que existen en los datos y NO se mapean a propósito: miden longitud
# o superficie (rollos de papel, film, aluminio). No tienen equivalencia con
# kg/l/un y forzarla sería inventar. Las filas quedan fuera del índice.
NO_MAPEABLES = {"m", "mt", "mtr", "m2", "mtk", "cm", "cmt", "m3", "mtq", "cu"}

UNIDADES_BASE = ("kg", "l", "un")


def _limpiar(u: str) -> str:
    s = unicodedata.normalize("NFKD", str(u)).encode("ascii", "ignore").decode()
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9 ]+", "", s)   # saca puntos, barras, etc.
    return re.sub(r"\s+", " ", s).strip()


def normalizar(cantidad: pd.Series, unidad: pd.Series) -> pd.DataFrame:
    """Devuelve un DataFrame con `cantidad_base` y `unidad_base`.

    Las filas cuya unidad no se reconoce quedan en NaN a propósito: prefiero
    perder esas filas antes que inventar una equivalencia y publicar un
    precio por kilo que no existe.
    """
    u = unidad.map(_limpiar)
    mapeado = u.map(_MAPA)

    base = mapeado.map(lambda t: t[0] if isinstance(t, tuple) else None)
    factor = mapeado.map(lambda t: t[1] if isinstance(t, tuple) else float("nan"))

    cant = pd.to_numeric(cantidad, errors="coerce")
    # Cantidad 0 o negativa es error de carga: no se puede dividir por eso.
    cant = cant.where(cant > 0)

    return pd.DataFrame({
        "cantidad_base": cant * factor,
        "unidad_base": base,
    }, index=cantidad.index)


def unidades_no_reconocidas(unidad: pd.Series, top: int = 25) -> pd.Series:
    """Diagnóstico: qué textos de unidad no sé mapear y cuánto pesan.

    Correlo cada vez que agregues días de datos. Si aparece una unidad nueva
    con volumen, agregala arriba en vez de dejar que se pierdan las filas.
    """
    u = unidad.map(_limpiar)
    return u[~u.isin(_MAPA) & ~u.isin(NO_MAPEABLES)].value_counts().head(top)
