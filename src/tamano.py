"""Extrae el tamaño del envase desde la DESCRIPCIÓN del producto.

Por qué no alcanza con las columnas de presentación
--------------------------------------------------
SEPA tiene `productos_cantidad_presentacion` y `productos_unidad_medida_presentacion`,
pero medidas sobre los datos reales del 2026-07-24 (14,5M de filas) muestran que
no son confiables:

  - ~39% de las filas de la canasta declaran `1 un` para envases que claramente
    tienen peso o volumen (un paquete de fideos de 500 g informado como "1 un")
  - hay filas que declaran `1 gr` para una botella de 900 ml, lo que al dividir
    da precios de $97.000.000 por litro
  - 13,5% de las filas traen una unidad que no está en ningún estándar

En cambio la descripción, que es lo que la cadena le muestra al consumidor, casi
siempre trae el tamaño: "ACEITE GIRASOL 900 ML", "FIDEO GUISERO 500 GR".

Estrategia: parsear la descripción primero, usar las columnas de presentación
como respaldo, y medir cuánto se contradicen. Cuando dos fuentes discrepan, lo
peor que se puede hacer es elegir una en silencio.

Casos que maneja
----------------
    "ACEITE GIRASOL 900 ML"          -> 0.9   l
    "FIDEO GUISERO 500 GR"           -> 0.5   kg
    "HARINA 000 X 1 KG"              -> 1.0   kg
    "GASEOSA COLA 2.25 LTS"          -> 2.25  l
    "GASEOSA COLA 2,25 LTS"          -> 2.25  l   (coma decimal)
    "CERVEZA PACK X 6 X 473 ML"      -> 2.838 l   (multipack)
    "PAPA NEGRA POR KG"              -> 1.0   kg  (venta a granel)
    "HUEVO BLANCO DOCENA"            -> 12.0  un
    "PAPEL HIGIENICO 4 UNIDADES"     -> 4.0   un
    "LECHE ENTERA SACHET 1LT"        -> 1.0   l   (sin espacio)
"""
from __future__ import annotations

import re

import pandas as pd

from src.unidades import _MAPA, _limpiar

# Alias de unidad ordenados de más largo a más corto: si "KG" se probara antes
# que "KGS", "KGS" nunca matchearía completo.
_ALIAS = sorted(_MAPA, key=len, reverse=True)
_ALIAS_RE = "|".join(re.escape(a) for a in _ALIAS if a not in ("media docena",))

_NUM = r"(\d+(?:[.,]\d+)?)"
# Multipack: "PACK X 6 X 473 ML", "6 X 473ML", "3X1 LT"
#
# El (?<![A-Z0-9]) del principio es la parte importante y costó dos intentos:
# los fideos se codifican con el número de corte pegado a una letra
# ("TALLARIN N5 X500G", "TIRABUZON N28 X500G"). Sin ese lookbehind, el "28"
# de "N28" se leía como multiplicador y daba 28 x 500 g = 14 kg, con lo que
# el precio por kilo quedaba 28 veces más barato de lo real.
# Y no alcanza con excluir letras: con (?<![A-Z]) el motor bloqueaba el "2" de
# "N28" pero arrancaba desde el "8", dando 8 x 500 g = 4 kg. Hay que excluir
# también dígitos para no entrar por la mitad de un número.
RE_MULTI = re.compile(rf"(?<![A-Z0-9]){_NUM}\s*[xX*]\s*{_NUM}\s*({_ALIAS_RE})(?![A-Z])", re.I)
# Simple: "900 ML", "1KG", "X 1 KG"
RE_SIMPLE = re.compile(rf"{_NUM}\s*({_ALIAS_RE})(?![A-Z])", re.I)
# Venta a granel sin número: "POR KG", "AL KILO", "X KG"
RE_GRANEL = re.compile(rf"\b(?:POR|AL|X|PRECIO)\s+({_ALIAS_RE})(?![A-Z])", re.I)
# Palabras que implican cantidad sin número
RE_PALABRA = re.compile(r"\b(DOCENA|MEDIA DOCENA|UNIDAD)\b", re.I)


def _a_float(s: str) -> float:
    return float(s.replace(",", "."))


