# Empezá acá

Guía de 15 minutos para dejar el proyecto andando en tu máquina.
(Después de esto, seguí con `PLAN.md`.)

---

## Paso 1 — Poner la carpeta en tu compu

1. Descargá `radar-precios-ar.zip`.
2. Descomprimilo en una carpeta **estable**, no en Descargas. Sugerencia:

   ```
   ~/Proyectos/radar-precios-ar
   ```

3. Verificá que adentro estén: `README.md`, `PLAN.md`, `src/`, `notebooks/`, `tests/`.

## Paso 2 — Abrirlo en VS Code

**File → Open Folder…** y elegí la carpeta `radar-precios-ar` (la que contiene el `README.md`).

> Importante: abrí **la carpeta**, no un archivo suelto. Si abrís solo `clean.py`, los imports `from src import config` no van a funcionar.

Extensiones a instalar (ícono de bloques en la barra izquierda):

- **Python** (Microsoft)
- **Jupyter** (Microsoft)

## Paso 3 — Chequear que tengas Python

En VS Code: **Terminal → New Terminal**, y escribí:

```bash
python3 --version
```

Si dice `3.10` o superior, listo. Si dice "command not found", instalalo:

- **macOS:** `brew install python@3.12` (o bajalo de python.org)
- **Windows:** desde python.org, y **tildá "Add Python to PATH"** en el instalador

## Paso 4 — Crear el entorno virtual

Un entorno virtual es una carpeta con las librerías de *este* proyecto, para no ensuciar tu Python del sistema. En la terminal de VS Code, parado en la carpeta del proyecto:

```bash
python3 -m venv .venv
```

Activarlo:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

Vas a ver `(.venv)` al principio de la línea. Eso significa que está activo.

> **Tenés que activarlo cada vez que abrís una terminal nueva.** Es el error #1 de todo el mundo.

Instalar las librerías:

```bash
pip install -r requirements.txt
```

Tarda 1–2 minutos.

## Paso 5 — Probar que todo funciona (sin bajar datos)

```bash
python -m tests.make_fixture --dias 14 --sucursales 180
python -m src.clean --forzar
python -m src.transform
python -m src.figuras
python -m tests.test_pipeline
```

**Qué tenés que ver:**

- Una tabla de calidad con las filas descartadas por día
- Un bloque `HALLAZGOS` con tres números
- `6/6 verificaciones pasan`
- Cinco PNG nuevos en `reports/figs/`

Si llegaste hasta acá, el proyecto anda. Todo lo que sigue es análisis, no plomería.

## Paso 6 — Los notebooks

En VS Code abrí `notebooks/01_exploracion.ipynb`. Arriba a la derecha, **Select Kernel → Python Environments → .venv**.

Ejecutá las celdas con `Shift + Enter`.

## Paso 7 — Datos reales

Recién ahora. Primero mirá qué hay publicado:

```bash
python -m src.extract --listar
```

Bajate **dos días nada más** para empezar:

```bash
python -m src.extract --ultimos 2
```

Después abrí a mano un `productos.csv` de `data/raw/` y **comparalo con lo que espera `src/config.py`**. Si los nombres de columna cambiaron, ajustalos ahí. Si algo no coincide, `clean.py` te va a decir exactamente qué columnas encontró.

Cuando eso funcione:

```bash
python -m src.extract --ultimos 14
python -m src.clean
python -m src.transform
python -m src.figuras
python -m tests.test_pipeline
```

⚠️ Los datos crudos pesan varios GB. Si te preocupa el espacio:

```bash
export RADAR_DATA_DIR=/ruta/a/otro/disco     # macOS/Linux
$env:RADAR_DATA_DIR="D:\sepa"                # Windows PowerShell
```

## Paso 8 — Git y GitHub

```bash
git init
git add .
git commit -m "Pipeline SEPA: extract, clean, transform y verificacion"
```

Creá un repo **público** vacío en github.com (sin README, sin .gitignore — ya los tenés) y después:

```bash
git remote add origin https://github.com/TU-USUARIO/radar-precios-ar.git
git branch -M main
git push -u origin main
```

El `.gitignore` ya excluye `data/`, así que no vas a subir gigas por accidente. Las figuras de `reports/figs/` **sí** se suben: son las que se ven en el README.

---

## Errores que te van a pasar

| Síntoma | Causa | Solución |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | estás parado en otra carpeta | `cd` a la raíz del proyecto (donde está el README) |
| `ModuleNotFoundError: No module named 'pandas'` | el venv no está activo | `source .venv/bin/activate` |
| `No hay datos en data/interim/` | corriste transform antes de clean | corré `clean.py` primero |
| `faltan columnas núcleo [...]` | SEPA cambió el formato | ajustá los nombres en `src/config.py` |
| El notebook no encuentra `src` | kernel equivocado | Select Kernel → `.venv` |
| `running scripts is disabled` (Windows) | política de PowerShell | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

---

## Orden mental

1. **Hoy:** pasos 1 a 6. Que ande el fixture. No toques datos reales todavía.
2. **Mañana:** paso 7, dos días de datos reales, verificar el esquema.
3. **De ahí en más:** seguí `PLAN.md`.

Regla: **nunca pases al día siguiente con algo roto.** Es preferible menos alcance que un pipeline que falla la mitad de las veces.
