"""Genera datos sintéticos con el formato (y la mugre) de SEPA.

Sirve para dos cosas:
1. Probar el pipeline entero sin bajar 20 GB.
2. Que cualquiera pueda clonar el repo y correrlo en 30 segundos.

Uso:
    python -m tests.make_fixture --dias 7 --sucursales 40
"""
from __future__ import annotations

import argparse
import datetime as dt
import random


import numpy as np
import pandas as pd

from src import config as cfg

random.seed(42)
np.random.seed(42)

CADENAS = [
    ("001", "COTO CICSA", "COTO"),
    ("002", "JUMBO RETAIL ARGENTINA S.A.", "JUMBO"),
    ("003", "DIA ARGENTINA S.A.", "DIA"),
    ("004", "CARREFOUR ARGENTINA", "CARREFOUR"),
    ("005", "LA ANONIMA S.A.", "LA ANONIMA"),
    ("006", "CHANGOMAS", "CHANGOMAS"),
]
PROVINCIAS = ["AR-C", "AR-B", "AR-S", "AR-X", "AR-M", "AR-T"]
PROV_NOMBRE = {
    "AR-C": "CIUDAD AUTONOMA DE BUENOS AIRES", "AR-B": "BUENOS AIRES",
    "AR-S": "SANTA FE", "AR-X": "CORDOBA", "AR-M": "MENDOZA", "AR-T": "TUCUMAN",
}

# (descripcion, marca, precio_del_envase, cantidad, unidad)
# Las unidades estan escritas de formas distintas a proposito ('GR', 'gr.',
# 'cm3', 'LTS', 'unidad'), como hacen las cadenas reales.
PRODUCTOS = [
    ("LECHE ENTERA LA SERENISIMA SACHET 1L", "LA SERENISIMA", 1450, 1, "l"),
    ("LECHE ENTERA ILOLAY 1L", "ILOLAY", 1380, 1000, "cm3"),
    ("LECHE ENTERA SANCOR BOTELLA 3 LTS", "SANCOR", 4050, 3, "LTS"),
    ("YOGUR BEBIBLE FRUTILLA 1L", "SANCOR", 2100, 1, "lt"),
    ("QUESO CREMOSO POR KG", "PUNTA DEL AGUA", 9800, 1, "kg"),
    ("MANTECA 200 GR", "SANCOR", 2650, 200, "GR"),
    ("PAN LACTAL BLANCO 390G", "BIMBO", 2890, 390, "gr."),
    ("HARINA 000 X 1 KG", "PUREZA", 1120, 1, "Kg"),
    ("FIDEO GUISERO 500 GR", "MATARAZZO", 1340, 500, "gr"),
    ("ARROZ LARGO FINO 1KG", "GALLO", 2250, 1000, "grs"),
    ("ACEITE GIRASOL 900 ML", "NATURA", 3100, 900, "ml"),
    ("AZUCAR COMUN TIPO A 1KG", "LEDESMA", 1580, 1, "kg"),
    ("YERBA MATE ELABORADA 1 KG", "TARAGUI", 5400, 1, "kg"),
    ("YERBA MATE ELABORADA 500 GR", "TARAGUI", 2820, 500, "gr"),
    ("CAFE MOLIDO TOSTADO 500G", "LA VIRGINIA", 8900, 500, "gr"),
    ("PURE DE TOMATE 520 GR", "ARCOR", 980, 520, "gr"),
    ("ARVEJAS REMOJADAS 350G", "ARCOR", 890, 350, "gr"),
    ("ATUN AL NATURAL 170 GR", "GOMES DA COSTA", 3450, 170, "gr"),
    ("HUEVO BLANCO DOCENA", "GRANJA", 3900, 1, "docena"),
    ("CARNE PICADA COMUN POR KG", "S/M", 7800, 1, "kg"),
    ("POLLO ENTERO FRESCO POR KG", "S/M", 4200, 1, "kg"),
    ("PAPA NEGRA POR KG", "S/M", 1250, 1, "kg"),
    ("PAPA NEGRA BOLSA 5 KG", "S/M", 5600, 5, "kg"),
    ("BANANA ECUADOR POR KG", "S/M", 2400, 1, "kg"),
    ("GASEOSA COLA 2.25 LTS", "COCA COLA", 3600, 2.25, "l"),
    ("AGUA MINERAL SIN GAS 2L", "VILLA DEL SUR", 1450, 2, "l"),
    ("CERVEZA RUBIA 1 LT", "QUILMES", 2400, 1, "l"),
    ("CERVEZA RUBIA LATA 269 ML", "QUILMES", 780, 269, "ml"),
    ("CERVEZA RUBIA BARRIL 50 LTS", "QUILMES", 118000, 50, "lts"),
    ("DETERGENTE LIQUIDO 750ML", "MAGISTRAL", 2900, 750, "ml"),
    ("LAVANDINA COMUN 1 LT", "AYUDIN", 1150, 1, "l"),
    ("JABON EN POLVO 800 GR", "ALA", 4300, 800, "gr"),
    ("PAPEL HIGIENICO 4 UNIDADES", "HIGIENOL", 3800, 4, "unidad"),
    ("SHAMPOO 350 ML", "SEDAL", 4900, 350, "ml"),
    ("CREMA DENTAL 90 GR", "COLGATE", 2300, 90, "gr"),
    # Trampas deliberadas: misma palabra, presentacion incomparable.
    ("BANANA UNIDAD", "S/M", 25, 1, "unidad"),
    # Ruido: fuera de la canasta
    ("TELEVISOR LED 50 PULGADAS 4K", "SAMSUNG", 890000, 1, "unidad"),
    ("CEMENTO PORTLAND 50KG", "LOMA NEGRA", 12500, 50, "kg"),
    ("ALFAJOR TRIPLE CHOCOLATE", "JORGITO", 950, 70, "gr"),
    # Unidad que el mapeo NO conoce, para probar el diagnostico
    ("ESCOBA CERDA PLASTICA", "GENERICA", 8900, 1, "pieza"),
]

