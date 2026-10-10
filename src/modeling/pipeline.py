# =====================================================================
# FASE 3 | Bloque 3: Pipeline de preproceso, QC y filtraje (AASIM)
# ---------------------------------------------------------------------
# Encapsula, de forma serializable y sin fuga, la transformación de la
# ABT para el modelado:
#   * imputación con mediana del tren (por característica);
#   * escalado robusto (mediana/IQR) ajustado SOLO con entrenamiento;
#   * codificación one-hot de covariables discretas (categorías cerradas).
# Cualquier estadístico se aprende exclusivamente con ``train`` y se
# aplica sin modificación a val/test.
# Responsable: Rocha (ingeniería TI); reglas anti-fuga: Hidalgo.
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.modeling.config import SEMILLA_DEFAULT, ConfigFase3

#: Categorías cerradas de covariables discretas (alineadas con el esquema).
SEX_OBSERVABLE: tuple[str, ...] = ("M", "F")
SOURCE_OBSERVABLE: tuple[str, ...] = ("MIMIC", "VitalDB")


@dataclass(frozen=True)
class PipelineModelado:
    """Pipeline de preproceso serializable.

    Attributes:
        pasos: Nombres ordenados de los pasos (``imputacion_mediana``,
            ``escalado_robusto``, ``codificacion_onehot``).
        columnas_numericas: Columnas ``feat_*`` a transformar.
        columnas_categoricas: Columnas discretas a codificar one-hot.
        parametros: Estadísticos congelados del tren (JSON-serializable).
        recorte_iqr: Winsorización opcional del escalado robusto: los valores
            escalados se recortan a ``[-recorte, +recorte]`` (en unidades de
            IQR), controla colas pesadas de HRV/espectrales que
            desestabilizan los modelos lineales. ``None`` = sin recorte.
    """

    pasos: tuple[str, ...]
    columnas_numericas: tuple[str, ...]
    columnas_categoricas: tuple[str, ...]
    parametros: dict[str, Any]
    recorte_iqr: float | None = 5.0


def _columnas_feat(abt: pd.DataFrame) -> tuple[str, ...]:
    return tuple(sorted(c for c in abt.columns if c.startswith("feat_")))


def construir_pipeline(
    columnas: Sequence[str],
    categoricas: Sequence[str] = (),
    *,
    imputar: bool = True,
    escalar: bool = True,
    recorte_iqr: float | None = 5.0,
) -> PipelineModelado:
    """Define un pipeline declarativo (sin ajustar).

    Args:
        columnas: Columnas numéricas (``feat_*``) a transformar.
        categoricas: Columnas discretas a codificar one-hot.
        imputar: Si se imputa la mediana del tren.
        escalar: Si se aplica escalado robusto mediana/IQR del tren.
        recorte_iqr: Winsorización del escalado (``None`` = sin recorte).

    Returns:
        Pipeline no ajustado; ``parametros`` queda vacío hasta ``ajustar``.
    """
    pasos: list[str] = []
    if imputar:
        pasos.append("imputacion_mediana")
    if escalar:
        pasos.append("escalado_robusto")
    if categoricas:
        pasos.append("codificacion_onehot")
    return PipelineModelado(
        pasos=tuple(pasos),
        columnas_numericas=tuple(columnas),
        columnas_categoricas=tuple(categoricas),
        parametros={},
        recorte_iqr=recorte_iqr,
    )


def _particionar_numericas_categoricas(
    datos: pd.DataFrame, pipeline: PipelineModelado
) -> tuple[pd.DataFrame, pd.DataFrame]:
    falta_num = [c for c in pipeline.columnas_numericas if c not in datos.columns]
    falta_cat = [c for c in pipeline.columnas_categoricas if c not in datos.columns]
    if falta_num or falta_cat:
        raise ValueError(f"Faltan columnas en los datos: {falta_num + falta_cat}")
    # Coerción defensiva a numérico: las ABT pueden arrastrar celdas corruptas
    # (p. ej. strings de columnas contiguas). Lo no convertible se vuelve NaN
    # y lo gestiona la imputación (mediana del tren).
    numericas = pd.DataFrame(
        {
            col: pd.to_numeric(datos[col].astype(object), errors="coerce")
            for col in pipeline.columnas_numericas
        },
        index=datos.index,
    )
    categoricas = datos[list(pipeline.columnas_categoricas)].copy()
    return numericas, categoricas


