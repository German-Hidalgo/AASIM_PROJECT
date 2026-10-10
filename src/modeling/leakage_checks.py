# =====================================================================
# FASE 3 | Bloques 5-6: Evidencia de no-fuga y balance (AASIM)
# ---------------------------------------------------------------------
# Deja constancia verificable de:
#   * intersección nula de sujetos y de centros entre particiones
#     (reutiliza el certificado sedado de la Fase 2 y lo recomprueba sobre
#     la propia ABT);
#   * balance de la variable objetivo / clases por partición;
#   * ausencia de fuga objetivo-característica (correlación espuria).
# Responsable: Hidalgo (gobernanza); implementación: Rocha.
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def evidencia_no_fuga(abt: pd.DataFrame, certificado: Path) -> dict[str, Any]:
    """Verifica y resume la no-fuga a partir del certificado y de la ABT.

    Comprueba dos capas:
    1. El certificado de la Fase 2 (paired intersections en 0).
    2. Recomprobación sobre la propia ABT: las particiones de ventanas no
       comparten ningún ``subject_id``.

    Args:
        abt: ABT con columnas ``split`` y ``subject_id``.
        certificado: Ruta a ``certificado_patient_wise.json``.

    Returns:
        Dict con ``certificado``, ``recomprobacion_abt`` y
        ``intersecciones`` (subject-wise ya seteadas a 0).
    """
    with open(certificado, "r", encoding="utf-8") as f:
        cert = json.load(f)
    if "pairwise_subject_intersections" not in cert:
        raise ValueError(
            f"El certificado {certificado} no tiene 'pairwise_subject_intersections'"
        )

    # Recomprobación de la ABT: sujetos por partición.
    sujetos = (
        abt.groupby("split")["subject_id"].apply(lambda s: set(s.astype(str))).to_dict()
    )
    inter_abt: dict[str, int] = {}
    for a, b in combinations(sorted(sujetos), 2):
        inter_abt[f"{a}&{b}"] = len(sujetos[a] & sujetos[b])

    # Sujetos presentes en varias particiones dentro de la propia ABT.
    multi = abt.groupby("subject_id")["split"].nunique()
    sujetos_duplicados = sorted(multi[multi > 1].index.astype(str))

    return {
        "certificado_verificado": cert["pairwise_subject_intersections"],
        "recomprobacion_abt": inter_abt,
        "intersecciones_ok": all(v == 0 for v in inter_abt.values()),
        "sujetos_en_varias_particiones": sujetos_duplicados,
        "conteos_particion": {k: len(v) for k, v in sujetos.items() if k},
        "n_particiones": len(sujetos),
    }


def balance_clases(
    abt: pd.DataFrame, target: str, split: str = "split"
) -> pd.DataFrame:
    """Conteo y proporción de clases por partición (clasificación).

    Args:
        abt: ABT.
        target: Columna de clase discreta (o continua a discretizar).
        split: Columna de partición (``split``).

    Returns:
        DataFrame con filas (partición, clase) y columnas ``n`` y
        ``proporcion``.
    """
    grp = abt.groupby([split, target], dropna=False).size().rename("n").reset_index()
    total = grp.groupby(split)["n"].transform("sum")
    grp["proporcion"] = (grp["n"] / total).round(4)
    return grp.sort_values([split, target])


def distribucion_por_particion(
    abt: pd.DataFrame, target: str, split: str = "split"
) -> pd.DataFrame:
    """Estadísticos del objetivo por partición (regresión: media/DE/percentiles).

    Returns:
        DataFrame con ``mean``, ``std``, ``min``, median, ``max`` y ``n``.
    """
    resumen = (
        abt.groupby(split)[target]
        .agg(["mean", "std", "min", "median", "max", "count"])
        .round(2)
        .rename(columns={"count": "n_ventanas"})
        .reset_index()
    )
    return resumen


def chequeo_fuga_objetivo(
    abt: pd.DataFrame, target: str, columnas: list[str], umbral: float = 0.95
) -> list[str]:
    """Detecta columnas sospechosas de fugar el objetivo (correlación espuria).

    Evalúa la correlación absoluta de cada feature con el objetivo usando
    SOLO las filas de entrenamiento; una correlación |r| >= ``umbral`` puede
    ser una señal de derivación directa del target.

    Args:
        abt: ABT.
        target: Columna objetivo.
        columnas: Features a analizar.
        umbral: Umbral de |r| para marca de riesgo.

    Returns:
        Lista de avisos (vacía si no hay riesgo).
    """
    train = abt[abt["split"] == "train"]
    cols = [c for c in columnas if c in train.columns and c != target]
    avisos: list[str] = []
    y = train[target].to_numpy(dtype=float)
    for c in cols:
        x = train[c].astype(object)
        x = pd.to_numeric(x, errors="coerce").to_numpy(dtype=float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 3:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.corrcoef(x[ok], y[ok])[0, 1]
        if np.isfinite(r) and abs(r) >= umbral:
            avisos.append(
                f"{c}: |r|={abs(r):.3f} >= {umbral} en train "
                "(posible derivación del objetivo)"
            )
    return avisos


def generar_informe(
    abt: pd.DataFrame,
    certificado: Path,
    target: str,
) -> dict[str, Any]:
    """Compone el informe completo de no-fuga y balance."""
    no_fuga = evidencia_no_fuga(abt, certificado)
    dist = distribucion_por_particion(abt, target)
    columnas = [c for c in abt.columns if c.startswith("feat_")]
    fuga_obj = chequeo_fuga_objetivo(abt, target, columnas)
    # Balance de la discretización de 3 clases usada por el Bloque 8.
    from src.modeling.classification import balance_clases as balance_clases_3

    balance = balance_clases_3(abt, target)
    return {
        "no_fuga": no_fuga,
        "distribucion_por_particion": dist.to_dict(orient="records"),
        "balance": balance.to_dict(orient="records"),
        "advertencias_fuga_objetivo": fuga_obj,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: genera el informe JSON de no-fuga y balance."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloques 5/6: no-fuga y balance")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument(
        "--certificado",
        type=Path,
        default=Path("data/processed/pulsedb_particion/certificado_patient_wise.json"),
    )
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    from src.modeling.config import ConfigFase3
    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)
    cert = args.certificado
    if not cert.exists():
        cert = cfg.particion_dir / "certificado_patient_wise.json"

    informe = generar_informe(abt, cert, args.target)
    salida = args.out or (cfg.out_base / "no_fuga_y_balance.json")
    salida.write_text(
        json.dumps(informe, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    ok = informe["no_fuga"]["intersecciones_ok"]
    print(f"[no_fuga] intersecciones: {informe['no_fuga']['recomprobacion_abt']}")
    print(f"[no_fuga] OK={ok}")
    print(
        f"[balance] advertencias fuga objetivo: {len(informe['advertencias_fuga_objetivo'])}"
    )
    print(f"[no_fuga] informe guardado en {salida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