def parsear(desc: str) -> tuple[float, str] | tuple[None, None]:
    """Devuelve (cantidad_base, unidad_base) o (None, None) si no puede.

    Cuando hay varios tamaños en la descripción se queda con el ÚLTIMO: las
    cadenas ponen el contenido al final ("YOGUR FRUTILLA 0% 1 LT"), mientras que
    los números del principio suelen ser parte del nombre comercial ("HARINA 000").
    """
    if not isinstance(desc, str) or not desc.strip():
        return None, None
    d = desc.upper()

    # 1) Multipack primero: es más específico y contiene al patrón simple.
    #    Acoto el multiplicador a 2..100 porque el patrón matchea de más:
    #    "HARINA 000 X 1 KG" se leía como 000 x 1 = 0 kg. Un multiplicador de 0
    #    o de 1 no es un multipack, es parte del nombre del producto.
    m = None
    for cand in RE_MULTI.finditer(d):
        mult = _a_float(cand.group(1))
        if 2 <= mult <= 100 and _a_float(cand.group(2)) > 0:
            m = cand
    if m:
        base = _MAPA.get(_limpiar(m.group(3)))
        if base:
            cant = _a_float(m.group(1)) * _a_float(m.group(2)) * base[1]
            if cant > 0:
                return cant, base[0]

    # 2) Tamaño simple, el último de la cadena.
    m = None
    for m in RE_SIMPLE.finditer(d):
        pass
    if m:
        base = _MAPA.get(_limpiar(m.group(2)))
        if base:
            cant = _a_float(m.group(1)) * base[1]
            if cant > 0:
                return cant, base[0]

    # 3) Granel: "POR KG" significa que el precio ya es por kilo.
    m = RE_GRANEL.search(d)
    if m:
        base = _MAPA.get(_limpiar(m.group(1)))
        if base:
            return base[1], base[0]

    # 4) Palabras sin número.
    m = RE_PALABRA.search(d)
    if m:
        base = _MAPA.get(_limpiar(m.group(1)))
        if base:
            return base[1], base[0]

    return None, None


def parsear_series(desc: pd.Series) -> pd.DataFrame:
    """Versión vectorizada por cache: hay ~83.000 descripciones únicas contra
    14,5 millones de filas, así que parsear una vez por texto único y mapear es
    dos órdenes de magnitud más rápido que aplicar la regex fila por fila."""
    unicas = pd.Series(desc.dropna().unique())
    tabla = {u: parsear(u) for u in unicas}
    res = desc.map(tabla)
    return pd.DataFrame({
        "cantidad_desc": res.map(lambda t: t[0] if isinstance(t, tuple) else None),
        "unidad_desc": res.map(lambda t: t[1] if isinstance(t, tuple) else None),
    }, index=desc.index)


# --- Autotest -----------------------------------------------------------------
CASOS = [
    ("ACEITE GIRASOL 900 ML", 0.9, "l"),
    ("ACEITE OLIVA CAÑUELAS EXTRA VIRGEN SUAVE PET 500 ML", 0.5, "l"),
    ("FIDEO GUISERO 500 GR", 0.5, "kg"),
    ("HARINA 000 X 1 KG", 1.0, "kg"),          # el "000" no es multiplicador
    ("HARINA 0000 X 1 KG", 1.0, "kg"),
    ("YOGUR PACK 2 X 1 L", 2.0, "l"),          # este sí es multipack
    ("GASEOSA 6 X 500 ML", 3.0, "l"),
    # El numero de corte del fideo NO es un multiplicador (bug real, 2026-07-24)
    ("FIDEOS MATARAZZO TALLARIN N5 X500G PAQ-500-GR.", 0.5, "kg"),
    ("FIDEOS LUCCHETTI TIRABUZON N28 X500G", 0.5, "kg"),
    ("FIDEOS MATARAZZO PENNE RIGATE N45 X500G PAQ-0.5-KG", 0.5, "kg"),
    ("FIDEOS MOSTACHOL BULNEZ PAQUETE X 500 GRS", 0.5, "kg"),
    ("FIDEOS SECOS PAMPERITOS BULNEZ 500 GRS", 0.5, "kg"),
    ("ARROZ LARGO FINO 1KG", 1.0, "kg"),
    ("GASEOSA COLA 2.25 LTS", 2.25, "l"),
    ("GASEOSA COLA 2,25 LTS", 2.25, "l"),
    ("CERVEZA PACK X 6 X 473 ML", 2.838, "l"),
    ("CERVEZA RUBIA BARRIL 50 LTS", 50.0, "l"),
    ("PAPA NEGRA POR KG", 1.0, "kg"),
    ("CARNE PICADA COMUN POR KG", 1.0, "kg"),
    ("HUEVO BLANCO DOCENA", 12.0, "un"),
    ("PAPEL HIGIENICO 4 UNIDADES", 4.0, "un"),
    ("LECHE ENTERA LA SERENISIMA SACHET 1L", 1.0, "l"),
    ("MANTECA 200 GR", 0.2, "kg"),
    ("CREMA DENTAL 90 GR", 0.09, "kg"),
    ("YERBA MATE ELABORADA 1 KG", 1.0, "kg"),
    ("PRESERVATIVOS", None, None),
    ("FIBRA ESPONJA LISA TASK", None, None),
    ("", None, None),
]

if __name__ == "__main__":
    fallos = 0
    for desc, cant_esp, uni_esp in CASOS:
        c, u = parsear(desc)
        ok = (u == uni_esp) and (c is None if cant_esp is None else abs(c - cant_esp) < 1e-6)
        if not ok:
            fallos += 1
        print(f"{'OK  ' if ok else 'FALLA'} {desc[:52]:<52} -> {c} {u}"
              + ("" if ok else f"   (esperaba {cant_esp} {uni_esp})"))
    print(f"\n{len(CASOS) - fallos}/{len(CASOS)} casos correctos")
    raise SystemExit(1 if fallos else 0)
