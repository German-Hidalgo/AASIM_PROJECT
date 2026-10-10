# =====================================================================
# FASE 3 | Bloque 5: Split por sujeto, métricas y tests (AASIM)
# ---------------------------------------------------------------------
# Validación cruzada K-fold agrupada POR SUJETO (un paciente nunca se
# reparte entre pliegues), reutilizando ``subject_group_kfold`` de la
# Fase 2. Incluye:
#   * métricas de regresión (MAE, RMSE, ME±SD, r, BHS/AAMI);
#   * métricas de clasificación (balanced accuracy, macro-F1);
#   * early stopping agrupado por sujeto para modelos iterativos.
# La partición ``test`` NO se toca durante la validación.
# Responsable: Rocha (ingeniería TI).
# =====================================================================

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.modeling.baselines import SEMILLA_DEFAULT

# Router típico: ``subject_group_kfold`` (Fase 2).
from src.partitioning.split_dataset import subject_group_kfold


# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------
def metricas_regresion(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Métricas de regresión sobre valores observados *válidos*.

    Returns:
        Diccionario con ``mae``, ``rmse``, ``me`` (sesgo), ``sd_error``,
        ``r_pearson`` y cumplimiento BHS (5/10/15 mmHg) y AAMI.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    validos = np.isfinite(y_true) & np.isfinite(y_pred)
    if not validos.all():
        y_true, y_pred = y_true[validos], y_pred[validos]
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    me = float(np.mean(err))
    sd = float(np.std(err, ddof=1)) if len(err) > 1 else float("nan")
    num = np.sum((y_true - y_true.mean()) * (y_pred - y_pred.mean()))
    den = np.sqrt(
        np.sum((y_true - y_true.mean()) ** 2) * np.sum((y_pred - y_pred.mean()) ** 2)
    )
    r = float(num / den) if den > 0 else float("nan")
    bhs5 = float(np.mean(np.abs(err) <= 5.0))
    bhs10 = float(np.mean(np.abs(err) <= 10.0))
    bhs15 = float(np.mean(np.abs(err) <= 15.0))
    return {
        "mae": mae,
        "rmse": rmse,
        "me": me,
        "sd_error": sd,
        "r_pearson": r,
        "bhs_5": bhs5,
        "bhs_5_10": bhs10,
        "bhs_5_10_15": bhs15,
        "aami_strato14": float(abs(me) <= 5.0 and sd <= 8.0),
    }


def metricas_clasificacion(
    y_true: np.ndarray, y_pred: np.ndarray, labels: Sequence[Any] | None = None
) -> dict[str, float]:
    """Métricas de clasificación multiclase.

    Args:
        y_true: Etiquetas reales.
        y_pred: Etiquetas predichas.
        labels: Universo de clases (fija el conteo de clases ausentes, evita
            avisos de ``f1_score`` y mantiene las 3 clases en matrices).

    Returns:
        ``balanced_accuracy`` y ``macro_f1``.
    """
    from sklearn.metrics import balanced_accuracy_score, f1_score

    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return {
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=labels)),
    }


# --------------------------------------------------------------------------
# Folds agrupados por sujeto
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class EsquemaFold:
    """Conjuntos (entrenar/validar) de sujetos de un pliegue.

    Attributes:
        indice: Número del pliegue (0-based).
        sujetos_train: Sujetos del subentrenamiento del pliegue.
        sujetos_val: Sujetos de validación del pliegue.
    """

    indice: int
    sujetos_train: frozenset[str]
    sujetos_val: frozenset[str]