def ajustar(pipeline: PipelineModelado, train: pd.DataFrame) -> PipelineModelado:
    """Ajusta los estadísticos del pipeline SOLO con el tren (train).

    Args:
        pipeline: Pipeline declarativo.
        train: Filas de entrenamiento (con columnas ``feat_*`` y las
            categóricas declaradas).

    Returns:
        Pipeline ajustado con ``parametros`` congelados.
    """
    numericas, _ = _particionar_numericas_categoricas(train, pipeline)

    params: dict[str, Any] = {}
    pasos = list(pipeline.pasos)
    if "imputacion_mediana" in pasos:
        medianas = numericas.median(axis=0)
        params["mediana_por_columna"] = medianas.to_dict()
    if "escalado_robusto" in pasos:
        q1, med, q3 = numericas.quantile([0.25, 0.50, 0.75]).to_numpy()
        iqr = np.where(q3 - q1 > 0.0, q3 - q1, 1.0)
        params["escalador_centro"] = med.tolist()
        params["escalador_iqr"] = iqr.tolist()
    if "codificacion_onehot" in pasos:
        codificador: dict[str, list[str]] = {}
        for col in pipeline.columnas_categoricas:
            categorias = list(train[col].astype("str").unique())
            codificador[col] = categorias
        params["categorias_onehot"] = codificador

    return replace(pipeline, parametros=params)


def transformar(pipeline: PipelineModelado, datos: pd.DataFrame) -> pd.DataFrame:
    """Aplica el pipeline ajustado (estadísticos congelados) a ``datos``.

    Returns:
        DataFrame con las features numéricas transformadas y, si procede,
        las columnas one-hot de covariables discretas.
    """
    numericas, categoricas = _particionar_numericas_categoricas(datos, pipeline)
    pasos = set(pipeline.pasos)

    if "imputacion_mediana" in pasos:
        mediana = pd.Series(pipeline.parametros["mediana_por_columna"])
        numericas = numericas.fillna(mediana)
    if "escalado_robusto" in pasos:
        centro = np.asarray(pipeline.parametros["escalador_centro"], dtype=float)
        iqr = np.asarray(pipeline.parametros["escalador_iqr"], dtype=float)
        numericas = (numericas.to_numpy(dtype=float) - centro) / iqr
        if pipeline.recorte_iqr is not None:
            limite = float(pipeline.recorte_iqr)
            numericas = np.clip(numericas, -limite, limite)

    salida = pd.DataFrame(
        numericas, index=datos.index, columns=list(pipeline.columnas_numericas)
    )

    if "codificacion_onehot" in pasos:
        codificador = pipeline.parametros["categorias_onehot"]
        for col in pipeline.columnas_categoricas:
            categorias = codificador.get(col, [])
            for cat in categorias:
                salida[f"{col}__{cat}"] = (
                    categoricas[col].astype("str") == cat
                ).astype(int)
    return salida


