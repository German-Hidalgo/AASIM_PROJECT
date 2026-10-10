# AASIM_PROJECT

Sistema AASIM: software como dispositivo médico (SaMD) para la estimación continua de PAS, PAD y PAM a partir de derivaciones de ECG.

Este repositorio contiene el informe y la presentación de la Fase 1 y los entregables de la **Fase 2** (preparación de datos, gobernanza y mitigación de riesgos de validez): pipeline de preprocesamiento, Data Quality Report, diccionario de datos con esquema de metadatos y matriz de riesgos de validez. Los datos de trabajo son **PulseDB v2.0** (MIMIC-III y VitalDB).

Equipo: Juan Manuel Buitrago (validación clínica), Luis Carlos Rocha (ingeniería TI) y German Alberto Hidalgo (ética, privacidad y calidad).

## 1. Requisitos

| Herramienta | Uso |
|---|---|
| Python 3.13 y [uv](https://docs.astral.sh/uv/) | entorno y dependencias (`.python-version`, `pyproject.toml`, `uv.lock`) |
| TeX Live (`latexmk`, `xelatex`, `babel-spanish`, `beamer`, `tikz`) | informe, presentaciones y PDFs de la Fase 2 |
| `pandoc` | conversión de los informes Markdown de la Fase 2 a PDF |
| `pdfunite` (poppler-utils), opcional | PDF único con los tres informes de la Fase 2 |
| PulseDB v2.0 en `data/raw/datos_drive/PulseDB_v2_0/` | datos (603 GB, no se versionan) |

## 2. Instalación y verificación del código

```bash
uv sync --locked
uv run ruff check .
uv run ruff check . --fix
# Corrección de errores seguros
uv run ruff format --check .
uv run ruff format .
# Corrección de formato
uv run pytest -q
# 41 pruebas: filtros causales, SQI, características, particiones, metadatos y transformaciones
```

### Scripts de `uv add` (dependencias acumuladas)

`pyproject.toml` y `uv.lock` ya incluyen todo lo siguiente; estos comandos solo son necesarios para reconstruir el proyecto desde cero:

```bash
# Base del proyecto
uv add "matplotlib>=3.9,<4" "numpy>=2,<3" "scipy>=1.14,<2"
# Fase 2: wavelets, tablas, lectura de MATLAB v7.3 (HDF5) y validación de metadatos
uv add PyWavelets pandas h5py jsonschema
# Desarrollo
uv add --dev "pytest>=8.3,<10" "ruff>=0.12,<1"
```

## 3. Regenerar todo con un solo comando

```bash
bash scripts/fase2/regenerar_todo.sh
```

Ejecuta, en orden: `uv sync`, `ruff`, `pytest`, catálogo de PulseDB, muestra de formas de onda, particiones anti-fuga, estadísticas y figuras reales, figuras sintéticas de verificación, PDFs de los informes de la Fase 2 (más un PDF único), presentación de la Fase 2 y el informe y la presentación de la Fase 1.

Variables opcionales:

| Variable | Valor por defecto | Efecto |
|---|---|---|
| `PULSEDB` | `data/raw/datos_drive/PulseDB_v2_0` | raíz de PulseDB |
| `N_POR_FUENTE` | `40` | sujetos adultos por fuente en la muestra de ondas |
| `K_VENTANAS` | `60` | ventanas de 10 s por sujeto |
| `PARTES` | `2` | procesos en paralelo al leer las ondas |
| `SEMILLA` | `20260920` | semilla de la muestra y de las particiones |
| `FORZAR` | `0` | `1` rehace catálogo y muestra aunque existan |
| `SALTAR_LATEX` | `0` | `1` omite la compilación de presentaciones e informe LaTeX |

> **Catálogo e identificadores.** El catálogo asigna identificadores `SUBJ-xxxxx` por permutación aleatoria (privacidad, RNF1). Rehacerlo cambia los identificadores y obliga a rehacer muestra, particiones e informes; por eso el script solo lo ejecuta si no existe. Para reproducir exactamente un catálogo previo use `--semilla`.

## 4. Paso a paso

Todos los comandos se ejecutan desde la raíz del repositorio.

```bash
# 1. Catálogo: metadatos y etiquetas de los 5 361 sujetos (lee solo Info_Files; ~40 s)
uv run python -m src.ingestion.pulsedb_catalog \
    --info data/raw/datos_drive/PulseDB_v2_0/Info_Files/PulseDB_Info.mat

# 2. Muestra de formas de onda: filtrado causal a 125 Hz, compuerta SQI,
#    65 características y latencia. Reanudable; --parte/--partes paralelizan.
uv run python -m src.ingestion.pulsedb_sample \
    --raiz-pulsedb data/raw/datos_drive/PulseDB_v2_0 \
    --n-por-fuente 40 --k-ventanas 60 --tiempo-max 1000000000

# 3. Particiones patient-wise 70/15/15, leave-one-site-out y certificado de
#    intersección vacía
uv run python -m src.partitioning.partition_pulsedb

# 4. Estadísticas, tablas y figuras del DQR con datos reales (figures/pulsedb)
uv run python -m src.reports.pulsedb_dqr_analysis

# 5. Figuras de verificación funcional con datos sintéticos (figures/verificacion_sintetica)
uv run python -m src.reports.generate_visualizations --synthetic-demo
```

### Informes de la Fase 2 (Markdown a PDF)

```bash
bash scripts/fase2/construir_informes_fase2.sh
```

Lee `reports/data_quality_report.md`, `reports/data_dictionary.md` y `reports/validity_risks_assessment.md` y escribe los PDFs en `build/reports/`.

### Ejecute el reproducible con el siguiente comando:

```bash
latexmk -pdf -xelatex -interaction=nonstopmode -halt-on-error -outdir=build/reports reports/informe.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build/presentacion slides/presentacion.tex
# Presentación de la Fase 2 (usa las figuras de figures/pulsedb)
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build/presentacion slides/presentacion_fase2.tex
```

## 5. Estructura

```text
config/metadata_schema.json     esquema JSON de metadatos por sesión (versión 1.1.0)
data/raw/                       datos originales (no versionados)
data/processed/                 catálogo, muestra y particiones (no versionados)
data/metadata/                  tabla de correspondencia RESTRINGIDA (no versionada)
src/preprocessing/              filtros causales, censura de etiquetas, transformaciones, validación de metadatos
src/sqi/                        bSQI, kSQI, pSQI y compuerta de descarte (RF4)
src/features/                   morfología, HRV, wavelets Daubechies 4 y texturas GLCM
src/partitioning/               particiones patient-wise, site-wise y certificado anti-fuga
src/ingestion/                  catálogo y muestreo de PulseDB v2.0
src/reports/                    figuras y estadísticas del DQR
tests/                          pruebas automáticas (pytest)
reports/                        informes en Markdown y LaTeX
figures/                        figuras generadas (PNG y SVG)
slides/                         presentaciones (Beamer)
scripts/fase2/                  construcción de PDFs y regeneración completa
build/                          PDFs y auxiliares de compilación
```

## 6. Resultados de la Fase 2 (resumen)

Caracterización preliminar sobre PulseDB v2.0: catálogo completo (5 361 sujetos, 5 245 454 segmentos) y una muestra de ondas de 41 sujetos y 2 042 ventanas. Detalle en `reports/`.

- Cuota ISO 81060-2 de PAD ≥ 100 mmHg: 0.65 % (mínimo 5 %); en la partición de prueba, PAS ≥ 160 mmHg: 4.7 %.
- Desfase de alineación `ABP_Lag` mayor de 50 ms en el 99.7 % de las ventanas de la muestra.
- Compuerta de calidad: 45.7 % de rechazo (99 % por pSQI); cociente de rechazo 2.02 por edad y 1.61 por estrato de PAS.
- Latencia por ventana: media de 12.5 ms en el equipo de trabajo (límite de 5 s).
- Partición patient-wise 3 732 / 800 / 800 sujetos con intersección vacía certificada.
- Las puertas G1, G5, G6 y G8 no se cumplen: la Fase 3 no queda autorizada con los umbrales y la fuente actuales.

Las cifras de las ondas provienen de una muestra y son un diagnóstico, no desempeño clínico.

## 7. Datos, privacidad y licencias

- `data/raw/`, `data/processed/` y `data/metadata/tabla_correspondencia_RESTRINGIDA.csv` no se versionan (`.gitignore`); la tabla de correspondencia guarda los nombres originales de PulseDB y debe custodiarse con acceso restringido.
- Los informes suprimen o agrupan celdas con menos de 5 sujetos.
- PulseDB conserva las licencias de sus fuentes: ODbL (MIMIC-III) y CC BY-NC-SA 4.0 (VitalDB). El uso comercial requiere revisión legal.
- Los filtros de la ruta de inferencia son causales; el modo de fase cero solo se admite para auditoría retrospectiva.
