# =====================================================================
# FASE 3 | Bloque 7b: Tuning de hiperparámetros y ablación (AASIM)
# ---------------------------------------------------------------------
# * Búsqueda de hiperparámetros (Optuna) con validación agrupada por
#   sujeto, nunca sobre ``test``.
# * Ablación de grupos de características (morfológicas, HRV, wavelets,
#   GLCM) para justificar la selección y detectar dependencias espurias.
# Responsable: Rocha (ingeniería TI); revisión clínica: Buitrago.
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.modeling.baselines import SEMILLA_DEFAULT
from src.modeling.config import ConfigFase3


# --------------------------------------------------------------------------
# Tuning
# --------------------------------------------------------------------------
def _objetivo_optuna(
    trial: Any,
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    semilla: int,
) -> float:
    """Objetivo de Optuna: MAE (regresión) o -macro-F1 (clasificación) con CV por sujeto."""
    from sklearn.linear_model import LogisticRegression

    from src.modeling.validation import validacion_agrupada

    if tarea == "regresion":
        from sklearn.linear_model import Ridge

        alpha = trial.suggest_float("alpha", 1e-3, 1e3, log=True)
        est = lambda: Ridge(alpha=alpha)
        principal = "mae"
        signo = 1.0
    else:
        from sklearn.linear_model import LogisticRegression

        C = trial.suggest_float("C", 1e-3, 1e3, log=True)
        est = lambda: LogisticRegression(C=C, max_iter=2000, random_state=semilla)
        principal = "macro_f1"
        signo = -1.0

    tabla = validacion_agrupada(
        abt, target, tarea, n_splits=3, semilla=semilla, modelo=est
    )
    if tabla.empty or principal not in tabla.columns:
        return signo * float("inf")
    return signo * float(tabla[principal].mean())


def buscar_hiperparametros(
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    espacio: Mapping[str, Sequence[Any]],
    *,
    n_splits: int = 5,
    semilla: int = SEMILLA_DEFAULT,
    n_trials: int = 20,
) -> dict[str, Any]:
    """Busca hiperparámetros con Optuna (validación agrupada por sujeto).

    Args:
        abt: ABT con la partición ``train``.
        target: Variable objetivo.
        tarea: ``regresion`` o ``clasificacion``.
        espacio: Espacio de búsqueda (se consulta con ``trial.suggest_*``).
        n_splits: Pliegues internos de la CV por sujeto.
        semilla: Semilla.
        n_trials: Número de tanteos de Optuna.

    Returns:
        Dict con ``mejores_params``, ``mejor_valor``, ``tarea`` y
        ``n_trials``.
    """
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="minimize", sampler=optuna.samplers.TPESampler(seed=semilla)
    )
    study.optimize(
        lambda t: _objetivo_optuna(t, abt, target, tarea, semilla),
        n_trials=n_trials,
        show_progress_bar=False,
    )
    return {
        "mejores_params": study.best_params,
        "mejor_valor": float(study.best_value),
        "tarea": tarea,
        "n_trials": n_trials,
        "semilla": semilla,
    }


# --------------------------------------------------------------------------
# Ablación
# --------------------------------------------------------------------------
def _grupos_features(abt: pd.DataFrame) -> dict[str, list[str]]:
    """Agrupa las features de la ABT por familia (morfo/HRV/wavelet/GLCM)."""
    feats = [c for c in abt.columns if c.startswith("feat_")]
    grupos: dict[str, list[str]] = {}
    nombres = {
        "morfologia": (
            "feat_pr_",
            "feat_qrs_",
            "feat_qt",
            "feat_dvdt",
            "feat_r_amp",
            "feat_s_depth",
            "feat_st_dev",
            "feat_t_amp",
        ),
        "hrv": ("feat_hrv_",),
        "wavelet": ("feat_wpd_",),
        "glcm": ("feat_glcm_",),
    }
    for feats_familia, prefijos in nombres.items():
        grupos[feats_familia] = sorted(
            f for f in feats if any(f.startswith(p) for p in prefijos)
        )
    restante = sorted(set(feats) - set().union(*grupos.values()))
    if restante:
        grupos["otras"] = restante
    return {k: v for k, v in grupos.items() if v}


def ablation_features(
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    bloques: Mapping[str, Sequence[str]] | None = None,
    *,
    semilla: int = SEMILLA_DEFAULT,
    n_splits: int = 3,
) -> pd.DataFrame:
    """Mide el efecto de retirar cada bloque de características.

    Para cada bloque ``b``:
      1. base = todas las features;
      2. config = "sin <bloque>" (base menos las columnas del bloque);
      3. se evalúa con CV por sujeto (Ridge o LogReg) y se registra MAE/macro-F1.

    Returns:
        DataFrame con filas ``todas`` y ``sin_<bloque>`` y columnas con la
        métrica principal (media de los pliegues).
    """
    from src.modeling.validation import validacion_agrupada

    bloques_uso = dict(bloques) if bloques is not None else _grupos_features(abt)
    filas: list[dict[str, Any]] = []

    def _evaluar(sub: pd.DataFrame, etiqueta: str) -> dict[str, Any]:
        from sklearn.linear_model import LinearRegression, LogisticRegression

        if tarea == "regresion":
            est = lambda: LinearRegression()
        else:
            est = lambda: LogisticRegression(max_iter=2000, random_state=semilla)
        principal = "mae" if tarea == "regresion" else "macro_f1"
        tabla = validacion_agrupada(
            sub, target, tarea, n_splits=n_splits, semilla=semilla, modelo=est
        )
        res: dict[str, Any] = {"config": etiqueta}
        if tabla.empty:
            res[principal] = float("nan")
            return res
        res[principal] = float(tabla[principal].mean())
        for k in ("mae", "macro_f1", "balanced_accuracy", "r_pearson"):
            if k in tabla.columns:
                res[k] = float(tabla[k].mean())
        return res

    filas.append(_evaluar(abt, "todas"))
    for nombre, cols in bloques_uso.items():
        restante = [
            c for c in abt.columns if c.startswith("feat_") and c not in set(cols)
        ]
        sub = abt[["subject_id", "split", target, *restante]].copy()
        if not restante:
            # Grupo que agota todas las features: no hay señal que evaluar.
            filas.append({"config": f"sin_{nombre}", "mae": float("nan")})
            continue
        filas.append(_evaluar(sub, f"sin_{nombre}"))
    return pd.DataFrame(filas)


def main(argv: list[str] | None = None) -> int:
    """CLI: tuning (Optuna) + ablación; guarda JSON/CSV."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloque 7b: tuning y ablación")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument(
        "--tarea", choices=("regresion", "clasificacion"), default="regresion"
    )
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    p.add_argument("--trials", type=int, default=8)
    args = p.parse_args(argv)

    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    espacio: dict[str, Sequence[Any]] = {}
    resultado_tuning = buscar_hiperparametros(
        abt,
        args.target,
        args.tarea,
        espacio,
        n_splits=5,
        semilla=args.semilla,
        n_trials=args.trials,
    )
    (cfg.out_base / "tuning.json").write_text(
        json.dumps(resultado_tuning, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[tuning] mejores params: {resultado_tuning['mejores_params']}")

    ablacion = ablation_features(abt, args.target, args.tarea, semilla=args.semilla)
    print(ablacion.to_string(index=False))
    (cfg.out_base / "ablation.csv").write_text(
        ablacion.to_csv(index=False), encoding="utf-8"
    )
    print(f"[tuning] guardado en {cfg.out_base}/tuning.json y ablation.csv", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
