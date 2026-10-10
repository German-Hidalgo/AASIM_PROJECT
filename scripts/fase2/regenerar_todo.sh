#!/usr/bin/env bash
# Regenera de extremo a extremo los artefactos de la Fase 2 del proyecto AASIM.
#
# Uso (desde cualquier carpeta):
#   bash scripts/fase2/regenerar_todo.sh            # todo, reutilizando catálogo y muestra
#   FORZAR=1 bash scripts/fase2/regenerar_todo.sh   # rehace también catálogo y muestra
#
# Variables de entorno opcionales:
#   PULSEDB        raíz de PulseDB v2.0 (por defecto data/raw/datos_drive/PulseDB_v2_0)
#   N_POR_FUENTE   sujetos adultos por fuente en la muestra de ondas (40)
#   K_VENTANAS     ventanas por sujeto (60)
#   PARTES         procesos en paralelo para leer las ondas (2)
#   SEMILLA        semilla de la muestra y de las particiones (20260920)
#   SALTAR_LATEX   =1 omite la compilación de presentaciones e informe LaTeX
#
# Advertencia: el catálogo asigna identificadores SUBJ-xxxxx por permutación
# aleatoria. Rehacerlo (FORZAR=1) cambia los identificadores y obliga a rehacer
# la muestra, las particiones y los informes; por eso solo se ejecuta si no existe.
set -euo pipefail
cd "$(dirname "$0")/../.."

PULSEDB="${PULSEDB:-data/raw/datos_drive/PulseDB_v2_0}"
N_POR_FUENTE="${N_POR_FUENTE:-40}"
K_VENTANAS="${K_VENTANAS:-60}"
PARTES="${PARTES:-2}"
SEMILLA="${SEMILLA:-20260920}"
CAT="data/processed/pulsedb_catalogo"
MUESTRA="data/processed/pulsedb_muestra"

paso() { printf '\n== %s ==\n' "$1"; }

paso "1/9 Entorno y verificación de código"
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

INFO_MAT="$PULSEDB/Info_Files/PulseDB_Info.mat"

paso "2/9 Catálogo de metadatos y etiquetas de PulseDB"
if [[ ! -f "$INFO_MAT" ]]; then
  if [[ -f "$CAT/sujetos.csv" ]]; then
    echo "AVISO: no se encontró el dato crudo '$INFO_MAT'."
    echo "       Se reutiliza el catálogo existente en '$CAT' (no se puede reconstruir sin él)."
  else
    echo "ERROR: falta '$INFO_MAT' y no hay catálogo en '$CAT'." >&2
    echo "       Monta los datos crudos de PulseDB o define PULSEDB a su raíz." >&2
    exit 1
  fi
elif [[ ! -f "$CAT/sujetos.csv" || "${FORZAR:-0}" == "1" ]]; then
  uv run python -m src.ingestion.pulsedb_catalog \
    --info "$INFO_MAT" --out "$CAT"
else
  echo "Catálogo existente: se reutiliza (FORZAR=1 para rehacerlo)."
fi

paso "3/9 Muestra de formas de onda (SQI, características, latencia)"
tiene_ondas=0
if compgen -G "$PULSEDB/Segment_Files/PulseDB_MIMIC/*.mat" > /dev/null 2>&1 \
   || compgen -G "$PULSEDB/Segment_Files/PulseDB_Vital/*.mat" > /dev/null 2>&1; then
  tiene_ondas=1
fi
if [[ "$tiene_ondas" == "0" ]]; then
  if [[ -f "$MUESTRA/ventanas.csv" || -f "$MUESTRA/ventanas_p0.csv" ]]; then
    echo "AVISO: no se encontraron formas de onda en '$PULSEDB/Segment_Files'."
    echo "       Se reutiliza la muestra existente en '$MUESTRA'."
  else
    echo "ERROR: no hay formas de onda en '$PULSEDB/Segment_Files' ni muestra en '$MUESTRA'." >&2
    echo "       Monta los datos crudos de PulseDB o define PULSEDB a su raíz." >&2
    exit 1
  fi
