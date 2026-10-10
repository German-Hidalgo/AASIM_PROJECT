# =====================================================================
# FASE 3 | Bloque 8: Clasificación derivada de la PAS (AASIM)
# ---------------------------------------------------------------------
# Convierte el problema de regresión en uno de 3 clases (normotenso,
# elevada, hipertensa) para evaluar la utilidad práctica de los modelos
# y reportar balanced accuracy / macro-F1 con balance explícito.
# También prueba un Plan B (2 clases) si una clase es muy minoritaria o
# desaparece en algún pliegue.
# Responsable: Rocha (ingeniería TI); revisión clínica: Buitrago.
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.modeling.baselines import SEMILLA_DEFAULT
from src.modeling.config import CLASES_SBP_BORDES, CLASES_SBP_NOMBRES, ConfigFase3


def construir_clases(
    abt: pd.DataFrame,
    target: str = "sbp_mmhg",
    bordes: tuple[float, float, float] = CLASES_SBP_BORDES,
    nombres: tuple[str, str, str] = CLASES_SBP_NOMBRES,
) -> pd.Series:
    """Discretiza la PAS en ``k=len(bordes)-1`` clases.

    Uses ``pd.cut`` con bordes cerrados a la derecha (i.e. hipertensa
    incluye PAS >= 140 mmHg).

    Returns:
        Series de etiquetas categóricas (ordenadas), con el mismo índice
        que ``abt``.
    """
    return pd.cut(
        abt[target],
        bins=bordes,
        labels=nombres,
        right=True,
        include_lowest=True,
    )


def balance_clases(abt: pd.DataFrame, target: str = "sbp_mmhg") -> pd.DataFrame:
    """Distribución de clases por partición (n y proporción)."""
    clases = construir_clases(abt, target)
    tabla = abt.assign(clase=clases).groupby(["split", "clase"]).size().rename("n")
    tabla = tabla.reset_index()
    total = tabla.groupby("split")["n"].transform("sum")
    tabla["proporcion"] = (tabla["n"] / total).round(4)
    return tabla.sort_values(["split", "clase"])


