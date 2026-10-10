"""Análisis del Data Quality Report sobre el corpus PulseDB v2.0 (Fase 2, AASIM).

Combina dos fuentes producidas por ``src/ingestion``:

* el catálogo completo (5 361 sujetos y 5 245 454 etiquetas de presión arterial), y
* la muestra de formas de onda procesada con el pipeline de la Fase 2
  (filtrado causal, compuerta de calidad RF4, características y latencia).

Genera las figuras del corpus real en ``figures/pulsedb/`` y un resumen numérico
(``resumen_pulsedb.json`` y ``tablas_pulsedb.md``) del que se toman las cifras del informe.

Responsables: Rocha (cómputo y figuras), Buitrago (lectura clínica de etiquetas y
sincronización) e Hidalgo (rechazo por subgrupos y representatividad).
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import stats

from src.reports.generate_visualizations import (
    C_BAD,
    C_INK,
    C_INK2,
    C_OK,
    _save,
    _style_axes,
    iso_distribution_check,
    plot_bp_histograms,
    plot_psd_comparison,
    plot_spearman_heatmap,
)

FS = 125.0
MS_POR_MUESTRA = 1e3 / FS

FloatArray = NDArray[np.float64]
GRUPOS_EDAD = [17, 39, 64, 200]
ETIQUETAS_EDAD = ["18-39", "40-64", "65 o más"]
# En la muestra de ondas el estrato 18-39 tiene menos de 5 sujetos: por la regla de
# supresión de celdas pequeñas (RNF1) se agrupa con 40-64.
GRUPOS_EDAD_MUESTRA = [17, 64, 200]
ETIQUETAS_EDAD_MUESTRA = ["18-64", "65 o más"]


def cargar_muestra(directorio: Path) -> pd.DataFrame:
    """Lee los CSV de la muestra descartando líneas truncadas por interrupciones."""
    filas: list[list[str]] = []
    cabecera: list[str] = []
    descartadas = 0
    for ruta in sorted(glob.glob(str(directorio / "ventanas*.csv"))):
        with open(ruta, newline="") as f:
            lector = csv.reader(f)
            cab = next(lector)
            cabecera = cabecera or cab
            for fila in lector:
                if len(fila) == len(cab):
                    filas.append(fila)
                else:
                    descartadas += 1
    df = pd.DataFrame(filas, columns=cabecera).replace("", pd.NA)
    texto = {"subject_id", "source", "biological_sex", "failed_criteria"}
    for c in df.columns:
        if c not in texto:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df.attrs["lineas_descartadas"] = descartadas
    return df


def _fila_md(valores: list[Any]) -> str:
    return "| " + " | ".join(str(v) for v in valores) + " |"


def tabla_md(df: pd.DataFrame, indice: str) -> str:
    """Convierte un ``DataFrame`` en tabla Markdown (sin depender de ``tabulate``)."""
    cab = [indice, *[str(c) for c in df.columns]]
    lineas = [_fila_md(cab), _fila_md(["---"] * len(cab))]
    for idx, fila in df.iterrows():
        lineas.append(_fila_md([idx, *fila.tolist()]))
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Catálogo completo
# ---------------------------------------------------------------------------
def resumen_catalogo(dir_cat: Path, out_fig: Path) -> tuple[dict[str, Any], str]:
    """Estadísticas de sujetos y etiquetas del corpus completo y figura de histogramas."""
    suj = pd.read_csv(dir_cat / "sujetos.csv")
    lab = pd.read_csv(dir_cat / "etiquetas_segmentos.csv.gz")
    lab = lab.merge(suj[["subject_id", "source", "Subj_Age"]], on="subject_id")
    res: dict[str, Any] = {}
    md: list[str] = []

    res["n_sujetos"] = len(suj)
    res["n_segmentos"] = len(lab)
    res["sujetos_menores_18"] = int((suj["Subj_Age"] < 18).sum())
    por_fuente = suj.groupby("source").agg(
        sujetos=("subject_id", "count"),
        segmentos=("n_segments", "sum"),
        seg_mediana=("n_segments", "median"),
        seg_max=("n_segments", "max"),
    )
    res["por_fuente"] = por_fuente.to_dict("index")
    md += ["### Sujetos y segmentos por fuente", tabla_md(por_fuente, "fuente"), ""]

    adultos = suj[suj["Subj_Age"] >= 18].copy()
    adultos["grupo_edad"] = pd.cut(
        adultos["Subj_Age"], GRUPOS_EDAD, labels=ETIQUETAS_EDAD
    )
    comp = (
        adultos.groupby(["source", "grupo_edad", "biological_sex"], observed=True)
        .size()
        .unstack(["biological_sex"])
        .fillna(0)
        .astype(int)
    )
    comp.index = [f"{a} / {b}" for a, b in comp.index]
    md += [
        "### Composición de adultos (fuente / edad; F y M)",
        tabla_md(comp, "estrato"),
        "",
    ]
    res["adultos"] = len(adultos)
    res["edad_adultos"] = (
        adultos.groupby("source")["Subj_Age"].describe().round(1).to_dict("index")
    )
    res["sexo_por_fuente"] = (
        suj.groupby(["source", "biological_sex"]).size().unstack().to_dict("index")
    )
    res["disponibilidad_bmi"] = {
        f: float(1.0 - g["Subj_BMI"].isna().mean()) for f, g in suj.groupby("source")
    }
    res["bmi_vital"] = (
        suj[suj["source"] == "VitalDB"]["Subj_BMI"].describe().round(1).to_dict()
    )

    sbp = lab["sbp_mmhg"].to_numpy(float)
    dbp = lab["dbp_mmhg"].to_numpy(float)
    est = (
        lab.groupby("source")[["sbp_mmhg", "dbp_mmhg"]]
        .describe(percentiles=[0.01, 0.5, 0.99])
        .round(1)
    )
    res["estadisticas_etiquetas"] = {
        f: {
            v: {
                k: float(est.loc[f, (v, k)])
                for k in ("mean", "std", "min", "1%", "50%", "99%", "max")
            }
            for v in ("sbp_mmhg", "dbp_mmhg")
        }
        for f in est.index
    }
    pas, pad = lab["sbp_mmhg"], lab["dbp_mmhg"]
    fuera = {
        "PAS < 70": int((pas < 70).sum()),
        "PAS > 240": int((pas > 240).sum()),
        "PAD < 40": int((pad < 40).sum()),
        "PAD > 140": int((pad > 140).sum()),
        "PP < 20": int(((pas - pad) < 20).sum()),
    }
    excl = (pas < 70) | (pas > 240) | (pad < 40) | (pad > 140) | ((pas - pad) < 20)
    res["censura_catalogo"] = {
        "por_condicion": fuera,
        "excluidas": int(excl.sum()),
        "fraccion": float(excl.mean()),
        "fraccion_por_fuente": excl.groupby(lab["source"]).mean().to_dict(),
    }
    iso_all = iso_distribution_check(sbp, dbp)
    md += [
        "### Cuotas ISO 81060-2 (corpus completo)",
        iso_all.round(4).to_string(index=False),
        "",
    ]
    res["cuotas_iso"] = {"todo": iso_all.round(4).to_dict("records")}
    for f in ("MIMIC", "VitalDB"):
        sub = lab[lab["source"] == f]
        res["cuotas_iso"][f] = (
            iso_distribution_check(
                sub["sbp_mmhg"].to_numpy(float), sub["dbp_mmhg"].to_numpy(float)
            )
            .round(4)
            .to_dict("records")
        )
    ok = ~excl.to_numpy()
    iso_adm = iso_distribution_check(sbp[ok], dbp[ok])
    res["cuotas_iso"]["admisibles"] = iso_adm.round(4).to_dict("records")
    md += [
        "### Cuotas ISO tras la censura clínica",
        iso_adm.round(4).to_string(index=False),
        "",
    ]
    res["spearman_pas_pad"] = float(stats.spearmanr(sbp[::50], dbp[::50]).statistic)

    seg = suj.sort_values("n_segments", ascending=False)
    res["concentracion_top1pct"] = float(
        seg["n_segments"].head(max(1, len(seg) // 100)).sum() / seg["n_segments"].sum()
    )
    res["segmentos_por_sujeto"] = suj["n_segments"].describe().round(1).to_dict()

    rutas = plot_bp_histograms(
        sbp[ok], dbp[ok], out_fig, stem="histograma_pas_pad_pulsedb"
    )
    res["figuras"] = [str(r) for r in rutas]
    return res, "\n".join(md)


# ---------------------------------------------------------------------------
# Muestra de formas de onda
# ---------------------------------------------------------------------------
def resumen_muestra(
    d: pd.DataFrame, dir_muestra: Path, out_fig: Path
) -> tuple[dict[str, Any], str]:
    """Resumen de señal, calidad, sincronización, características y latencia."""
    res: dict[str, Any] = {}
    md: list[str] = []
    d = d.copy()
    d["lag_ms"] = d["abp_lag_samples"] * MS_POR_MUESTRA
    d["grupo_edad"] = pd.cut(
        d["age"], GRUPOS_EDAD_MUESTRA, labels=ETIQUETAS_EDAD_MUESTRA
    )
    d["estrato_pas"] = pd.cut(
        d["sbp_mmhg"],
        [0, 100, 140, 160, 400],
        labels=["<= 100", "101-139", "140-159", ">= 160"],
    )
    res["ventanas"] = len(d)
    res["sujetos"] = int(d["subject_id"].nunique())
    res["lineas_descartadas"] = int(d.attrs.get("lineas_descartadas", 0))
    res["por_fuente"] = (
        d.groupby("source")
        .agg(sujetos=("subject_id", "nunique"), ventanas=("subject_id", "size"))
        .to_dict("index")
    )
    res["ventanas_por_sujeto"] = (
        d.groupby("subject_id").size().describe().round(1).to_dict()
    )
    res["motivo_censura_etiquetas"] = {
        int(k): int(v) for k, v in d["label_reason_code"].value_counts().items()
    }
    res["include_flag"] = {
        int(k): int(v) for k, v in d["include_flag"].value_counts().items()
    }
    res["ppg_abp_corr"] = (
        d.groupby("source")["ppg_abp_corr"].describe().round(3).to_dict("index")
    )

    # Sincronización ABP - ECG (S3)
    lag = (
        d.groupby("source")["lag_ms"]
        .describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
        .round(0)
    )
    res["retardo_abp_ms"] = lag.to_dict("index")
    res["retardo_fuera_150ms"] = float((d["lag_ms"].abs() > 150).mean())
    cambios = (
        d.sort_values(["subject_id", "win_index"])
        .groupby("subject_id")["abp_lag_samples"]
        .apply(lambda s: float((np.sign(s).diff().abs() > 0).mean()))
    )
    res["cambio_signo_lag_dentro_sujeto"] = float(cambios.mean())
    md += ["### Retardo ABP (ms) por fuente", tabla_md(lag, "fuente"), ""]

    # Señal cruda
    res["senal_cruda"] = (
        d.groupby("source")[["raw_std_mv", "raw_ptp_mv"]]
        .median()
        .round(3)
        .to_dict("index")
    )
    res["fraccion_flatline_mayor_0"] = float((d["flatline_fraction"] > 0).mean())
    det = d[d["mains_detected"] == 1]
    res["red_detectada_fraccion"] = (
        d.groupby("source")["mains_detected"].mean().round(3).to_dict()
    )
    res["red_frecuencias"] = {
        f"{int(k)}": int(v)
        for k, v in det["mains_hz"].round(0).value_counts().sort_index().items()
    }

    # Calidad
    q = d.groupby("source")[["bsqi", "ksqi", "psqi", "ssqi"]].median().round(2)
    res["sqi_medianas"] = q.to_dict("index")
    md += ["### Medianas de los SQI por fuente", tabla_md(q, "fuente"), ""]
    res["rechazo_global"] = float(d["quality_flag"].mean())
    res["rechazo_por_fuente"] = (
        d.groupby("source")["quality_flag"].mean().round(4).to_dict()
    )
    motivos = d[d["quality_flag"] == 1]["failed_criteria"].value_counts()
    res["motivos_rechazo"] = {str(k): int(v) for k, v in motivos.items()}
    sub_rows = []
    for nombre, col in (
        ("fuente", "source"),
        ("sexo", "biological_sex"),
        ("edad", "grupo_edad"),
        ("estrato PAS", "estrato_pas"),
    ):
        g = d.groupby(col, observed=True).agg(
            sujetos=("subject_id", "nunique"),
            ventanas=("subject_id", "size"),
            rechazo=("quality_flag", "mean"),
            psqi_mediana=("psqi", "median"),
        )
        for idx, fila in g.iterrows():
            sub_rows.append(
                {
                    "dimensión": nombre,
                    "subgrupo": idx,
                    "sujetos": int(fila["sujetos"]),
                    "ventanas": int(fila["ventanas"]),
                    "rechazo (%)": round(100 * fila["rechazo"], 1),
                    "pSQI mediana": round(float(fila["psqi_mediana"]), 3),
                }
            )
    sub = pd.DataFrame(sub_rows).set_index("dimensión")
    res["rechazo_por_subgrupo"] = sub.reset_index().to_dict("records")
    md += ["### Rechazo por subgrupo", tabla_md(sub, "dimensión"), ""]
    ed = sub[sub["subgrupo"].isin(ETIQUETAS_EDAD_MUESTRA)]
    res["cociente_rechazo_edad"] = float(
        ed["rechazo (%)"].max() / max(ed["rechazo (%)"].min(), 1e-9)
    )
    por_suj = d.groupby("subject_id")["quality_flag"].mean()
    res["sujetos_rechazo_mayor_30"] = int((por_suj > 0.30).sum())
    res["sujetos_rechazo_90_o_mas"] = int((por_suj >= 0.90).sum())
    res["sujetos_sin_rechazo"] = int((por_suj == 0).sum())
    res["rechazo_por_sujeto_cuantiles"] = (
        por_suj.quantile([0.25, 0.5, 0.75, 0.9]).round(3).to_dict()
    )
    f1 = d["rpeak_f1_vs_pulsedb"]
    res["f1_picos_r"] = {
        "mediana": float(f1.median()),
        "menor_0_9_todas": float((f1 < 0.9).mean()),
        "menor_0_9_aceptadas": float((f1[d["quality_flag"] == 0] < 0.9).mean()),
        "menor_0_9_rechazadas": float((f1[d["quality_flag"] == 1] < 0.9).mean()),
        "mediana_rechazadas": float(f1[d["quality_flag"] == 1].median()),
    }
    res["censura_vs_rechazo"] = {
        "etiqueta_censurada_y_rechazada": int(
            ((d["label_reason_code"] > 0) & (d["quality_flag"] == 1)).sum()
        ),
        "etiqueta_censurada": int((d["label_reason_code"] > 0).sum()),
    }
    utiles = (d["quality_flag"] == 0) & (d["label_reason_code"] == 0)
    res["perdida_neta_muestra"] = float(1.0 - utiles.mean())
    res["rechazo_por_criterio"] = {
        "bSQI": int(d["failed_criteria"].fillna("").str.contains("bSQI").sum()),
        "kSQI": int(d["failed_criteria"].fillna("").str.contains("kSQI").sum()),
        "pSQI": int(d["failed_criteria"].fillna("").str.contains("pSQI").sum()),
        "mas_de_uno": int(d["failed_criteria"].fillna("").str.contains(r"\|").sum()),
    }
    res["red_por_fuente_hz"] = {
        str(f): {
            str(int(k)): int(v)
            for k, v in g[g["mains_detected"] == 1]["mains_hz"]
            .round(0)
            .value_counts()
            .sort_index()
            .items()
        }
        for f, g in d.groupby("source")
    }

    # Características
    a = d[d["quality_flag"] == 0]
    res["aceptadas"] = len(a)
    res["fc_aceptadas"] = (
        a["hr_bpm"].describe(percentiles=[0.05, 0.5, 0.95]).round(1).to_dict()
    )
    feat = [c for c in d.columns if c.startswith("feat_")]
    nan = a[feat].isna().mean().sort_values(ascending=False)
    res["nan_caracteristicas"] = {
        k: round(float(v), 3) for k, v in nan[nan > 0].items()
    }
    res["morfologia"] = {
        c: a[c].describe(percentiles=[0.05, 0.5, 0.95]).round(0).to_dict()
        for c in (
            "feat_qrs_duration_ms",
            "feat_pr_interval_ms",
            "feat_qt_interval_ms",
            "feat_qtc_bazett_ms",
        )
    }
    pr = a["feat_pr_interval_ms"].dropna()
    res["pr_en_limite_busqueda"] = float((pr >= pr.max() - 1e-6).mean())
    res["pr_maximo_ms"] = float(pr.max())
    res["spearman_fc"] = {
        "pas": float(a[["hr_bpm", "sbp_mmhg"]].corr(method="spearman").iloc[0, 1]),
        "pad": float(a[["hr_bpm", "dbp_mmhg"]].corr(method="spearman").iloc[0, 1]),
    }
    corr = []
    for c in feat:
        ok = a[c].notna()
        if ok.sum() > 50 and a.loc[ok, c].nunique() > 2:
            corr.append(
                (
                    c,
                    float(
                        stats.spearmanr(a.loc[ok, c], a.loc[ok, "sbp_mmhg"]).statistic
                    ),
                    float(
                        stats.spearmanr(a.loc[ok, c], a.loc[ok, "dbp_mmhg"]).statistic
                    ),
                )
            )
    corr_df = pd.DataFrame(
        corr, columns=["característica", "rho_PAS", "rho_PAD"]
    ).set_index("característica")
    top = (
        corr_df.reindex(corr_df.abs().max(axis=1).sort_values(ascending=False).index)
        .head(8)
        .round(3)
    )
    res["spearman_top"] = top.reset_index().to_dict("records")
    res["spearman_max_abs"] = float(corr_df.abs().max().max())
    md += [
        "### Mayores correlaciones de Spearman (ventanas aceptadas)",
        tabla_md(top, "característica"),
        "",
    ]

    # Latencia
    lat = d["latency_ms"].dropna()
    res["latencia_ms"] = {
        "media": float(lat.mean()),
        "p50": float(lat.median()),
        "p95": float(lat.quantile(0.95)),
        "p99": float(lat.quantile(0.99)),
        "max": float(lat.max()),
    }

    # Figuras
    figs: list[str] = []
    dir_npy = dir_muestra / "ventanas_npy"
    acept = [np.load(p) for p in sorted(dir_npy.glob("*_aceptadas.npy"))]
    rech = [np.load(p) for p in sorted(dir_npy.glob("*_rechazadas.npy"))]
    if acept and rech:
        figs += [
            str(p)
            for p in plot_psd_comparison(
                np.concatenate(acept),
                np.concatenate(rech),
                FS,
                out_fig,
                mains_hz=60.0,
                stem="psd_aceptadas_vs_rechazadas_pulsedb",
            )
        ]
        res["psd_ventanas"] = {
            "aceptadas": int(sum(len(x) for x in acept)),
            "rechazadas": int(sum(len(x) for x in rech)),
        }
    figs += [str(p) for p in _plot_lag(d, out_fig)]
    figs += [str(p) for p in _plot_rechazo(sub, out_fig)]
    figs += [
        str(p)
        for p in plot_spearman_heatmap(
            a[feat].dropna(axis=1, how="all"),
            a["sbp_mmhg"].to_numpy(float),
            a["dbp_mmhg"].to_numpy(float),
            out_fig,
            stem="correlacion_spearman_pulsedb",
        )
    ]
    res["figuras"] = figs
    return res, "\n".join(md)


def _plot_lag(d: pd.DataFrame, out_fig: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    bins = np.arange(-800, 801, 16)
    for fuente, color in (("MIMIC", C_OK), ("VitalDB", C_BAD)):
        x = d.loc[d["source"] == fuente, "lag_ms"].dropna()
        ax.hist(
            x,
            bins=bins,
            color=color,
            alpha=0.62,
            label=f"{fuente} (n = {len(x)})",
            edgecolor="white",
            linewidth=0.5,
        )
    ax.axvspan(-150, 150, color="#efeeea", zorder=0)
    ax.axvline(150, color=C_INK2, linestyle="--", linewidth=1.0)
    ax.axvline(-150, color=C_INK2, linestyle="--", linewidth=1.0)
    ax.text(
        0,
        ax.get_ylim()[1] * 0.93,
        "tolerancia +-150 ms",
        ha="center",
        fontsize=8,
        color=C_INK2,
    )
    ax.set_xlabel("Retardo ABP (campo ABP_Lag, ms a 125 Hz)", fontsize=9)
    ax.set_ylabel("Ventanas (n)", fontsize=9)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(
        "Retardo ABP por ventana frente a la tolerancia de sincronización",
        fontsize=10,
        color=C_INK,
        loc="left",
    )
    _style_axes(ax)
    fig.tight_layout()
    return _save(fig, out_fig, "retardo_abp_pulsedb", False)


def _plot_rechazo(sub: pd.DataFrame, out_fig: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    df = sub.reset_index()
    etiquetas = [
        f"{r['dimensión']}: {r['subgrupo']}\n(n = {r['ventanas']})"
        for _, r in df.iterrows()
    ]
    y = np.arange(len(df))[::-1]
    ax.barh(y, df["rechazo (%)"], color=C_BAD, height=0.62)
    for yi, v in zip(y, df["rechazo (%)"], strict=True):
        ax.text(v + 1, yi, f"{v:.1f} %", va="center", fontsize=7.5, color=C_INK)
    ax.axvline(30, color=C_INK2, linestyle="--", linewidth=1.0)
    ax.text(
        30.6, y.max() + 0.7, "alerta de auditoría (30 %)", fontsize=7.5, color=C_INK2
    )
    ax.set_yticks(y, etiquetas, fontsize=7)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Ventanas rechazadas por la compuerta RF4 (%)", fontsize=9)
    ax.set_title(
        "Rechazo de señal por subgrupo (muestra de PulseDB)",
        fontsize=10,
        color=C_INK,
        loc="left",
    )
    _style_axes(ax)
    fig.tight_layout()
    return _save(fig, out_fig, "rechazo_por_subgrupo_pulsedb", False)


# --------------------------------------------------------------------------
# Figuras del resumen exploratorio (migradas del cuaderno)
# --------------------------------------------------------------------------
def plot_bp_joint_and_retention(
    sbp: FloatArray,
    dbp: FloatArray,
    pulse_pressure: FloatArray,
    subject_ids: Sequence[str],
    include_flag: FloatArray,
    out_fig: Path,
    *,
    stem: str = "resumen_exploratorio_pulsedb",
) -> list[Path]:
    """Panel de tres vistas del resumen exploratorio de etiquetas por ventana.

    Migra las visualizaciones de las celdas 6-7 del cuaderno
    (``src/Pruebas_jupyter/Mi_cuaderno.ipynb``) a un módulo reproducible:

    1. densidad conjunta PAS vs PAD (KDE) de las ventanas válidas;
    2. histograma de la presión de pulso (PAS - PAD) con su media;
    3. porcentaje de ventanas retenidas por sujeto.

    Advertencia: ``include_flag`` es la bandera propia de PulseDB y **no** la
    compuerta SQI/RF4 del proyecto (que rechaza ~45.7 % de la muestra); la
    retención de este panel no debe confundirse con la del DQR.

    Args:
        sbp: PAS de referencia (mmHg).
        dbp: PAD de referencia (mmHg).
        pulse_pressure: Presión de pulso (mmHg).
        subject_ids: Identificador de sujeto por ventana.
        include_flag: Bandera de inclusión por ventana.
        out_fig: Directorio de salida.
        stem: Nombre base del archivo sin extensión.
    """
    raise NotImplementedError(
        "Pendiente: KDE conjunta, histograma de PP y retención por sujeto"
    )


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--catalogo", type=Path, default=Path("data/processed/pulsedb_catalogo")
    )
    p.add_argument(
        "--muestra", type=Path, default=Path("data/processed/pulsedb_muestra")
    )
    p.add_argument("--out", type=Path, default=Path("figures/pulsedb"))
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    res_cat, md_cat = resumen_catalogo(args.catalogo, args.out)
    res_mue, md_mue = resumen_muestra(
        cargar_muestra(args.muestra), args.muestra, args.out
    )
    resumen = {"catalogo": res_cat, "muestra": res_mue}
    (args.out / "resumen_pulsedb.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False, default=float)
    )
    (args.out / "tablas_pulsedb.md").write_text(md_cat + "\n\n" + md_mue)

    # Impresión compacta de los resultados para verificación en consola.
    c, m = res_cat, res_mue
    print(f"Resumen escrito en {args.out}")
    print("\n== Resumen Fase 2 (datos reales) ==")
    print(
        f"[catálogo] {c['n_sujetos']} sujetos | {c['n_segmentos']} segmentos "
        f"| adultos >=18: {c['adultos']}"
    )
    print(
        "[catálogo] por fuente: "
        + "; ".join(f"{k}: {v['sujetos']} sujetos" for k, v in c["por_fuente"].items())
    )
    print(
        f"[muestra] {m['ventanas']} ventanas | {m['sujetos']} sujetos "
        f"| {m['lineas_descartadas']} líneas irregulares (interrupción)"
    )
    print(f"[muestra] rechazo por calidad (quality_flag): {m['rechazo_global']:.1%}")
    print(
        "[muestra] por fuente: "
        + "; ".join(
            f"{k}: {v['ventanas']} ventanas / {v['sujetos']} sujetos"
            for k, v in m["por_fuente"].items()
        )
    )
    if m.get("motivo_censura_etiquetas"):
        print(
            "[muestra] etiquetas censuradas (por código): "
            + json.dumps(m["motivo_censura_etiquetas"])
        )
    print(
        f"[muestra] retardo ABP fuera de ±150 ms: {m.get('retardo_fuera_150ms', 0):.1%}"
    )
    print("== fin resumen ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
