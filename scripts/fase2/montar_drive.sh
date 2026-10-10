#!/usr/bin/env bash
# Monta el Google Drive compartido de PulseDB en ~/AASIM_datos con flags
# estables (evita RATE_LIMIT_EXCEEDED y caídas del montaje).
#
# Uso:
#   bash scripts/fase2/montar_drive.sh
#
# Nota: la carpeta compartida solo da acceso a PulseDB_MIMIC y PulseDB_Vital.
# El client_id compartido de rclone se retira en 2026; si deja de funcionar,
# crear uno propio (https://rclone.org/drive/#making-your-own-client-id).
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
ROOT_ID="1-WKcJgO9lAjY2HBepRGDqyF3xjFADr8-"
PUNTO="$HOME/AASIM_datos"

# Si ya está montado, no duplicar.
if mountpoint -q "$PUNTO" 2>/dev/null; then
  echo "El Drive ya está montado en $PUNTO."
  exit 0
fi

mkdir -p "$PUNTO"
nohup rclone mount "gdrive:" "$PUNTO" \
  --drive-root-folder-id "$ROOT_ID" \
  --vfs-cache-mode full --vfs-cache-max-size 40G \
  --buffer-size 256M --transfers 2 --tpslimit 3 --tpslimit-burst 6 \
  --dir-cache-time 1000h \
  --log-file "$HOME/rclone.log" --log-level INFO > /dev/null 2>&1 &

sleep 8
if mountpoint -q "$PUNTO" 2>/dev/null; then
  echo "Drive montado en $PUNTO (con caché y límite de peticiones)."
else
  echo "Aún arrancando; revisa con: tail -f ~/rclone.log"
fi