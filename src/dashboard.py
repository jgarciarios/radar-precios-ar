"""Genera el dashboard interactivo: un único HTML autocontenido.

    python -m src.dashboard

Salida: reports/dashboard.html

Por qué un HTML y no Power BI
-----------------------------
El dashboard es parte del portfolio: tiene que abrirse con un clic, sin cuenta
ni instalación. Un .pbix requiere Power BI Desktop (que no corre en macOS) y
compartir desde el servicio gratuito exige que el otro tenga cuenta. Un HTML se
publica en GitHub Pages y se ve desde cualquier navegador, incluso el celular.

El archivo lleva los datos adentro (JSON embebido), así que funciona offline y
no depende de ningún servidor.
"""
from __future__ import annotations

import json

import pandas as pd

from src import config as cfg
from src.utils import get_logger

log = get_logger("dashboard")
SALIDA = cfg.REPORTS / "dashboard.html"
# index.html en la raíz: da una URL corta (jgarciarios.github.io/radar-precios-ar/)
# y evita que el link termine en ".html", que es lo que hace que LinkedIn lo
# rechace como "enlace no válido".
INDICE = cfg.ROOT / "index.html"

REDIRECT = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Radar de Precios Argentina</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="Radar de Precios Argentina">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{base}/reports/figs/02_canasta_escenarios.png">
<meta property="og:url" content="{base}/">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url=reports/dashboard.html">
<link rel="canonical" href="{base}/reports/dashboard.html">
</head><body style="font-family:system-ui;padding:40px">
<p>Redirigiendo al <a href="reports/dashboard.html">dashboard</a>...</p>
</body></html>
"""


def _sanear(o):
    """Deja el objeto listo para JSON estricto.

    NaN e Infinity son literales válidos de JavaScript pero NO son JSON válido,
    y numpy los produce todo el tiempo. Si quedan adentro, JSON.parse tira una
    excepción y la página entera se queda en blanco. Se convierten a null.
    """
    import math
    if isinstance(o, dict):
        return {k: _sanear(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanear(v) for v in o]
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if hasattr(o, "item"):          # numpy int64 / float64 / bool_
        return _sanear(o.item())
    if o is None or isinstance(o, (str, int, bool)):
        return o
    return str(o)


def _leer(nombre: str) -> pd.DataFrame:
    p = cfg.PROCESSED / f"{nombre}.csv"
    if not p.exists():
        raise SystemExit(f"Falta {p}. Corré `python -m src.transform` primero.")
    df = pd.read_csv(p)
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def _calidad() -> pd.DataFrame:
    p = cfg.INTERIM / "_calidad.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def armar_datos() -> dict:
    disp = _leer("fact_dispersion")
    canasta = _leer("fact_canasta")
    rank = _leer("fact_ranking_cadenas")
    precio = _leer("fact_precio_item")
    dim = _leer("dim_item")
    cal = _calidad()

    ult = disp["fecha"].max()
    disp_u = disp[disp["fecha"] == ult]
    can_dia = canasta.groupby("fecha")[
        ["canasta_optima", "canasta_tipica", "canasta_peor"]].mean()

    # --- KPIs -----------------------------------------------------------------
    kpis = {
        "gap_mediano": round(float(disp_u["gap_pct"].median()), 1),
        "canasta_tipica": float(can_dia["canasta_tipica"].iloc[-1]),
        "ahorro": float(can_dia["canasta_tipica"].iloc[-1] - can_dia["canasta_optima"].iloc[-1]),
        "ahorro_pct": round(100 * (1 - can_dia["canasta_optima"].iloc[-1]
                                   / can_dia["canasta_tipica"].iloc[-1]), 1),
        "var_periodo": round(100 * (can_dia["canasta_tipica"].iloc[-1]
                                    / can_dia["canasta_tipica"].iloc[0] - 1), 1),
        "dias": int(canasta["fecha"].nunique()),
        "desde": canasta["fecha"].min().strftime("%d/%m/%Y"),
        "hasta": canasta["fecha"].max().strftime("%d/%m/%Y"),
    }
    if not cal.empty:
        kpis |= {
            "filas_crudas": int(cal["filas_crudas"].sum()),
            "cadenas": int(cal["cadenas"].max()),
            "sucursales": int(cal["sucursales"].max()),
            "eans": int(cal["eans_unicos"].max()),
            "pct_descartado": round(float(
                100 * (1 - cal["filas_finales"].sum() / cal["filas_crudas"].sum())), 2),
        }
        if "pct_fuentes_discrepan" in cal.columns:
            kpis["discrepancia"] = round(float(cal["pct_fuentes_discrepan"].mean()), 1)

    # --- Series ---------------------------------------------------------------
    unidades = dict(zip(dim["item"], dim["unidad_base"]))

    dispersion_items = (
        disp_u.groupby(["categoria", "item"])
        .agg(gap=("gap_pct", "median"), pmin=("precio_min", "median"),
             pmax=("precio_max", "median"), provincias=("provincia", "nunique"))
        .reset_index().sort_values("gap", ascending=False)
    )
    dispersion_items["unidad"] = dispersion_items["item"].map(unidades)

    ranking = (rank[rank["fecha"] == rank["fecha"].max()]
               .groupby("cadena")
               .agg(indice=("indice_vs_mercado", "median"),
                    items=("items", "sum"), provincias=("provincia", "nunique"))
               .reset_index().sort_values("indice"))

    provincias = (canasta[canasta["fecha"] == canasta["fecha"].max()]
                  .groupby("provincia")["canasta_tipica"].mean()
                  .reset_index().sort_values("canasta_tipica"))

    # Detalle para el explorador: item x provincia x cadena más barata/cara
    detalle = disp_u[["item", "categoria", "provincia", "precio_min", "precio_med",
                      "precio_max", "gap_pct", "cadena_mas_barata",
                      "cadena_mas_cara", "cadenas_comparadas"]].copy()
    detalle["unidad"] = detalle["item"].map(unidades)
    detalle = detalle.sort_values("gap_pct", ascending=False).round(1)
    # Los NaN de pandas se serializan como NaN, que en JS renderiza literalmente
    # "NaN" en la tabla. Mejor un guion que un valor que parece un error.
    for c in ("cadena_mas_barata", "cadena_mas_cara", "unidad", "categoria"):
        detalle[c] = detalle[c].fillna("—")
    dispersion_items["unidad"] = dispersion_items["unidad"].fillna("—")

    return {
        "kpis": kpis,
        "canasta": {
            "fechas": [d.strftime("%d/%m") for d in can_dia.index],
            "optima": can_dia["canasta_optima"].round(0).tolist(),
            "tipica": can_dia["canasta_tipica"].round(0).tolist(),
            "peor": can_dia["canasta_peor"].round(0).tolist(),
        },
        "dispersion": dispersion_items.round(1).to_dict("records"),
        "ranking": ranking.round(1).to_dict("records"),
        "provincias": provincias.round(0).to_dict("records"),
        "detalle": detalle.to_dict("records"),
        "categorias": sorted(disp_u["categoria"].dropna().unique().tolist()),
        "prov_lista": sorted(disp_u["provincia"].dropna().unique().tolist()),
    }


PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radar de Precios Argentina — el mismo producto, hasta 47% más caro</title>
<meta name="description" content="__DESC__">
<meta property="og:type" content="website">
<meta property="og:title" content="Radar de Precios Argentina">
<meta property="og:description" content="__DESC__">
<meta property="og:image" content="__BASE__/reports/figs/02_canasta_escenarios.png">
<meta property="og:url" content="__BASE__/">
<meta name="twitter:card" content="summary_large_image">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script id="datos" type="application/json">__DATOS__</script>
<style>
  :root {
    --azul:#1f4e79; --rojo:#c0392b; --verde:#27ae60; --gris:#6b7280;
    --fondo:#f7f8fa; --card:#fff; --borde:#e4e7ec; --texto:#1a1d23;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--fondo); color:var(--texto);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  header { background:var(--azul); color:#fff; padding:28px 32px; }
  header h1 { margin:0 0 6px; font-size:26px; letter-spacing:-.4px; }
  header p { margin:0; opacity:.85; font-size:14px; }
  main { max-width:1240px; margin:0 auto; padding:24px 20px 60px; }
  .kpis { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(178px,1fr));
          margin:-52px 0 26px; }
  .kpi { background:var(--card); border:1px solid var(--borde); border-radius:10px;
         padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
  .kpi .v { font-size:27px; font-weight:700; letter-spacing:-.6px; }
  .kpi .l { font-size:12px; color:var(--gris); margin-top:3px; line-height:1.35; }
  .card { background:var(--card); border:1px solid var(--borde); border-radius:10px;
          padding:20px 22px; margin-bottom:20px; }
  .card h2 { margin:0 0 4px; font-size:17px; }
  .card .sub { margin:0 0 16px; font-size:13px; color:var(--gris); }
  .grid2 { display:grid; gap:20px; grid-template-columns:1fr 1fr; }
  @media(max-width:900px){ .grid2{grid-template-columns:1fr;} }
  select, input { padding:7px 10px; border:1px solid var(--borde); border-radius:6px;
                  font-size:13px; background:#fff; color:var(--texto); }
  .filtros { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; padding:9px 8px; border-bottom:2px solid var(--borde);
       font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:var(--gris);
       cursor:pointer; user-select:none; white-space:nowrap; }
  th:hover { color:var(--azul); }
  td { padding:8px; border-bottom:1px solid #f0f1f4; }
  tbody tr:hover { background:#f9fafb; }
  .num { text-align:right; font-variant-numeric:tabular-nums; }
  .badge { display:inline-block; padding:2px 7px; border-radius:20px; font-size:11px;
           font-weight:600; }
  .alto { background:#fdecea; color:var(--rojo); }
  .medio { background:#fff5e6; color:#b26a00; }
  .bajo { background:#eaf7ef; color:var(--verde); }
  .nota { background:#fffdf5; border-left:3px solid #e0b34d; padding:14px 16px;
          font-size:13px; line-height:1.6; border-radius:0 6px 6px 0; }
  .nota ul { margin:8px 0 0; padding-left:18px; }
  .nota li { margin-bottom:5px; }
  footer { text-align:center; font-size:12px; color:var(--gris); padding:24px; }
  .chartbox { position:relative; height:320px; }
</style>
</head>
<body>
<header>
  <h1>Radar de Precios Argentina</h1>
  <p>Base SEPA · Secretaría de Comercio Interior · __DESDE__ al __HASTA__ (__DIAS__ días)</p>
</header>

<main>
  <div class="kpis" id="kpis"></div>

  <div class="card">
    <h2>Costo mensual de la canasta según dónde compres</h2>
    <p class="sub">Canasta de __NITEMS__ productos de consumo masivo para un hogar de 4 personas.
       Precios normalizados por kilo, litro o unidad.</p>
    <div class="chartbox"><canvas id="c_canasta"></canvas></div>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Qué tan cara es cada cadena</h2>
      <p class="sub">Índice 100 = mediana del mercado en la misma provincia y el mismo día.</p>
      <div class="chartbox"><canvas id="c_cadenas"></canvas></div>
    </div>
    <div class="card">
      <h2>Costo de la canasta por provincia</h2>
      <p class="sub">Solo provincias con al menos 3 cadenas comparables.</p>
      <div class="chartbox"><canvas id="c_provincias"></canvas></div>
    </div>
  </div>

  <div class="card">
    <h2>Dispersión por producto</h2>
    <p class="sub">Cuánto más caro está el mismo producto en la cadena más cara
       respecto de la más barata, dentro de la misma provincia.</p>
    <div class="chartbox" style="height:420px"><canvas id="c_items"></canvas></div>
  </div>

  <div class="card">
    <h2>Explorador</h2>
    <p class="sub">Dónde comprás más barato cada producto, provincia por provincia.
       Hacé clic en los encabezados para ordenar.</p>
    <div class="filtros">
      <select id="f_prov"><option value="">Todas las provincias</option></select>
      <select id="f_cat"><option value="">Todas las categorías</option></select>
      <input id="f_txt" placeholder="Buscar producto..." style="flex:1;min-width:160px">
      <span id="f_info" style="font-size:12px;color:var(--gris)"></span>
    </div>
    <div style="max-height:460px;overflow:auto">
      <table id="tabla">
        <thead><tr>
          <th data-k="item">Producto</th>
          <th data-k="provincia">Provincia</th>
          <th data-k="precio_min" class="num">Más barato</th>
          <th data-k="precio_max" class="num">Más caro</th>
          <th data-k="gap_pct" class="num">Brecha</th>
          <th data-k="cadena_mas_barata">Dónde conviene</th>
          <th data-k="cadenas_comparadas" class="num">Cadenas</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Metodología y limitaciones</h2>
    <div class="nota">
      <strong>Leé esto antes de citar los números.</strong>
      <ul>
        <li><strong>Precios normalizados.</strong> Se compara precio por kilo, litro o
            unidad, no precio de envase. Sin esto, "la cerveza más barata" sería una
            lata de 269 ml y "la más cara" un barril de 50 litros.</li>
        <li><strong>Solo grandes superficies.</strong> SEPA no incluye almacenes de
            barrio, ferias ni mayoristas, que es donde compra buena parte del país.</li>
        <li><strong>Precios de lista.</strong> Sin promociones ni descuentos bancarios,
            que en Argentina mueven el precio efectivo más que la lista.</li>
        <li><strong>Los productos se identifican por patrones de texto</strong> sobre la
            descripción. Es una aproximación: un item puede capturar presentaciones
            distintas del mismo producto.</li>
        <li><strong>La muestra cambia día a día.</strong> Las cadenas entran y salen del
            reporte, así que una variación entre fechas puede reflejar composición de la
            muestra y no un cambio real de precios.</li>
        <li><strong>Las cantidades mensuales del hogar tipo son un supuesto propio</strong>,
            editable en <code>src/canasta.py</code>. No son las del INDEC.</li>
      </ul>
    </div>
  </div>
</main>

<footer>
  Generado con Python, DuckDB y Chart.js · Datos: Precios Claros – Base SEPA
</footer>

<div id="error" style="display:none;margin:20px;padding:16px;background:#fdecea;
     border-left:4px solid #c0392b;border-radius:0 6px 6px 0;font-size:14px"></div>
<script>
function falla(e){
  // Antes esto se quedaba en blanco y no había forma de saber por qué.
  const d = document.getElementById('error');
  d.style.display = 'block';
  d.innerHTML = '<strong>No se pudo renderizar el dashboard.</strong><br>' +
    'Error: ' + e.message + '<br><span style="color:#6b7280">' +
    'Si dice "Chart is not defined", no hay conexión a internet y no cargó Chart.js. ' +
    'Si es otra cosa, mirá la consola del navegador.</span>';
  console.error(e);
}
let D;
try { D = JSON.parse(document.getElementById('datos').textContent); }
catch (e) { falla(e); throw e; }
try {
const AZUL='#1f4e79', ROJO='#c0392b', VERDE='#27ae60', GRIS='#9aa1ac';
const pesos = v => '$' + Math.round(v).toLocaleString('es-AR');
const K = D.kpis;

// ---------- KPIs ----------
const tarjetas = [
  [K.gap_mediano + '%', 'Diferencia mediana entre la cadena más cara y la más barata, mismo producto y provincia'],
  [pesos(K.ahorro), 'Se ahorra por mes comprando cada producto donde está más barato (' + K.ahorro_pct + '% de la canasta)'],
  [pesos(K.canasta_tipica), 'Canasta mensual del hogar tipo a precio mediano de mercado'],
  [(K.var_periodo > 0 ? '+' : '') + K.var_periodo + '%', 'Variación de la canasta en los ' + K.dias + ' días analizados'],
];
if (K.filas_crudas) tarjetas.push(
  [(K.filas_crudas/1e6).toFixed(1) + 'M', 'Registros de precios procesados · ' + K.cadenas + ' cadenas · ' + K.sucursales.toLocaleString('es-AR') + ' sucursales']);
if (K.discrepancia) tarjetas.push(
  [K.discrepancia + '%', 'De los productos: las dos fuentes oficiales del tamaño del envase se contradicen entre sí']);
document.getElementById('kpis').innerHTML = tarjetas
  .map(([v,l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

// ---------- Gráficos ----------
const base = {responsive:true, maintainAspectRatio:false,
  plugins:{legend:{labels:{boxWidth:12,font:{size:11}}}}};

new Chart(document.getElementById('c_canasta'), {
  type:'line',
  data:{labels:D.canasta.fechas, datasets:[
    {label:'Comprando siempre en la más cara', data:D.canasta.peor, borderColor:ROJO, backgroundColor:ROJO, tension:.25, pointRadius:2},
    {label:'A precio mediano de mercado', data:D.canasta.tipica, borderColor:AZUL, backgroundColor:AZUL, borderWidth:3, tension:.25, pointRadius:2},
    {label:'Comprando cada producto en la más barata', data:D.canasta.optima, borderColor:VERDE, backgroundColor:VERDE, tension:.25, pointRadius:2}]},
  options:{...base, scales:{y:{ticks:{callback:pesos}}}}
});

new Chart(document.getElementById('c_cadenas'), {
  type:'bar',
  data:{labels:D.ranking.map(r=>r.cadena),
    datasets:[{data:D.ranking.map(r=>r.indice),
      backgroundColor:D.ranking.map(r=>r.indice>100?ROJO:VERDE)}]},
  options:{...base, indexAxis:'y', plugins:{legend:{display:false},
    tooltip:{callbacks:{label:c=>'Índice ' + c.raw + ' (100 = mercado)'}}},
    scales:{x:{min:Math.min(...D.ranking.map(r=>r.indice))-6,
                max:Math.max(...D.ranking.map(r=>r.indice))+6}}}
});

new Chart(document.getElementById('c_provincias'), {
  type:'bar',
  data:{labels:D.provincias.map(p=>p.provincia),
    datasets:[{data:D.provincias.map(p=>p.canasta_tipica), backgroundColor:AZUL}]},
  options:{...base, indexAxis:'y', plugins:{legend:{display:false},
    tooltip:{callbacks:{label:c=>pesos(c.raw) + ' por mes'}}},
    scales:{x:{ticks:{callback:pesos}}}}
});

const top = D.dispersion.slice(0,18).reverse();
new Chart(document.getElementById('c_items'), {
  type:'bar',
  data:{labels:top.map(d=>d.item), datasets:[{data:top.map(d=>d.gap), backgroundColor:AZUL}]},
  options:{...base, indexAxis:'y', plugins:{legend:{display:false},
    tooltip:{callbacks:{label:c=>{const d=top[c.dataIndex];
      return [c.raw+'% de diferencia', pesos(d.pmin)+' a '+pesos(d.pmax)+' por '+d.unidad];}}}},
    scales:{x:{title:{display:true,text:'Diferencia entre la cadena más cara y la más barata (%)'}}}}
});

// ---------- Explorador ----------
const tb = document.querySelector('#tabla tbody');
const fp = document.getElementById('f_prov'), fc = document.getElementById('f_cat'),
      ft = document.getElementById('f_txt'), fi = document.getElementById('f_info');
D.prov_lista.forEach(p => fp.add(new Option(p,p)));
D.categorias.forEach(c => fc.add(new Option(c,c)));
let orden = {k:'gap_pct', asc:false};

function clase(g){ return g>60?'alto' : g>30?'medio' : 'bajo'; }

function pintar(){
  const txt = ft.value.trim().toLowerCase();
  let f = D.detalle.filter(r =>
    (!fp.value || r.provincia===fp.value) &&
    (!fc.value || r.categoria===fc.value) &&
    (!txt || r.item.toLowerCase().includes(txt)));
  f.sort((a,b)=>{ const x=a[orden.k], y=b[orden.k];
    const c = (typeof x==='number') ? x-y : String(x).localeCompare(String(y));
    return orden.asc ? c : -c; });
  fi.textContent = f.length + ' combinaciones producto–provincia';
  tb.innerHTML = f.slice(0,400).map(r=>`<tr>
    <td><strong>${r.item}</strong> <span style="color:var(--gris)">/${r.unidad}</span></td>
    <td>${r.provincia}</td>
    <td class="num">${pesos(r.precio_min)}</td>
    <td class="num">${pesos(r.precio_max)}</td>
    <td class="num"><span class="badge ${clase(r.gap_pct)}">${r.gap_pct}%</span></td>
    <td>${r.cadena_mas_barata}</td>
    <td class="num">${r.cadenas_comparadas}</td></tr>`).join('');
}
document.querySelectorAll('#tabla th').forEach(th => th.onclick = () => {
  const k = th.dataset.k;
  orden = {k, asc: orden.k===k ? !orden.asc : false};
  pintar();
});
[fp,fc].forEach(e => e.onchange = pintar);
ft.oninput = pintar;
pintar();
} catch (e) { falla(e); }
</script>
</body>
</html>"""


