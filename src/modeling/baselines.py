# =====================================================================
# FASE 3 | Bloque 6: Modelos base y pruebas de fuga (AASIM)
# ---------------------------------------------------------------------
# Baselines interpretables para una referencia honesta antes de los
# modelos avanzados:
#   * regresión: Dummy (media), Ridge, SVR;
#   * clasificación: Dummy, Regresión Logística, Naive Bayes, SVM.
# Además ejecuta las **pruebas de fuga** con Random Forest:
#   * split aleatorio (fugado, ventanas del mismo sujeto en train y val);
#   * split por sujeto (honesto);
#   * label-shuffle (control: sin relación señal-objetivo).
# Se ajustan SOLO con ``train`` y se evalúan sobre ``val``.
# Responsable: Rocha (ingeniería TI); lectura clínica: Buitrago.
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.modeling.config import SEMILLA_DEFAULT, ConfigFase3


@dataclass(frozen=True)
class ResultadoModelo:
    """Resultado trazable de un modelo entrenado y evaluado.

    Attributes:
        nombre: Identificador del modelo.
        tarea: ``regresion`` o ``clasificacion``.
        metrica_principal: Nombre de la métrica principal.
        valor: Valor de la métrica principal.
        metricas: Compendio de métricas (adicionales).
        n_train: Número de ventanas de entrenamiento.
        n_val: Número de ventanas de validación.
        params: Hiperparámetros usados.
        semilla: Semilla de la corrida.
    """

    nombre: str
    tarea: str
    metrica_principal: str
    valor: float
    metricas: dict[str, float]
    n_train: int
    n_val: int
    params: dict[str, Any]
    semilla: int


def modelos_baseline(tarea: str) -> dict[str, Any]:
    """Devuelve los estimadores base sin entrenar para la ``tarea`` indicada.

    Returns:
        Dict ``nombre -> clase`` (instanciado con ``random_state=semilla`` se
        hace en ``entrenar_baselines`` para mantener una semilla única).
    """
    from sklearn.dummy import DummyClassifier, DummyRegressor
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.naive_bayes import GaussianNB
    from sklearn.svm import SVC, SVR

    if tarea == "regresion":
        return {
            "Dummy": DummyRegressor(strategy="mean"),
            "Ridge": Ridge(),
            "SVR": SVR(),
        }
    return {
        "Dummy": DummyClassifier(strategy="most_frequent"),
        "LogReg": LogisticRegression(max_iter=2000),
        "NaiveBayes": GaussianNB(),
        "SVM": SVC(probability=False),
    }