def evaluar_clasificadores(
    abt: pd.DataFrame,
    target: str = "sbp_mmhg",
    semilla: int = SEMILLA_DEFAULT,
) -> dict[str, Any]:
    """Entrena LR / NB / SVM sobre las 3 clases y reporta métricas + matrices.

    Returns:
        Dict con ``balance_por_particion``, ``resultados`` (DF), y
        ``matrices`` (por clase de verdad).
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix
    from sklearn.naive_bayes import GaussianNB
    from sklearn.svm import SVC

    from src.modeling.pipeline import ajustar, construir_pipeline, transformar
    from src.modeling.validation import esquema_cv, metricas_clasificacion

    abt = abt.copy()
    abt["clase"] = construir_clases(abt, target)
    columnas = [c for c in abt.columns if c.startswith("feat_")]
    pliegues = esquema_cv(abt, n_splits=5, semilla=semilla, sobre="train")

    filas_raw: list[dict[str, Any]] = []
    matrices: dict[str, np.ndarray] = {}
    nombres_modelo = ["LogReg", "NaiveBayes", "SVM"]

    for fold in pliegues:
        mask_tr = abt["subject_id"].astype(str).isin(fold.sujetos_train)
        mask_va = abt["subject_id"].astype(str).isin(fold.sujetos_val)
        Xtr = abt.loc[mask_tr, columnas]
        ytr = abt.loc[mask_tr, "clase"].astype(str)
        Xva = abt.loc[mask_va, columnas]
        yva = abt.loc[mask_va, "clase"].astype(str)

        pipe = ajustar(
            construir_pipeline(tuple(columnas)),
            Xtr.assign(_subj=abt.loc[mask_tr, "subject_id"]),
        )
        Xtr_t = transformar(pipe, Xtr)
        Xva_t = transformar(pipe, Xva)

        for nombre in nombres_modelo:
            if nombre == "LogReg":
                est = LogisticRegression(max_iter=2000, random_state=semilla)
            elif nombre == "NaiveBayes":
                est = GaussianNB()
            else:
                est = SVC(random_state=semilla)
            est.fit(Xtr_t, ytr.to_numpy())
            y_pred = est.predict(Xva_t)
            metricas = metricas_clasificacion(
                yva.to_numpy(), y_pred, labels=list(CLASES_SBP_NOMBRES)
            )
            filas_raw.append(
                {
                    "fold": fold.indice,
                    "modelo": nombre,
                    "n_val": len(yva),
                    **metricas,
                }
            )
            if nombre not in matrices:
                matrices[nombre] = np.zeros((3, 3), dtype=int)
            matrices[nombre] += confusion_matrix(
                yva.to_numpy(), y_pred, labels=list(CLASES_SBP_NOMBRES)
            )

    resultados = pd.DataFrame(filas_raw)

    # Consolidación por modelo.
    tabla_modelos = (
        resultados.groupby("modelo")[["balanced_accuracy", "macro_f1"]]
        .mean()
        .round(4)
        .reset_index()
    )

    balance = balance_clases(abt, target)
    clases_por_fold = {}
    for split, grp in abt.assign(clase=construir_clases(abt, target)).groupby("split"):
        clases_por_fold[str(split)] = grp["clase"].value_counts().astype(int).to_dict()
    plan_b = _plan_b_si_necesario(balance)
    plan_b_detallado = (
        _evaluar_plan_b(abt, target, columnas, pliegues, semilla)
        if "Plan B" in (plan_b or "")
        else None
    )

    return {
        "balance_por_particion": balance.to_dict(orient="records"),
        "clases_por_fold": clases_por_fold,
        "tabla_modelos": tabla_modelos.to_dict(orient="records"),
        "matrices": {k: v.tolist() for k, v in matrices.items()},
        "plan_b": plan_b,
        "plan_b_detallado": plan_b_detallado,
        "n_filas_raw": len(resultados),
    }


def _plan_b_si_necesario(balance: pd.DataFrame, umbral_min: float = 0.05) -> str | None:
    """Detecta si una clase es demasiado minoritaria y sugiere el Plan B.

    Si cualquier (partición, clase) tiene proporción < ``umbral_min``, o una
    clase falta por completo, se recomienda colapsar a 2 clases y justificarlo.
    """
    pt = balance.copy()
    falta = pt[pt["proporcion"] == 0.0]
    minoritarias = pt[pt["proporcion"] < umbral_min]
    if not falta.empty or not minoritarias.empty:
        return (
            "Plan B: alguna clase es minoritaria (<5%) o ausente en una "
            "partición; fusionar a 2 clases (hipenso/normo-tenso vs "
            "hipertenso) y anotar el motivo en el informe."
        )
    return "Sin necesidad de Plan B: las 3 clases están presentes."


def _evaluar_plan_b(
    abt: pd.DataFrame,
    target: str,
    columnas: list[str],
    pliegues: list[Any],
    semilla: int = SEMILLA_DEFAULT,
) -> dict[str, Any]:
    """Evalúa el Plan B de 2 clases: normotenso (<120) vs no normotenso (>=120).

    Se ejecuta cuando ``_plan_b_si_necesario`` detecta una clase minoritaria
    o ausente en alguna partición. Mismo esquema de CV por sujeto y mismos
    clasificadores que el bloque principal.

    Returns:
        Dict con la definición del corte, el balance 2 clases, las métricas
        por modelo y las matrices de confusión.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix
    from sklearn.naive_bayes import GaussianNB
    from sklearn.svm import SVC

    from src.modeling.pipeline import ajustar, construir_pipeline, transformar
    from src.modeling.validation import metricas_clasificacion

    nombres2 = ["normotenso", "no_normotenso"]
    abt2 = abt.copy()
    base = construir_clases(abt2, target)
    abt2["clase"] = np.where(base.eq("normotenso"), "normotenso", "no_normotenso")

    filas: list[dict[str, Any]] = []
    matrices: dict[str, np.ndarray] = {}
    for fold in pliegues:
        mask_tr = abt2["subject_id"].astype(str).isin(fold.sujetos_train)
        mask_va = abt2["subject_id"].astype(str).isin(fold.sujetos_val)
        Xtr = abt2.loc[mask_tr, columnas]
        ytr = abt2.loc[mask_tr, "clase"].astype(str)
        Xva = abt2.loc[mask_va, columnas]
        yva = abt2.loc[mask_va, "clase"].astype(str)
        pipe = ajustar(
            construir_pipeline(tuple(columnas)),
            Xtr.assign(_subj=abt2.loc[mask_tr, "subject_id"]),
        )
        Xtr_t = transformar(pipe, Xtr)
        Xva_t = transformar(pipe, Xva)
        for nombre in ("LogReg", "NaiveBayes", "SVM"):
            if nombre == "LogReg":
                est = LogisticRegression(max_iter=2000, random_state=semilla)
            elif nombre == "NaiveBayes":
                est = GaussianNB()
            else:
                est = SVC(random_state=semilla)
            est.fit(Xtr_t, ytr.to_numpy())
            y_pred = est.predict(Xva_t)
            metricas = metricas_clasificacion(yva.to_numpy(), y_pred, labels=nombres2)
            filas.append(
                {
                    "fold": fold.indice,
                    "modelo": nombre,
                    "n_val": len(yva),
                    **metricas,
                }
            )
            if nombre not in matrices:
                matrices[nombre] = np.zeros((2, 2), dtype=int)
            matrices[nombre] += confusion_matrix(
                yva.to_numpy(), y_pred, labels=nombres2
            )

    tabla = pd.DataFrame(filas)
    consolidado = (
        tabla.groupby("modelo")[["balanced_accuracy", "macro_f1"]]
        .mean()
        .round(4)
        .reset_index()
    )
    balance2 = abt2.groupby(["split", "clase"]).size().rename("n").reset_index()
    total2 = balance2.groupby("split")["n"].transform("sum")
    balance2["proporcion"] = (balance2["n"] / total2).round(4)
    return {
        "definicion": (
            "normotenso (PAS < 120 mmHg) vs no_normotenso (PAS >= 120 mmHg); "
            "colapsa elevada+hipertensa del esquema de 3 clases"
        ),
        "balance_2clases": balance2.sort_values(["split", "clase"]).to_dict(
            orient="records"
        ),
        "tabla_modelos": consolidado.to_dict(orient="records"),
        "matrices": {k: v.tolist() for k, v in matrices.items()},
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: evalúa clasificadores y guarda JSON + CSV."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloque 8: clasificación")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    args = p.parse_args(argv)

    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    res = evaluar_clasificadores(abt, args.target, semilla=args.semilla)
    pd.DataFrame(res["tabla_modelos"]).to_csv(
        cfg.out_base / "clasificacion_folds.csv", index=False
    )
    (cfg.out_base / "clasificacion.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(pd.DataFrame(res["tabla_modelos"]).to_string(index=False))
    print(f"[classification] Plan B: {res['plan_b']}")
    print(f"[classification] guardado en {cfg.out_base}/clasificacion.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
