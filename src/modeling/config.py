# =====================================================================
# FASE 3 | Bloque 1: Configuración central del modelado (AASIM)
# ---------------------------------------------------------------------
# Define parámetros y rutas únicos para toda la Fase 3: semilla, rutas de
# entrada (ABT/partición), directorio de salida de resultados y figuras.
# Todo módulo de modelado lee su configuración desde aquí para que los
# experimentos sean reproducibles y trazables.
# Responsable: Rocha (ingeniería TI); revisión de la semilla: Hidalgo.
# =====================================================================

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Semilla global de la Fase 3 (coherente con la Fase 2).
SEMILLA_DEFAULT = 20260920

#: Rutas por defecto del proyecto.
_ROOT = Path(__file__).resolve().parents[2]
ABT_DIR = _ROOT / "data" / "processed" / "pulsedb_abt"
PARTICION_DIR = _ROOT / "data" / "processed" / "pulsedb_particion"
OUT_BASE = _ROOT / "results" / "modeling" / "fase3"
FIGURA_DIR = OUT_BASE / "figuras"
LOG_DIR = _ROOT / "build" / "modeling" / "registros"

#: Bordes (mmHg) para discretizar la PAS en 3 clases en el Bloque 8.
#: 4 bordes -> 3 intervalos: [0,120) normotenso, [120,140) elevada, [140,~] hipertensa.
CLASES_SBP_BORDES: tuple[float, float, float, float] = (0.0, 120.0, 140.0, 260.0)
CLASES_SBP_NOMBRES: tuple[str, str, str] = ("normotenso", "elevada", "hipertensa")


@dataclass(frozen=True)
class ConfigFase3:
    """Configuración central del modelado.

    Attributes:
        semilla: Semilla global (default ``SEMILLA_DEFAULT``).
        abt_dir: Directorio con la ABT versionada (``abt_manifest.json``).
        particion_dir: Directorio con manifiesto/certificado patient-wise.
        out_base: Directorio raíz de resultados (CSV/JSON).
        figura_dir: Directorio de figuras (PNG).
        log_dir: Directorio de registros de experimentos (append-only).
        target: Variable objetivo por defecto (``sbp_mmhg``).
        grupo: Columna de agrupación de la validación (``subject_id``).
        n_splits: Número de pliegues agrupados por sujeto.
        n_jobs: Paralelismo CPU (auto = número de núcleos).
        usar_mlp: Si la GPU/CUDA está disponible, activa el MLP del Bloque 7.
    """

    semilla: int = SEMILLA_DEFAULT
    abt_dir: Path = ABT_DIR
    particion_dir: Path = PARTICION_DIR
    out_base: Path = OUT_BASE
    figura_dir: Path = FIGURA_DIR
    log_dir: Path = LOG_DIR
    target: str = "sbp_mmhg"
    grupo: str = "subject_id"
    n_splits: int = 5
    n_jobs: int = field(default_factory=lambda: max(1, os.cpu_count() or 1))
    usar_mlp: bool = True

    def __post_init__(self) -> None:
        # Convierte las rutas a Path absolutos por si llegan como str.
        for campo in ("abt_dir", "particion_dir", "out_base", "figura_dir", "log_dir"):
            valor = getattr(self, campo)
            if isinstance(valor, str):
                object.__setattr__(self, campo, Path(valor))
        object.__setattr__(self, "out_base", self.out_base.resolve())
        object.__setattr__(self, "figura_dir", self.figura_dir.resolve())
        object.__setattr__(self, "log_dir", self.log_dir.resolve())

    def preparar_salidas(self) -> None:
        """Crea los directorios de resultados (idempotente)."""
        for d in (self.out_base, self.figura_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fijar_semillas(semilla: int = SEMILLA_DEFAULT) -> None:
    """Fija las semillas globales deterministas (reproducibilidad).

    Aplica a ``numpy`` y al módulo ``random``; los estimadores de
    scikit-learn reciben además ``random_state=semilla` explícito.
    """
    import random

    import numpy as np

    np.random.seed(semilla)
    random.seed(semilla)


def cargar_config(ruta: str | Path | None = None) -> ConfigFase3:
    """Carga la configuración desde un JSON (si existe); si no, crea la default."""
    ruta = Path(ruta) if ruta else None
    if ruta is not None and ruta.exists():
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return ConfigFase3(**datos)
    return ConfigFase3()


def guardar_config(cfg: ConfigFase3, ruta: str | Path) -> Path:
    """Serializa la configuración a JSON (evidencia del Bloque 1)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **cfg.to_dict(),
        "abt_dir": str(cfg.abt_dir),
        "particion_dir": str(cfg.particion_dir),
        "out_base": str(cfg.out_base),
        "figura_dir": str(cfg.figura_dir),
        "log_dir": str(cfg.log_dir),
        "generado": datetime.now(UTC).isoformat(),
    }
    ruta.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return ruta


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI: imprime y guarda la configuración."""
    import argparse

    p = argparse.ArgumentParser(description="FASE 3 - Bloque 1: configuración")
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    p.add_argument(
        "--out",
        type=Path,
        default=OUT_BASE / "config_fase3.json",
    )
    args = p.parse_args(argv)
    cfg = ConfigFase3(semilla=args.semilla)
    cfg.preparar_salidas()
    ruta = guardar_config(cfg, args.out)
    print(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False, default=str))
    print(f"[config] guardada en {ruta}", flush=True)
    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