def _split_train_val(
    abt: pd.DataFrame, semilla: int
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    train = abt[abt["split"] == "train"].copy()
    val = abt[abt["split"] == "val"].copy()
    col_features = sorted(c for c in abt.columns if c.startswith("feat_"))
    rng = np.random.RandomState(semilla)
    train = train.sample(frac=1.0, random_state=rng).reset_index(drop=True)
    return train, val, col_features


def preparar_target(
    abt: pd.DataFrame, target: str, tarea: str
) -> tuple[pd.DataFrame, str]:
    """Devuelve una ABT con el target listo para la tarea.

    En ``clasificacion`` el target continuo (PAS) se discretiza a 3 clases
    (normotenso/elevada/hipertensa) mediante
    ``src.modeling.classification.construir_clases`` y se devuelve en una
    columna nueva ``_clase``. En ``regresion`` se usa el target original.

    Returns:
        ``(abt_copia, nombre_columna_target)``.
    """
    abt2 = abt.copy()
    if tarea == "clasificacion":
        from src.modeling.classification import construir_clases

        abt2["_clase"] = construir_clases(abt2, target).astype(str)
        return abt2, "_clase"
    return abt2, target


def entrenar_baselines(
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    semilla: int = SEMILLA_DEFAULT,
) -> list[ResultadoModelo]:
    """Entrena y evalúa los baselines sobre train/val.

    Cada modelo se ajusta con imputación de mediana + escalado robusto
    aprendidos SOLO con train (en ``src.modeling.pipeline``).

    Returns:
        Lista de ``ResultadoModelo`` (una por modelo).
    """
    from src.modeling.pipeline import ajustar, construir_pipeline, transformar
    from src.modeling.validation import metricas_clasificacion, metricas_regresion

    abt2, target_uso = preparar_target(abt, target, tarea)
    train, val, col_features = _split_train_val(abt2, semilla)
    pipe = construir_pipeline(tuple(col_features))
    pipe = ajustar(pipe, train[col_features].assign(_subj=train["subject_id"]))
    Xtr = transformar(pipe, train[col_features])
    ytr = train[target_uso].to_numpy(dtype=float)
    Xva = transformar(pipe, val[col_features])
    yva = val[target_uso].to_numpy(dtype=float)

    resultados: list[ResultadoModelo] = []
    for nombre, est_fabrica in modelos_baseline(tarea).items():
        est = est_fabrica
        if "random_state" in est.get_params():
            est.set_params(random_state=semilla)
        est.fit(Xtr, train[target_uso] if tarea == "clasificacion" else ytr)
        y_pred = est.predict(Xva)
        metricas = (
            metricas_regresion(yva, y_pred)
            if tarea == "regresion"
            else metricas_clasificacion(val[target_uso].to_numpy(), y_pred)
        )
        principal = "mae" if tarea == "regresion" else "macro_f1"
        resultados.append(
            ResultadoModelo(
                nombre=nombre,
                tarea=tarea,
                metrica_principal=principal,
                valor=float(metricas[principal]),
                metricas=metricas,
                n_train=len(Xtr),
                n_val=len(Xva),
                params=_parametros_publicos(est),
                semilla=semilla,
            )
        )
    return resultados


def _parametros_publicos(est: Any) -> dict[str, Any]:
    """Extrae los parámetros del estimador compatibles con JSON."""
    if not hasattr(est, "get_params"):
        return {}
    try:
        p = est.get_params()
        return {
            k: (str(v) if not isinstance(v, (int, float, str, bool, type(None))) else v)
            for k, v in p.items()
        }
    except Exception:  # pragma: no cover - defensivo  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------
# Pruebas de fuga (Bloque 6): split aleatorio vs por sujeto vs shuffle
# --------------------------------------------------------------------------
def pruebas_fuga_modelo(
    abt: pd.DataFrame,
    target: str,
    semilla: int = SEMILLA_DEFAULT,
    n_estimators: int = 100,
) -> dict[str, Any]:
    """Compara RF bajo tres diseños para evidenciar la fuga.

    La brecha entre split aleatorio (fugado) y split por sujeto cuantifica
    cuánto del rendimiento aparente venía de reconocer al paciente. El
    label-shuffle debe quedar al nivel del Dummy (o peor).

    Returns:
        Dict con ``mae_por_diseño`` (mean de folds?) — aquí se usa un solo
        hold-out patient-wise sobre el 15 % de sujetos de ``train``.
    """
    from sklearn.ensemble import RandomForestRegressor

    from src.modeling.pipeline import ajustar, construir_pipeline, transformar

    rng = np.random.RandomState(semilla)
    train = abt[abt["split"] == "train"].copy()
    col_features = sorted(c for c in abt.columns if c.startswith("feat_"))

    # Hold-out patient-wise interno: 15 % de sujetos no vuelven a entrenar.
    sujetos = sorted(train["subject_id"].unique())
    rng.shuffle(sujetos)
    n_val = max(1, round(0.15 * len(sujetos)))
    val_sujetos = set(sujetos[:n_val])
    tr_sujetos = set(sujetos[n_val:])

    def preparar(sub: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        pipe = ajustar(
            construir_pipeline(tuple(col_features)),
            sub[col_features].assign(_subj=sub["subject_id"]),
        )
        X = transformar(pipe, sub[col_features]).to_numpy(dtype=float)
        y = sub[target].to_numpy(dtype=float)
        return X, y

    def mae(Xtr, ytr, Xva, yva) -> float:
        m = RandomForestRegressor(
            n_estimators=n_estimators, random_state=semilla, n_jobs=-1
        )
        m.fit(Xtr, ytr)
        return float(np.mean(np.abs(m.predict(Xva) - yva)))

    # Diseño 1: split ALEATORIO de ventanas (fugado).
    train_sh = train.sample(frac=1.0, random_state=rng).reset_index(drop=True)
    n_tr = round(0.85 * len(train_sh))
    Xtr1, ytr1 = preparar(train_sh.iloc[:n_tr])
    Xva1, yva1 = preparar(train_sh.iloc[n_tr:])
    mae_aleatorio = mae(Xtr1, ytr1, Xva1, yva1)

    # Diseño 2: split POR SUJETO (honesto).
    Xtr2, ytr2 = preparar(train[train["subject_id"].isin(tr_sujetos)])
    Xva2, yva2 = preparar(train[train["subject_id"].isin(val_sujetos)])
    mae_sujeto = mae(Xtr2, ytr2, Xva2, yva2)

    # Diseño 3: label-shuffle (sin relación señal-objetivo).
    m = RandomForestRegressor(
        n_estimators=n_estimators, random_state=semilla, n_jobs=-1
    )
    y_shuffled = rng.permutation(ytr2.copy())
    Xtr3, ytr3 = Xtr2.copy(), y_shuffled
    m.fit(Xtr3, ytr3)
    yva3 = yva2
    mae_shuffle = float(np.mean(np.abs(m.predict(Xva2) - yva3)))

    return {
        "mae_rf_split_aleatorio": mae_aleatorio,
        "mae_rf_split_sujeto": mae_sujeto,
        "mae_rf_label_shuffle": mae_shuffle,
        "brecha_al_sujeto_mmhg": round(mae_aleatorio - mae_sujeto, 3),
        "shuffle_vs_dummy": round(mae_shuffle, 3),
        "n_sujetos_train": len(tr_sujetos),
        "n_sujetos_val": len(val_sujetos),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: entrena baselines + pruebas de fuga y guarda CSV/JSON."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloque 6: baselines y fuga")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument(
        "--tarea", choices=("regresion", "clasificacion"), default="regresion"
    )
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    args = p.parse_args(argv)

    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    resultados = entrenar_baselines(abt, args.target, args.tarea, semilla=args.semilla)
    filas = [
        {
            "nombre": r.nombre,
            "tarea": r.tarea,
            "metrica_principal": r.metrica_principal,
            "valor": r.valor,
            **r.metricas,
            "n_train": r.n_train,
            "n_val": r.n_val,
            "semilla": r.semilla,
        }
        for r in resultados
    ]
    df = pd.DataFrame(filas)
    print(df.to_string(index=False))
    salida = cfg.out_base / "baselines.csv"
    df.to_csv(salida, index=False)
    print(f"[baselines] guardado en {salida}")

    if args.tarea == "regresion":
        fuga = pruebas_fuga_modelo(abt, args.target, semilla=args.semilla)
        print(json_fuga(fuga))
        (cfg.out_base / "pruebas_fuga.json").write_text(
            json.dumps(fuga, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    return 0


def json_fuga(fuga: dict[str, Any]) -> str:
    """Formateo legible de las pruebas de fuga."""
    from json import dumps

    return dumps(fuga, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
