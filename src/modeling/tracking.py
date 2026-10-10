# =====================================================================
# FASE 3 | Transversal: Trazabilidad de experimentos (AASIM)
# ---------------------------------------------------------------------
# Log append-only de corridas con: id, fecha, versión de la ABT, semilla,
# tarea, hiperparámetros, métricas y hash del código. Cada resultado
# guardado por los bloques 1-8 termina registrado aquí para auditoría y
# reproducibilidad.
# Responsable: Rocha (ingeniería TI); custodia de registros: Hidalgo.
# =====================================================================

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.modeling.config import ConfigFase3


@dataclass
class RegistroExperimento:
    """Una corrida de modelado registrada.

    Attributes:
        id: Identificador único de la corrida.
        fecha: Marca temporal ISO-8601.
        version_abt: Versión de la ABT usada (``AbtVersion.version``).
        semilla: Semilla de la corrida.
        tarea: ``regresion`` o ``clasificacion``.
        params: Hiperparámetros y decisiones de preproceso.
        metricas: Métricas obtenidas.
        hash_codigo: Huella del código (hash de fuentes de ``src``).
    """

    id: str
    fecha: str
    version_abt: str
    semilla: int
    tarea: str
    params: dict[str, Any] = field(default_factory=dict)
    metricas: dict[str, float] = field(default_factory=dict)
    hash_codigo: str = ""


def nuevo_registro(
    version_abt: str,
    semilla: int,
    tarea: str,
    params: dict[str, Any],
    metricas: dict[str, float],
    hash_codigo: str = "",
) -> RegistroExperimento:
    """Crea un registro con id y fecha generados automáticamente.

    El id es ``exp-<fecha_compacta>-<hash_corto>`` (útil para auditoría).
    """
    ahora = datetime.now(UTC)
    fecha = ahora.isoformat()
    digest = hashlib.sha256(
        f"{fecha}|{semilla}|{tarea}|{json.dumps(params, sort_keys=True)}".encode()
    ).hexdigest()[:8]
    return RegistroExperimento(
        id=f"exp-{ahora.strftime('%Y%m%dT%H%M%S')}-{digest}",
        fecha=fecha,
        version_abt=version_abt,
        semilla=semilla,
        tarea=tarea,
        params=params,
        metricas=metricas,
        hash_codigo=hash_codigo,
    )


def _to_dict(registro: RegistroExperimento) -> dict[str, Any]:
    """Serializa un registro a diccionario plano (JSON-safe)."""
    return asdict(registro)


def guardar_registro(registro: RegistroExperimento, dir_log: Path) -> Path:
    """Añade el registro (JSONL) al log append-only y devuelve su ruta.

    La escritura es atómica por línea: cada URL termina en ``\\n`` y el
    archivo solo se abre en modo append.
    """
    dir_log = Path(dir_log)
    dir_log.mkdir(parents=True, exist_ok=True)
    ruta = dir_log / "experimentos.jsonl"
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(_to_dict(registro), ensure_ascii=False, sort_keys=True) + "\n"
        )
    return ruta


def leer_registros(dir_log: Path) -> pd.DataFrame:
    """Lee todos los registros del log como tabla (una fila por corrida).

    Returns:
        DataFrame vacío si el log no existe o no tiene líneas válidas.
    """
    ruta = Path(dir_log) / "experimentos.jsonl"
    if not ruta.exists():
        return pd.DataFrame()
    filas: list[dict[str, Any]] = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            filas.append(json.loads(linea))
    return pd.DataFrame(filas)


def main(argv: list[str] | None = None) -> int:
    """CLI: vuelca el resumen del log (número de registros y tabla)."""
    p = argparse.ArgumentParser(description="FASE 3 - trazabilidad de experimentos")
    p.add_argument("--dir-log", type=Path, default=None)
    args = p.parse_args(argv)

    dir_log = args.dir_log or ConfigFase3().log_dir
    df = leer_registros(dir_log)
    print(f"[tracking] {len(df)} registro(s) en {dir_log / 'experimentos.jsonl'}")
    if not df.empty:
        cols = [
            c for c in ("id", "fecha", "version_abt", "semilla", "tarea") if c in df
        ]
        print(df[cols].to_string(index=False))
        (ConfigFase3().out_base / "experimentos_log.csv").write_text(
            df.to_csv(index=False), encoding="utf-8"
        )
        print(
            f"[tracking] copia consolidada en "
            f"{ConfigFase3().out_base / 'experimentos_log.csv'}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
