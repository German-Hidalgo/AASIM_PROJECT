#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

mkdir -p build/reports build/presentacion

echo "Compilando informe de Fase 3..."
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build/reports reports/informe_fase3.tex

echo "Compilando presentacion de Fase 3..."
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build/presentacion slides/presentacion_fase3.tex

echo "¡Informes de Fase 3 generados con éxito en build/!"
