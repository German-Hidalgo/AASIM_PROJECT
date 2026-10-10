"""Configuración de pytest: hace importable el paquete ``src`` y el generador
sintético sin modificar ``pyproject.toml``."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