FACTOR_ITEM = {
    (bandera, i): round(random.lognormvariate(0, 0.07), 4)
    for _, _, bandera in CADENAS
    for i in range(len(PRODUCTOS))
}


def _ean(i: int) -> str:
    return f"779{i:010d}"


def generar(dias: int, n_sucursales: int) -> None:
    hoy = dt.date.today()
    # Inflación sintética ~2.5% mensual + ruido diario
    for d in range(dias):
        fecha = hoy - dt.timedelta(days=dias - 1 - d)
        drift = (1.025) ** (d / 30)
        carpeta = cfg.RAW / f"{fecha:%Y-%m-%d}"

        for id_com, razon, bandera in CADENAS:
            sub = carpeta / f"sepa_{id_com}"
            sub.mkdir(parents=True, exist_ok=True)

            # nivel de precio propio de cada cadena (DIA barato, JUMBO caro)
            factor_cadena = {"DIA": 0.88, "CHANGOMAS": 0.92, "COTO": 0.99,
                             "LA ANONIMA": 1.04, "CARREFOUR": 1.06, "JUMBO": 1.14}[bandera]

            # comercio.csv
            pd.DataFrame([{
                "id_comercio": id_com, "id_bandera": "1",
                "comercio_cuit": f"30{id_com}12345{id_com[-1]}",
                "comercio_razon_social": razon,
                "comercio_bandera_nombre": bandera,
            }]).to_csv(sub / "comercio.csv", index=False, sep="|")

            # sucursales.csv
            sucs = []
            for s in range(n_sucursales // len(CADENAS)):
                prov = random.choice(PROVINCIAS)
                sucs.append({
                    "id_comercio": id_com, "id_bandera": "1", "id_sucursal": f"{s+1:03d}",
                    "sucursales_nombre": f"{bandera} SUC {s+1}",
                    "sucursales_tipo": "Supermercado",
                    "sucursales_provincia": prov,
                    "sucursales_localidad": PROV_NOMBRE[prov].title(),
                    "sucursales_latitud": round(-34.6 + random.uniform(-5, 5), 5),
                    "sucursales_longitud": round(-58.4 + random.uniform(-5, 5), 5),
                })
            pd.DataFrame(sucs).to_csv(sub / "sucursales.csv", index=False, sep="|")

            # productos.csv — acá metemos la mugre a propósito
            filas = []
            for suc in sucs:
                factor_suc = random.uniform(0.97, 1.03)
                for i, (desc, marca, base, cant, uni) in enumerate(PRODUCTOS):
                    if random.random() < 0.08:      # faltante de stock
                        continue
                    # Cada cadena tiene su propia política por producto: hay
                    # líderes de pérdida (leche barata para traer gente) y
                    # productos con margen alto. Sin esto todos los items dan
                    # la misma dispersión y el gráfico queda plano.
                    factor_item = FACTOR_ITEM[(bandera, i)]
                    p = base * drift * factor_cadena * factor_item * factor_suc \
                        * random.uniform(0.98, 1.02)

                    ean = _ean(i)
                    if random.random() < 0.01:      # EAN roto
                        ean = "0"
                    if random.random() < 0.005:     # precio 0 / negativo
                        p = 0
                    if random.random() < 0.004:     # coma decimal mal cargada
                        p *= 100

                    filas.append({
                        "id_comercio": id_com, "id_bandera": "1",
                        "id_sucursal": suc["id_sucursal"],
                        # Como en los archivos reales: el codigo de barras va
                        # en id_producto y productos_ean es la CANTIDAD de eans.
                        "id_producto": ean,
                        "productos_ean": 1,
                        "productos_descripcion": desc,
                        "productos_marca": marca,
                        "productos_cantidad_presentacion": cant,
                        "productos_unidad_medida_presentacion": uni,
                        # formato argentino: punto de miles, coma decimal
                        "productos_precio_lista": f"{p:,.2f}".replace(",", "@").replace(".", ",").replace("@", "."),
                        "productos_precio_referencia": "",
                    })

            df = pd.DataFrame(filas)
            # duplicados exactos (~2%)
            dupes = df.sample(frac=0.02, random_state=1)
            df = pd.concat([df, dupes], ignore_index=True)
            # header con acentos y mayúsculas, como aparece en algunos archivos
            df.columns = [c.replace("productos_descripcion", "Productos Descripción")
                          for c in df.columns]
            df.to_csv(sub / "productos.csv", index=False, sep="|")

        print(f"  fixture {fecha}  ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7)
    ap.add_argument("--sucursales", type=int, default=48)
    a = ap.parse_args()
    print(f"Generando fixture: {a.dias} días x {a.sucursales} sucursales")
    generar(a.dias, a.sucursales)
    print(f"\nListo. Ahora:\n  python -m src.clean --forzar\n  python -m src.transform")