elif [[ ! -f "$MUESTRA/ventanas.csv" && ! -f "$MUESTRA/ventanas_p0.csv" ]] \
   || [[ "${FORZAR:-0}" == "1" ]]; then
  mkdir -p "$MUESTRA"
  pids=()
  for ((i = 0; i < PARTES; i++)); do
    uv run python -m src.ingestion.pulsedb_sample \
      --raiz-pulsedb "$PULSEDB" --n-por-fuente "$N_POR_FUENTE" \
      --k-ventanas "$K_VENTANAS" --semilla "$SEMILLA" \
      --tiempo-max 1000000000 --parte "$i" --partes "$PARTES" &
    pids+=($!)
  done
  for pid in "${pids[@]}"; do wait "$pid"; done
else
  echo "Muestra existente: se reutiliza (FORZAR=1 para rehacerla)."
fi

paso "4/9 Particiones anti-fuga y certificado de intersección vacía"
uv run python -m src.partitioning.partition_pulsedb --semilla "$SEMILLA"

paso "5/9 Estadísticas y figuras reales del DQR (figures/pulsedb)"
uv run python -m src.reports.pulsedb_dqr_analysis

paso "6/9 Figuras de verificación funcional (datos sintéticos)"
uv run python -m src.reports.generate_visualizations --synthetic-demo

faltan_pdf=""
command -v pandoc >/dev/null 2>&1 || faltan_pdf="pandoc"
command -v xelatex >/dev/null 2>&1 || faltan_pdf="${faltan_pdf:+$faltan_pdf, }xelatex"
command -v latexmk >/dev/null 2>&1 || faltan_pdf="${faltan_pdf:+$faltan_pdf, }latexmk"

if [[ "${SALTAR_LATEX:-0}" == "1" ]]; then
  echo "Se omite la compilación de PDFs LaTeX (SALTAR_LATEX=1): pasos 7-9."
elif [[ -n "$faltan_pdf" ]]; then
  echo "AVISO: faltan herramientas para generar los PDFs ($faltan_pdf)."
  echo "       Se omiten los pasos 7-9; los PDFs previos en build/ se conservan."
  echo "       Instala texlive + pandoc y vuelve a ejecutar sin SALTAR_LATEX."
else
  paso "7/9 Informes de la Fase 2 en PDF (build/reports)"
  bash scripts/fase2/construir_informes_fase2.sh
  if command -v pdfunite >/dev/null 2>&1; then
    pdfunite build/reports/data_quality_report.pdf \
      build/reports/validity_risks_assessment.pdf \
      build/reports/data_dictionary.pdf build/reports/Informe_Fase2_AASIM_completo.pdf
    echo "OK  build/reports/Informe_Fase2_AASIM_completo.pdf"
  fi

  paso "8/9 Presentación de la Fase 2 (build/presentacion)"
  latexmk -pdf -interaction=nonstopmode -halt-on-error \
    -outdir=build/presentacion slides/presentacion_fase2.tex

  paso "9/9 Informe y presentación de la Fase 1 (build/reports, build/presentacion)"
  latexmk -pdf -xelatex -interaction=nonstopmode -halt-on-error \
    -outdir=build/reports reports/informe.tex
  latexmk -pdf -interaction=nonstopmode -halt-on-error \
    -outdir=build/presentacion slides/presentacion.tex
fi

printf '\n== Resumen de artefactos de la Fase 2 ==\n'
total=0
for f in "$MUESTRA"/ventanas*.csv; do
  total=$((total + $(($(wc -l < "$f") - 1))))
done
echo "Muestra:       $MUESTRA/ventanas*.csv  ($total ventanas en total)"
echo "Particiones:   data/processed/pulsedb_particion (manifiesto + certificado + resumen)"
echo "Figuras reales: figures/pulsedb/ (resumen_pulsedb.json, tablas_pulsedb.md, PNG)"
echo "Figuras demo:  figures/verificacion_sintetica/"
echo "PDFs:          build/reports, build/presentacion (si no se usó SALTAR_LATEX=1)"
echo "Resumen numérico en consola: uv run python -m src.reports.pulsedb_dqr_analysis"

if [[ "${SALTAR_LATEX:-0}" == "1" || -n "$faltan_pdf" ]]; then
  printf '\nListo (Fase 2 generada sin PDFs; usa SALTAR_LATEX=0 tras instalar pandoc/xelatex/latexmk para los PDFs).\n'
else
  printf '\nListo. PDFs en build/reports y build/presentacion.\n'
fi
