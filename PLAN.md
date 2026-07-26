# Plan de ejecución — 10 días hábiles

> Este archivo es para vos, no para el reclutador. Borralo del repo público si querés.

## Antes de empezar

Escribí el pitch **primero**, con los números en blanco. Todo lo que hagas después tiene que servir para completarlo:

> "Descargué la base oficial SEPA: 12 millones de precios diarios de supermercados. Armé un pipeline que la normaliza y la deja consultable. Encontré que el mismo producto varía hasta ___% entre cadenas en la misma provincia, y que eso son $______ por mes para un hogar tipo. El dashboard te dice, por producto y región, dónde comprás más barato."

Si al día 10 no podés completar esa frase, el proyecto no está terminado — aunque el código sea hermoso.

---

## Día 1 — Reconocimiento

- [ ] `python -m tests.make_fixture` + correr el pipeline entero con datos sintéticos. Que ande de punta a punta antes de tocar datos reales.
- [ ] `python -m src.extract --listar` → ver qué días hay publicados.
- [ ] Descargar **2 días** reales. Solo dos. Abrir los CSV a mano y mirarlos.
- [ ] **Verificar los nombres de columna reales** contra `src/config.py`. El portal cambió el formato más de una vez; si algo no coincide, ajustá `PRODUCTOS_CORE` / `SUCURSALES_CORE`. `read_sepa_csv` te va a decir exactamente qué columnas encontró.
- [ ] Notebook 01, secciones 1 a 3.

**Salida del día:** sabés cuántas cadenas, sucursales y provincias hay, y el pipeline corre sobre datos reales.

## Día 2 — Calidad

- [ ] Notebook 02 completa.
- [ ] Ajustar umbrales en `config.py` según lo que veas (los que vienen son un punto de partida, no la verdad).
- [ ] Llenar la tabla de decisiones al final del notebook 02.

**Regla:** si una regla te borra más del 5% de la base, la regla está mal.

## Días 3–4 — Pipeline sólido

- [ ] Descargar 14–20 días (`--ultimos 20`). Ojo con el disco: usá `RADAR_DATA_DIR`.
- [ ] `python -m src.clean` sobre todo. Que no tire un solo error.
- [ ] Revisar `_calidad.csv`: ¿los descartes son estables entre días? Un día con 30% de descarte es un día con problema de origen, no de tu código.
- [ ] Medir tiempos. Vas a querer decir "procesa N millones de filas en M minutos".

## Día 5 — Canasta

- [ ] `cobertura()` del notebook 01 sobre datos reales.
- [ ] **Acá está el 80% del criterio del proyecto.** Ajustá los patrones de `src/canasta.py` hasta que cada item capture productos genuinamente comparables. Un item que captura 2 EANs es un patrón demasiado estrecho; uno que captura 400 seguramente está mezclando presentaciones.
- [ ] Revisar las cantidades mensuales: ¿son razonables para un hogar de 4?

## Días 6–7 — Análisis

- [ ] `python -m src.transform` y notebook 03.
- [ ] Los tres hallazgos, con números.
- [ ] Preguntas que valen oro si las respondés: ¿alguna cadena sube antes que el resto? ¿la dispersión es mayor en limpieza que en alimentos? ¿las provincias del norte pagan más?
- [ ] Opcional pero muy diferenciador: bajar el IPC del INDEC y comparar.

## Día 8 — Power BI

Tres páginas. **Tres.** Más páginas es peor dashboard.

1. **Resumen ejecutivo** — 4 KPI cards (brecha mediana, ahorro mensual, canasta actual, variación del período) + el gráfico de escenarios + ranking de cadenas.
2. **Explorador** — segmentadores de provincia, categoría e item; tabla con precio min/med/max y qué cadena es cada uno.
3. **Evolución** — series por item y por cadena, con selector.

Cargá los CSV de `data/processed/`. Relación estrella: `dim_item` a las tablas de hechos por `item`.

Detalles que se notan: formato de moneda argentino, títulos que dicen el hallazgo (no "Gráfico 1"), paleta de 2–3 colores.

## Día 9 — Documentación

- [ ] Completar el README con **tus** números y **tus** capturas.
- [ ] Informe de 2–3 páginas en PDF (exportá el Power BI o escribilo en Markdown).
- [ ] Que el README tenga imágenes: la mayoría de los reclutadores no clona nada.

## Día 10 — Buffer y publicación

- [ ] Grabar un GIF o video de 60 segundos navegando el dashboard.
- [ ] Repo público, commits con mensajes decentes.
- [ ] Publicar en LinkedIn.

---

## Si vas retrasado

Cortá **alcance**, nunca calidad:

1. Menos días de datos (7 en vez de 20)
2. Menos provincias (las 5 con mejor cobertura)
3. Menos items en la canasta (15 en vez de 29)
4. Dashboard de 2 páginas

Un proyecto chico y terminado gana siempre contra uno ambicioso a medias.

---

## Post en LinkedIn

No publiques "hice un proyecto de análisis de datos 📊". Publicá el hallazgo:

> El Gobierno publica 12 millones de precios de supermercado por día. Casi nadie los usa, porque están en un formato incómodo.
>
> Los descargué, los limpié y los dejé consultables. Encontré que el mismo litro de aceite puede costar ___% más caro según en qué cadena lo compres, en la misma provincia. Para un hogar tipo, eso son $______ por mes.
>
> Todo el pipeline y el dashboard están acá 👇 (Python, DuckDB, Power BI)

Gancho = número. Repo al final. Compartilo en grupos de datos de Argentina y etiquetá #datosabiertos.

## En la entrevista

Orden: **problema → hallazgo → técnica**. Nunca al revés.

Preparate estas cuatro:

- *"¿Por qué mediana y no promedio?"* → Una cadena concentra mucha sucursal; el promedio termina siendo su precio.
- *"¿Cómo sabés que estás comparando el mismo producto?"* → No lo sé con certeza; por eso uso patrones revisados a mano y mido cuántos EAN capta cada item. Es la principal limitación y está en el README.
- *"¿Esto contradice al INDEC?"* → No. Mi canasta pondera distinto y cubre solo grandes superficies. Son cosas distintas.
- *"¿Qué harías con más tiempo?"* → Orquestación diaria, tests de calidad automáticos, alertas de cadenas que dejan de reportar, matcheo por embeddings.
