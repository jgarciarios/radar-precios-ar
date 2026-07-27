"""Definición de la canasta de análisis.

Por qué una canasta y no "todos los productos": con 82.916 EANs distintos y
14,5 millones de filas diarias, promediar todo mezcla peras con plasmas. Elijo
~29 items de consumo masivo, comparables entre cadenas, y sobre ESO construyo
el índice. Es la misma lógica que usa el INDEC para el IPC.

Cada item se define por:
  - patrones de texto sobre `descripcion` (los EAN no son estables entre
    cadenas para productos a granel o de marca propia)
  - una UNIDAD BASE esperada (kg, l o un). Todo lo que no venga en esa unidad
    queda afuera: no se compara un desodorante en aerosol con uno en barra.
  - una CANTIDAD MENSUAL en esa unidad, para un hogar tipo de 4 personas.

Los precios se comparan siempre como **precio por unidad base** ($/kg, $/l,
$/un), nunca como precio de envase. Sin eso, "la cerveza más barata" termina
siendo una lata de 269 ml y "la más cara" un barril de 50 litros.

Editá esta lista: es la parte del proyecto donde se ve tu criterio, y donde un
entrevistador va a hurgar.
"""
from __future__ import annotations

import pandas as pd

# (item, categoria, incluye, excluye, unidad_base, cantidad_mes)
CANASTA: list[tuple[str, str, str, str, str, float]] = [
    ("Leche entera",        "Lácteos",     r"LECHE.*ENTERA",           r"POLVO|CHOCOLAT|DESCREM|INFANT", "l",  30.0),
    # Yogur en kg y no en litros: medido sobre datos reales, solo el 6,8% de las
    # filas venía declarado en litros. La densidad del yogur es ~1, así que el
    # $/kg y el $/l son equivalentes, y kg es como lo declara el mercado.
    ("Yogur bebible",       "Lácteos",     r"YOGUR.*BEBIBLE",          r"", "kg",  6.0),
    ("Queso cremoso",       "Lácteos",     r"QUESO.*CREMOSO",          r"UNTABLE|RALLADO", "kg", 1.5),
    ("Manteca",             "Lácteos",     r"MANTECA",                 r"MARGARINA|CACAO|MANI", "kg", 0.6),
    ("Pan lactal",          "Panificados", r"PAN.*LACTAL",             r"", "kg",  3.0),
    ("Harina 000",          "Almacén",     r"HARINA.*(?:000|0000)",    r"LEUDANTE|INTEGRAL", "kg", 3.0),
    ("Fideos secos",        "Almacén",     r"FIDEO",                   r"FRESCO|SALSA|INSTANT", "kg", 3.0),
    ("Arroz largo fino",    "Almacén",     r"ARROZ.*(?:LARGO|FINO)",   r"INTEGRAL|PARBOL", "kg", 3.0),
    ("Aceite girasol",      "Almacén",     r"ACEITE.*GIRASOL",         r"OLIVA|MEZCLA|AEROSOL", "l", 2.5),
    ("Azúcar",              "Almacén",     r"AZUCAR",                  r"IMPALPABLE|ORGANIC|MASCABO", "kg", 2.0),
    ("Yerba mate",          "Almacén",     r"YERBA",                   r"COMPUESTA|SABORIZ", "kg", 2.0),
    ("Café molido",         "Almacén",     r"CAFE.*(?:MOLIDO|TOSTADO)", r"INSTANT|CAPSULA|SOLUBLE", "kg", 0.5),
    ("Puré de tomate",      "Almacén",     r"(?:PURE|SALSA).*TOMATE",  r"", "kg", 2.0),
    ("Arvejas en lata",     "Almacén",     r"ARVEJA",                  r"SECA", "kg", 1.0),
    ("Atún en lata",        "Almacén",     r"ATUN",                    r"", "kg", 0.7),
    ("Huevos",              "Frescos",     r"HUEVO",                   r"CHOCOLATE|PASCUA|LIQUIDO", "un", 30.0),
    # Carne picada y pollo entero SACADOS de la canasta (medido, no asumido):
    # sobre una muestra de 500.000 filas capturaban 47 y 3 registros, con 2 y 1
    # EAN respectivamente. La carne fresca se vende al peso en mostrador y casi
    # no se publica en SEPA con código de barras.
    # Dejar un item con 3 observaciones aportando al índice sería peor que no
    # tenerlo: agrega ruido y da una falsa sensación de cobertura.
    # Consecuencia a declarar: la canasta NO incluye carnes.
    ("Papa",                "Frutas y verduras", r"^PAPA\b",           r"CHIP|SNACK|FRITA|PURE", "kg", 8.0),
    ("Banana",              "Frutas y verduras", r"BANANA",            r"CHIP|DESHIDRAT", "kg", 4.0),
    ("Gaseosa cola",        "Bebidas",     r"(?:COCA|GASEOSA).*COLA",  r"ZERO|LIGHT|SIN AZUCAR", "l", 9.0),
    ("Agua mineral",        "Bebidas",     r"AGUA.*(?:MINERAL|SIN GAS)", r"SABORIZ|TONICA", "l", 20.0),
    ("Cerveza",             "Bebidas",     r"CERVEZA",                 r"SIN ALCOHOL|0,0", "l", 4.0),
    ("Detergente",          "Limpieza",    r"DETERGENTE",              r"ROPA|POLVO", "l", 1.5),
    ("Lavandina",           "Limpieza",    r"LAVANDINA",               r"GEL", "l", 4.0),
    ("Jabón en polvo",      "Limpieza",    r"JABON.*POLVO",            r"", "kg", 3.0),
    ("Papel higiénico",     "Higiene",     r"PAPEL HIGIENICO",         r"", "un", 16.0),
    ("Shampoo",             "Higiene",     r"SHAMPOO",                 r"ACONDICIONADOR|2 EN 1", "l", 0.7),
    ("Pasta dental",        "Higiene",     r"(?:PASTA|CREMA) DENTAL",  r"CEPILLO|ENJUAGUE", "kg", 0.27),
]

