"""Genera las figuras del informe y del README a partir de data/processed/.

Uso:
    python -m src.figuras

Criterio de diseño: pocas figuras, cada una con un solo mensaje y el mensaje
escrito en el título. Un gráfico que necesita que lo expliques es un gráfico
que falló.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from src import config as cfg
from src.utils import get_logger

log = get_logger("figuras")
FIGS = cfg.REPORTS / "figs"

AZUL, ROJO, GRIS = "#1f4e79", "#c0392b", "#95a5a6"
plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "savefig.bbox": "tight",
    "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "axes.titlesize": 12,
    "axes.titleweight": "bold", "figure.facecolor": "white",
})


def _leer(nombre: str) -> pd.DataFrame:
    p = cfg.PROCESSED / f"{nombre}.csv"
    if not p.exists():
        raise SystemExit(f"Falta {p}. Corré `python -m src.transform` primero.")
    df = pd.read_csv(p)
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def fig_dispersion_items(n: int = 15) -> None:
    """Barras horizontales: cuánto más caro es el mismo producto según dónde compres."""
    d = _leer("fact_dispersion")
    ult = d[d.fecha == d.fecha.max()]
    top = (ult.groupby("item")["gap_pct"].median()
              .sort_values(ascending=False).head(n).iloc[::-1])

    fig, ax = plt.subplots(figsize=(9, 0.42 * len(top) + 1.4))
    ax.barh(top.index, top.values, color=AZUL)
    for y, v in enumerate(top.values):
        ax.text(v + 0.6, y, f"{v:.0f}%", va="center", fontsize=9, color="#333")
    ax.set_xlabel("Diferencia entre la cadena más cara y la más barata (%)")
    ax.set_title(f"El mismo producto, la misma provincia, hasta {top.max():.0f}% de diferencia")
    ax.set_xlim(0, top.max() * 1.15)
    fig.savefig(FIGS / "01_dispersion_items.png")
    plt.close(fig)
    log.info("01_dispersion_items.png")


def fig_canasta_escenarios() -> None:
    """Evolución del costo mensual de la canasta en 3 escenarios de compra."""
    c = _leer("fact_canasta").groupby("fecha")[
        ["canasta_optima", "canasta_tipica", "canasta_peor"]].mean()

    fig, ax = plt.subplots(figsize=(9.5, 5))
    ax.fill_between(c.index, c.canasta_optima, c.canasta_peor, color=GRIS, alpha=0.18,
                    label="Rango según dónde compres")
    ax.plot(c.index, c.canasta_peor, color=ROJO, lw=2, label="Comprando siempre en la más cara")
    ax.plot(c.index, c.canasta_tipica, color=AZUL, lw=2.5, label="A precio mediano de mercado")
    ax.plot(c.index, c.canasta_optima, color="#27ae60", lw=2, label="Comprando cada item en la más barata")

    brecha = c.canasta_tipica.iloc[-1] - c.canasta_optima.iloc[-1]
    ax.set_title(f"Canasta mensual del hogar tipo: elegir bien vale ${brecha:,.0f} por mes"
                 .replace(",", "."))
    ax.set_ylabel("Costo mensual ($)")
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}".replace(",", "."))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.set_ylim(c.canasta_optima.min() * 0.94, c.canasta_peor.max() * 1.04)
    ax.legend(frameon=False, fontsize=9, ncol=2, loc="upper center",
              bbox_to_anchor=(0.5, -0.12))
    fig.savefig(FIGS / "02_canasta_escenarios.png")
    plt.close(fig)
    log.info("02_canasta_escenarios.png")


def fig_ranking_cadenas() -> None:
    """Índice 100 = mediana del mercado. Arriba de 100 = más cara."""
    r = _leer("fact_ranking_cadenas")
    ult = r[r.fecha == r.fecha.max()]
    s = ult.groupby("cadena")["indice_vs_mercado"].median().sort_values()

    colores = [ROJO if v > 100 else "#27ae60" for v in s.values]
    fig, ax = plt.subplots(figsize=(9, 0.45 * len(s) + 1.6))
    ax.barh(s.index, s.values - 100, left=100, color=colores)
    ax.axvline(100, color="#333", lw=1)
    for y, v in enumerate(s.values):
        ax.text(v + (0.4 if v > 100 else -0.4), y, f"{v:.1f}",
                va="center", ha="left" if v > 100 else "right", fontsize=9)
    ax.set_xlabel("Índice de precios (100 = mediana del mercado)")
    ax.set_title(f"Entre la cadena más barata y la más cara hay "
                 f"{s.max() - s.min():.0f} puntos de diferencia")
    fig.savefig(FIGS / "03_ranking_cadenas.png")
    plt.close(fig)
    log.info("03_ranking_cadenas.png")


def fig_mapa_provincias() -> None:
    """Costo de la canasta por provincia, ordenado."""
    c = _leer("fact_canasta")
    ult = c[c.fecha == c.fecha.max()].groupby("provincia")["canasta_tipica"].mean().sort_values()
    if len(ult) < 2:
        log.warning("Pocas provincias, salteo el gráfico")
        return
    media = ult.mean()

    fig, ax = plt.subplots(figsize=(9, 0.42 * len(ult) + 1.6))
    ax.barh(ult.index, ult.values, color=[ROJO if v > media else AZUL for v in ult.values])
    ax.axvline(media, color="#333", ls="--", lw=1, label=f"Promedio nacional")
    ax.set_xlabel("Costo mensual de la canasta ($)")
    ax.xaxis.set_major_formatter(lambda v, _: f"${v:,.0f}".replace(",", "."))
    ax.set_title(f"La misma canasta cuesta {100*(ult.max()/ult.min()-1):.0f}% más "
                 f"en {ult.index[-1]} que en {ult.index[0]}")
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(FIGS / "04_canasta_provincias.png")
    plt.close(fig)
    log.info("04_canasta_provincias.png")


def fig_calidad() -> None:
    """Transparencia sobre la limpieza: qué se descartó y por qué."""
    p = cfg.INTERIM / "_calidad.csv"
    if not p.exists():
        return
    cal = pd.read_csv(p)
    cols = [c for c in cal.columns if c.startswith("desc_")]
    s = (100 * cal[cols].sum() / cal["filas_crudas"].sum()).sort_values()
    s.index = [i.replace("desc_", "").replace("_", " ") for i in s.index]

    fig, ax = plt.subplots(figsize=(8, 0.5 * len(s) + 1.6))
    ax.barh(s.index, s.values, color=GRIS)
    for y, v in enumerate(s.values):
        ax.text(v + 0.03, y, f"{v:.2f}%", va="center", fontsize=9)
    ax.set_xlabel("% de las filas crudas")
    ax.set_title(f"Limpieza: se descartó el {s.sum():.1f}% de los registros")
    fig.savefig(FIGS / "05_calidad_descartes.png")
    plt.close(fig)
    log.info("05_calidad_descartes.png")


def run() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    fig_dispersion_items()
    fig_canasta_escenarios()
    fig_ranking_cadenas()
    fig_mapa_provincias()
    fig_calidad()
    log.info("Figuras en %s", FIGS)


if __name__ == "__main__":
    run()