def run() -> None:
    d = armar_datos()
    # allow_nan=False obliga a que cualquier NaN que se haya escapado del
    # saneo explote acá y no en silencio dentro del navegador.
    datos = json.dumps(_sanear(d), ensure_ascii=False, allow_nan=False)
    # "</script>" adentro del bloque lo cerraría antes de tiempo; y U+2028/2029
    # son saltos de línea invisibles que rompen el parseo en navegadores viejos.
    datos = (datos.replace("</", "<\\/")
                  .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    k = d["kpis"]
    desc = (f"El mismo producto cuesta hasta {k['gap_mediano']}% más caro según la cadena. "
            f"Análisis de {k.get('filas_crudas', 0)/1e6:.0f} millones de precios de "
            f"supermercados argentinos (base SEPA).")
    html = (PLANTILLA
            .replace("__DATOS__", datos)
            .replace("__DESC__", desc)
            .replace("__BASE__", cfg.SITIO_BASE)
            .replace("__NITEMS__", str(len(d["dispersion"]) or 27))
            .replace("__DESDE__", d["kpis"]["desde"])
            .replace("__HASTA__", d["kpis"]["hasta"])
            .replace("__DIAS__", str(d["kpis"]["dias"])))
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(html, encoding="utf-8")
    INDICE.write_text(REDIRECT.format(desc=desc, base=cfg.SITIO_BASE), encoding="utf-8")
    log.info("Índice:    %s  ->  %s/", INDICE, cfg.SITIO_BASE)
    log.info("Dashboard: %s (%.1f MB)", SALIDA, SALIDA.stat().st_size / 1e6)
    log.info("Abrilo con:  open %s", SALIDA)


if __name__ == "__main__":
    run()