COLUMNAS = ["item", "categoria", "incluye", "excluye", "unidad_base", "cantidad_mes"]


def canasta_df() -> pd.DataFrame:
    df = pd.DataFrame(CANASTA, columns=COLUMNAS)
    if df["item"].duplicated().any():
        raise ValueError("Hay items repetidos en CANASTA")
    return df


def etiquetar(df: pd.DataFrame, col: str = "descripcion") -> pd.DataFrame:
    """Agrega `item`, `categoria` y `unidad_esperada`. Sin match -> NaN.

    El orden importa: el primer patrón que matchea gana, así que los items más
    específicos tienen que ir antes en CANASTA.
    """
    desc = df[col].fillna("").astype(str)
    item = pd.Series(pd.NA, index=df.index, dtype="object")
    categoria = pd.Series(pd.NA, index=df.index, dtype="object")
    unidad = pd.Series(pd.NA, index=df.index, dtype="object")

    for nombre, cat, inc, exc, uni, _ in CANASTA:
        libre = item.isna()
        if not libre.any():
            break
        m = libre & desc.str.contains(inc, regex=True, na=False)
        if exc:
            m &= ~desc.str.contains(exc, regex=True, na=False)
        item[m] = nombre
        categoria[m] = cat
        unidad[m] = uni

    out = df.copy()
    out["item"] = item
    out["categoria"] = categoria
    out["unidad_esperada"] = unidad
    return out


def cobertura(df: pd.DataFrame) -> pd.DataFrame:
    """Cuántas filas, EANs y presentaciones capta cada item.

    Qué mirar:
      - un item con 2 o 3 EANs: el patrón es demasiado estrecho
      - un item con miles de EANs: probablemente está mezclando productos
      - `pct_unidad_ok` bajo: el patrón está trayendo otra presentación
        (ej. desodorante en aerosol cuando esperabas ml de roll-on)
    """
    lab = etiquetar(df).dropna(subset=["item"])
    agg = {"filas": ("precio", "size"), "eans": ("ean", "nunique")}
    if "precio_unitario" in lab.columns:
        agg["precio_unitario_mediano"] = ("precio_unitario", "median")
    if "unidad_base" in lab.columns:
        lab = lab.assign(_ok=lab["unidad_base"] == lab["unidad_esperada"])
        agg["pct_unidad_ok"] = ("_ok", "mean")

    res = (lab.groupby(["categoria", "item"]).agg(**agg)
              .reset_index().sort_values("filas", ascending=False))
    if "pct_unidad_ok" in res.columns:
        res["pct_unidad_ok"] = (100 * res["pct_unidad_ok"]).round(1)

    faltantes = {x[0] for x in CANASTA} - set(res["item"])
    if faltantes:
        print(f"[!] Items SIN datos ({len(faltantes)}): {sorted(faltantes)}")
    return res