def guardar_pipeline(pipeline: PipelineModelado, ruta: Path) -> Path:
    """Serializa el pipeline (estadísticos del tren) a JSON."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pasos": list(pipeline.pasos),
        "columnas_numericas": list(pipeline.columnas_numericas),
        "columnas_categoricas": list(pipeline.columnas_categoricas),
        "parametros": pipeline.parametros,
        "recorte_iqr": pipeline.recorte_iqr,
    }
    ruta.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return ruta


def cargar_pipeline(ruta: Path) -> PipelineModelado:
    """Reconstruye un pipeline previamente ajustado y guardado."""
    payload = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return PipelineModelado(
        pasos=tuple(payload["pasos"]),
        columnas_numericas=tuple(payload["columnas_numericas"]),
        columnas_categoricas=tuple(payload["columnas_categoricas"]),
        parametros=payload["parametros"],
        recorte_iqr=payload.get("recorte_iqr", 5.0),
    )


# --------------------------------------------------------------------------
# QC de la ABT (Blocque 3): describe el target y las features antes de modelar
# --------------------------------------------------------------------------
def informe_qc(abt: pd.DataFrame, target: str) -> dict[str, Any]:
    """Reporte de calidad de la ABT: target, features, missing e inf.

    Args:
        abt: ABT cargada (una fila por ventana).
        target: Columna objetivo (p. ej. ``sbp_mmhg``).

    Returns:
        Diccionario anidado con: shape, describe del target, conteo de
        sujetos por partición, missing/infinitos por feature y vector de
        features.
    """
    features = _columnas_feat(abt)
    describe = abt[target].describe().to_dict()
    # Coerción defensiva a numérico (las ABT pueden arrastrar celdas corruptas
    # por defectos de la cadena de Fase 2: strings de columnas contiguas).
    numericas = pd.DataFrame(
        {
            col: pd.to_numeric(abt[col].astype(object), errors="coerce")
            for col in features
        },
        index=abt.index,
    )
    celdas_no_numericas = int(
        numericas.isna().sum().sum() - abt[list(features)].isna().sum().sum()
    )
    columnas_con_no_numerico = [
        c for c in features if (abt[c].isna() != numericas[c].isna()).any()
    ]
    missing_rows = int(numericas.isna().any(axis=1).sum())
    inf_rows = int(np.isinf(numericas.to_numpy(dtype=float)).any(axis=1).sum())
    sujetos_por_particion = abt.groupby("split")["subject_id"].nunique().to_dict()
    return {
        "n_filas": len(abt),
        "n_columnas": int(abt.shape[1]),
        "n_features": len(features),
        "n_sujetos": int(abt["subject_id"].nunique()),
        "n_sujetos_por_particion": {
            str(k): int(v) for k, v in sujetos_por_particion.items()
        },
        "describe_target": {
            k: (float(v) if isinstance(v, (int, float)) else v)
            for k, v in describe.items()
        },
        "ventanas_con_missing": int(numericas.isna().any(axis=1).sum()),
        "ventanas_con_inf": inf_rows,
        "missing_rows_abs": missing_rows,
        "missing_rows_rel": round(missing_rows / len(abt), 4) if len(abt) else 0.0,
        "celdas_no_numericas": celdas_no_numericas,
        "columnas_con_no_numerico": columnas_con_no_numerico,
        "features": features,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: construye el pipeline con train y vuelca informe QC + pipeline."""
    p = argparse.ArgumentParser(
        description="FASE 3 - Bloque 3: preproceso y QC de la ABT"
    )
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    args = p.parse_args(argv)

    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    train = abt[abt["split"] == "train"]
    features = _columnas_feat(abt)
    pipeline = construir_pipeline(features, categoricas=("source",))
    pipeline = ajustar(pipeline, train)

    guardar_pipeline(pipeline, cfg.out_base / "pipeline_fase3.json")
    qc = informe_qc(abt, args.target)
    (cfg.out_base / "informe_qc.json").write_text(
        json.dumps(qc, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(info_resumen_qc(qc), indent=2, ensure_ascii=False))
    print(f"[pipeline] guardado en {cfg.out_base / 'pipeline_fase3.json'}")
    print(f"[qc] informe en {cfg.out_base / 'informe_qc.json'}", flush=True)
    return 0


def info_resumen_qc(qc: dict[str, Any]) -> dict[str, Any]:
    """Versión corta del QC para imprimir en consola."""
    t = qc["describe_target"]
    return {
        "target": t,
        "n_sujetos": qc["n_sujetos"],
        "n_sujetos_por_particion": qc["n_sujetos_por_particion"],
        "ventanas_con_missing": qc["ventanas_con_missing"],
        "ventanas_con_inf": qc["ventanas_con_inf"],
    }


if __name__ == "__main__":
    sys.exit(main())
