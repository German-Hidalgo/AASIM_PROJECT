#!/usr/bin/env bash
# Compila los tres informes de la Fase 2 (Markdown -> PDF) en build/reports.
# Uso, desde la raíz del repositorio:  bash scripts/fase2/construir_informes_fase2.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
SALIDA="build/reports"
mkdir -p "$SALIDA"
FECHA="19 de septiembre de 2026"

construir() {
  local fuente="$1" salida="$2" subtitulo="$3"
  pandoc "reports/${fuente}.md" \
    --from markdown+hard_line_breaks-tex_math_dollars \
    --shift-heading-level-by=-1 \
    --pdf-engine=xelatex \
    --lua-filter=scripts/fase2/fase2_filtro.lua \
    --include-in-header=scripts/fase2/fase2_preambulo.tex \
    --resource-path=.:reports \
    --toc --toc-depth=2 \
    -V documentclass=article -V papersize=a4 -V fontsize=10pt \
    -V geometry:"top=2.3cm,bottom=2.3cm,left=2.2cm,right=2.2cm" \
    -V lang=es \
    -V colorlinks=true -V linkcolor=aasimazul -V urlcolor=aasimazul \
    -M subtitle="${subtitulo}" \
    -M author="Juan Manuel Buitrago, Luis Carlos Rocha y German Alberto Hidalgo" \
    -M date="${FECHA}" \
    -o "${SALIDA}/${salida}.pdf"
  echo "OK  ${SALIDA}/${salida}.pdf"
}

construir data_quality_report        data_quality_report        "Proyecto AASIM - Fase 2"
construir data_dictionary            data_dictionary            "Proyecto AASIM - Fase 2"
construir validity_risks_assessment  validity_risks_assessment  "Proyecto AASIM - Fase 2"
