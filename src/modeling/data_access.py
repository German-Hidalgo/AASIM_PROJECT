# =====================================================================
# FASE 3 | Bloque 2: Acceso a datos y caché local (AASIM)
# ---------------------------------------------------------------------
# Punto único de entrada a los datos de modelado:
#   * carga la ABT versionada validando su SHA-256 contra el manifiesto;
#   * lista los pacientes válidos (una fila por ventana usable);
#   * describe el estado de la caché (espejo local/ventanas por paciente).
# No descarga la base completa: lee únicamente los artefactos ya
# producidos por la Fase 2 (package offline-first).
# Responsable: Rocha (ingeniería TI).
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from src.modeling.abt import cargar_abt
from src.modeling.config import (
    SEMILLA_DEFAULT,
    ConfigFase3,
    guardar_config,
)


def cargar_datos(cfg: ConfigFase3) -> pd.DataFrame:
    """Carga la ABT versionada y valida su huella SHA-256 (anti-tampering)."""
    cfg.preparar_salidas()
    abt = cargar_abt(cfg.abt_dir)
    return abt


def listado_pacientes(abt: pd.DataFrame) -> pd.DataFrame:
    """Tabla patient-wise: nº de ventanas, fuentes y partición por sujeto.

    Args:
        abt: ABT cargada (una fila por ventana).

    Returns:
        DataFrame indexado por ``subject_id`` con columnas
        ``n_ventanas``, ``fuentes``, ``particion`` y ``sbp_media``.
    """
    tabla = (
        abt.groupby("subject_id")
        .agg(
            n_ventanas=("win_index", "size"),
            fuentes=("source", lambda s: ",".join(sorted(set(s)))),
            particion=("split", "first"),
            sbp_media=("sbp_mmhg", "mean"),
        )
        .reset_index()
        .sort_values(["particion", "subject_id"])
    )
    tabla["sbp_media"] = tabla["sbp_media"].round(1)
    return tabla


def resumen_caché(abt: pd.DataFrame) -> dict:
    """Inventario de la caché derivada: ventanas por paciente y por partición.

    La caché de la Fase 3 es *derivada* (ABT en disco); el espejo local de
    señales (``~/AASIM_mini``) queda fuera de la cadena de modelado.
    """
    por_particion = (
        abt.groupby("split")
        .agg(n_ventanas=("win_index", "size"), n_pacientes=("subject_id", "nunique"))
        .reset_index()
    )
    por_paciente = listado_pacientes(abt)
    total_ventanas = len(abt)
    return {
        "tipo": "abt_derivada",
        "n_ventanas": total_ventanas,
        "n_pacientes": int(abt["subject_id"].nunique()),
        "por_particion": por_particion.to_dict(orient="records"),
        "ventanas_por_paciente_min": int(por_paciente["n_ventanas"].min()),
        "ventanas_por_paciente_max": int(por_paciente["n_ventanas"].max()),
        "ventanas_por_paciente_media": float(por_paciente["n_ventanas"].mean()),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: carga, valida y vuelca el inventario de pacientes y caché."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloque 2: acceso y caché")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    cfg = ConfigFase3(
        abt_dir=args.abt_dir or ConfigFase3().abt_dir, semilla=args.semilla
    )
    cfg.preparar_salidas()
    guardar_config(cfg, cfg.out_base / "config_fase3.json")

    abt = cargar_datos(cfg)
    pacientes = listado_pacientes(abt)
    cache = resumen_caché(abt)

    print(f"[data_access] ABT {abt.shape[0]} filas x {abt.shape[1]} columnas")
    print(
        f"[data_access] {cache['n_pacientes']} pacientes · "
        f"{cache['n_ventanas']} ventanas"
    )
    for fila in cache["por_particion"]:
        print(
            f"  {fila['split']:6s} {fila['n_pacientes']:3d} pacientes · "
            f"{fila['n_ventanas']:5d} ventanas"
        )

    salida = args.out or (cfg.out_base / "inventario_pacientes.json")
    payload = {"cache": cache, "pacientes": pacientes.to_dict(orient="records")}
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[data_access] inventario guardado en {salida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