def esquema_cv(
    abt: pd.DataFrame,
    grupo: str = "subject_id",
    n_splits: int = 5,
    semilla: int = SEMILLA_DEFAULT,
    sobre: str = "train",
) -> list[EsquemaFold]:
    """Construye las tuplas de sujetos (train/val) de la CV por sujeto.

    Args:
        abt: ABT con columna ``split`` y ``grupo``.
        grupo: Columna de agrupación (sujeto).
        n_splits: Número de pliegues.
        semilla: Semilla determinista del reparto.
        sobre: Partición sobre la que se produce la CV (``train``).

    Returns:
        Lista de pliegues (sujetos por pliegue, sin intersección entre
        subconjuntos del mismo pliegue).
    """
    base = abt[abt["split"] == sobre]
    sujetos = sorted(base[grupo].astype(str).unique())
    if len(sujetos) < n_splits:
        raise ValueError(
            f"Se requieren al menos {n_splits} sujetos sobre '{sobre}' "
            f"para la CV; hay {len(sujetos)}."
        )
    pliegues: list[EsquemaFold] = []
    for i, (tr, va) in enumerate(subject_group_kfold(sujetos, n_splits, semilla)):
        pliegues.append(
            EsquemaFold(
                indice=i, sujetos_train=frozenset(tr), sujetos_val=frozenset(va)
            )
        )
    return pliegues


