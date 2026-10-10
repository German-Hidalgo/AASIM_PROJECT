#!/usr/bin/env bash
# Validación rápida de la cadena Fase 1/2 + ABT (Fase 3) con 5-10 pacientes,
# leyendo los .mat desde un espejo local (sin depender del montaje de red).
#
# Uso:
#   bash scripts/fase2/validacion_rapida.sh
#
# Variables opcionales:
#   N_POR_FUENTE   sujetos por fuente (5 -> 10 sujetos en total)
#   K_VENTANAS     ventanas por sujeto (5)
#   PULSEDB_LOCAL  espejo local de la raíz de PulseDB (~/AASIM_mini/PulseDB_v2_0)
#   SEMILLA        semilla de la muestra y particiones (20260920)
#
# Todo el proceso escribe en /tmp/opencode/validacion_* (no toca los datos reales).
set -euo pipefail
cd "$(dirname "$0")/../.."

N_POR_FUENTE="${N_POR_FUENTE:-5}"
K_VENTANAS="${K_VENTANAS:-5}"
PULSEDB_LOCAL="${PULSEDB_LOCAL:-$HOME/AASIM_mini/PulseDB_v2_0}"
SEMILLA="${SEMILLA:-20260920}"
VOUT="/tmp/opencode/validacion_fase2"
VPART="/tmp/opencode/validacion_particion"
VFIG="/tmp/opencode/validacion_figuras"
VABT="/tmp/opencode/validacion_abt"

paso() { printf '\n== %s ==\n' "$1"; }

paso "1/4 Muestra local (${N_POR_FUENTE} por fuente, ${K_VENTANAS} ventanas)"
rm -rf "$VOUT"
uv run python -m src.ingestion.pulsedb_sample \
  --raiz-pulsedb "$PULSEDB_LOCAL" --n-por-fuente "$N_POR_FUENTE" \
  --k-ventanas "$K_VENTANAS" --semilla "$SEMILLA" \
  --tiempo-max 1000000000 --out "$VOUT"

echo "-- verificación: ninguna fila con campos != 92 (en blanco = OK) --"
for f in "$VOUT"/ventanas*.csv; do
  awk -F',' 'NF!=92 {print FILENAME":"NR": "NF}' "$f"
done

paso "2/4 Particiones anti-fuga (scratch: no toca las reales)"
uv run python -m src.partitioning.partition_pulsedb --semilla "$SEMILLA" --out "$VPART"

paso "3/4 DQR en datos reales (resumen impreso en consola)"
uv run python -m src.reports.pulsedb_dqr_analysis \
  --catalogo data/processed/pulsedb_catalogo \
  --muestra "$VOUT" --out "$VFIG"

paso "4/4 ABT Fase 3 sobre la muestra de validación"
uv run python -m src.modeling.abt \
  --ventanas "$VOUT" --particion "$VPART" \
  --out "$VABT" --version 0.1.0-validacion

printf '\n== Validación rápida lista ==\n'
echo "Muestra:   $VOUT/ventanas*.csv"
echo "Partición: $VPART/manifiesto_patient_wise.json"
echo "DQR:       $VFIG/resumen_pulsedb.json"
echo "ABT:       $VABT/abt_manifest.json"