def validacion_agrupada(
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    grupo: str = "subject_id",
    n_splits: int = 5,
    semilla: int = SEMILLA_DEFAULT,
    modelo: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Evalúa un modelo por CV agrupada por sujeto.

    Archiva el modelo por pliegue: ajusta al subentrenamiento del pliegue
    (re-escalando con estadísticos de ESE pliegue), predice a validación
    y registra métricas por pliegue.

    Args:
        abt: ABT (debe incluir una columna ``split``).
        target: Nombre de la variable objetivo.
        tarea: ``regresion`` o ``clasificacion``.
        grupo: Columna de agrupación.
        n_splits: Número de pliegues.
        semilla: Semilla del reparto.
        modelo: Fabricante del estimador (callable sin argumentos o con
            ``random_state``). Si es ``None``, se usa Ridge (regresión) o
            LogisticRegression (clasificación).

    Returns:
        DataFrame con una fila por pliegue: métricas + `n_val` y
        ``n_sujetos_val``.
    """
    from sklearn.linear_model import LinearRegression, LogisticRegression

    if modelo is None:
        if tarea == "regresion":
            modelo = lambda: LinearRegression()
        else:
            modelo = lambda: LogisticRegression(max_iter=2000, random_state=semilla)

    # Permite ensamblar el modelo con una semilla distinta si es configurable.
    fabrica = modelo
    pliegues = esquema_cv(abt, grupo, n_splits, semilla, sobre="train")
    filas: list[dict[str, Any]] = []
    features = [c for c in abt.columns if c.startswith("feat_")]
    numericas = tuple(features)

    for fold in pliegues:
        train_mask = abt[grupo].astype(str).isin(fold.sujetos_train)
        val_mask = abt[grupo].astype(str).isin(fold.sujetos_val)
        Xtr, ytr = abt.loc[train_mask, numericas], abt.loc[train_mask, target]
        Xva, yva = abt.loc[val_mask, numericas], abt.loc[val_mask, target]
        if len(Xva) == 0 or len(Xtr) == 0:
            continue

        # Escalado robusto restringido a los sujetos de entrenamiento del pliegue.
        from src.modeling.pipeline import ajustar, construir_pipeline, transformar

        pipe = construir_pipeline(numericas)
        pipe = ajustar(pipe, Xtr.assign(_subj=abt.loc[train_mask, grupo]))
        Xtr_t = transformar(pipe, Xtr)
        Xva_t = transformar(pipe, Xva)

        est = fabrica()
        if hasattr(est, "set_params"):
            est.set_params(**{k: v for k, v in kwargs.items() if k != "sample_weight"})
        est.fit(Xtr_t, ytr.to_numpy())
        y_pred = est.predict(Xva_t)

        metricas = (
            metricas_regresion(yva.to_numpy(), y_pred)
            if tarea == "regresion"
            else metricas_clasificacion(yva.to_numpy(), y_pred)
        )
        filas.append(
            {
                "fold": fold.indice,
                "n_sujetos_val": len(fold.sujetos_val),
                "n_val": len(yva),
                **metricas,
            }
        )
    return pd.DataFrame(filas)


def con_early_stopping(
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    *,
    validacion_fraccion: float = 0.15,
    paciencia: int = 10,
    semilla: int = SEMILLA_DEFAULT,
    grupo: str = "subject_id",
) -> dict[str, Any]:
    """Entrena un modelo con parada temprana agrupada por sujeto.

    Divide los sujetos de ``train`` en ajuste/early-stop (agrupado) y
    entrena un ``LGBMRegressor`` / ``LGBMClassifier`` con ``eval_set`` = el
    subconjunto de early-stop. Devuelve el número de árboles elegido y las
    métricas sobre el early-stop.

    Returns:
        ``n_arboles`` (best_iteration), métricas del eval-set y el conteo
        de sujetos usados.
    """
    try:
        from lightgbm import LGBMClassifier, LGBMRegressor
    except ImportError as exc:  # pragma: no cover - dependencia opcional
        raise RuntimeError(
            "Con_early_stopping requiere 'lightgbm' (uv add lightgbm)."
        ) from exc

    train = abt[abt["split"] == "train"]
    sujetos = sorted(train[grupo].astype(str).unique())
    rng = np.random.RandomState(semilla)
    sujetos = rng.permutation(sujetos)
    n_es = max(1, round(len(sujetos) * validacion_fraccion))
    es_sujetos = set(sujetos[:n_es])
    fit_sujetos = set(sujetos[n_es:])

    features = [c for c in train.columns if c.startswith("feat_")]
    from src.modeling.pipeline import ajustar, construir_pipeline, transformar

    pipe = construir_pipeline(tuple(features))
    # Ajuste del pipeline con TODOS los sujetos fitness (correcto: el pipe
    # con stats de train, no de es).
    fit_mask = train[grupo].astype(str).isin(fit_sujetos)
    pipe = ajustar(
        pipe, train.loc[fit_mask, features].assign(_subj=train.loc[fit_mask, grupo])
    )

    Xfit = transformar(pipe, train.loc[fit_mask, features])
    yfit = train.loc[fit_mask, target]
    Xes = transformar(
        pipe, train.loc[train[grupo].astype(str).isin(es_sujetos), features]
    )
    yes = train.loc[train[grupo].astype(str).isin(es_sujetos), target]

    from lightgbm import early_stopping, log_evaluation

    if tarea == "regresion":
        est = LGBMRegressor(
            n_estimators=2000,
            random_state=semilla,
            n_jobs=-1,
            verbosity=-1,
        )
    else:
        est = LGBMClassifier(
            n_estimators=2000,
            random_state=semilla,
            n_jobs=-1,
            verbosity=-1,
        )
    est.fit(
        Xfit,
        yfit.to_numpy(),
        eval_X=Xes,
        eval_y=yes.to_numpy(),
        callbacks=[early_stopping(paciencia), log_evaluation(0)],
    )
    y_pred = est.predict(Xes)
    metricas = (
        metricas_regresion(yes.to_numpy(), y_pred)
        if tarea == "regresion"
        else metricas_clasificacion(yes.to_numpy(), y_pred)
    )
    return {
        "n_arboles_elegidos": int(est.best_iteration_ or est.n_estimators),
        "n_sujetos_fit": len(fit_sujetos),
        "n_sujetos_early_stop": len(es_sujetos),
        "metricas_early_stop": metricas,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: ejecuta la CV agrupada por sujeto (modelo Ridge) y guarda CSV."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloque 5: CV por sujeto")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument(
        "--tarea", choices=("regresion", "clasificacion"), default="regresion"
    )
    p.add_argument("--grupo", type=str, default="subject_id")
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    args = p.parse_args(argv)

    from src.modeling.config import ConfigFase3
    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    tabla = validacion_agrupada(
        abt,
        args.target,
        args.tarea,
        grupo=args.grupo,
        n_splits=args.n_splits,
        semilla=args.semilla,
    )
    print(tabla.to_string(index=False))
    salida = cfg.out_base / "cv_folds.csv"
    tabla.to_csv(salida, index=False)
    print(f"[validation] pliegues guardados en {salida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
