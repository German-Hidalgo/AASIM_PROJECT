"""Visualizaciones clínicas y tablas estadísticas del Data Quality Report.

Proyecto AASIM - Fase 2.

Responsables
------------
* Implementación: Luis Carlos Rocha (Ingeniería TI).
* Criterios de lectura clínica de los histogramas y de Bland-Altman: Juan
  Manuel Buitrago (Validación Clínica).
* Lectura de rechazo de señal y equidad por sujeto: German Alberto Hidalgo
  (Ética y Pacientes).

Figuras (se guardan en ``figures/`` en PNG de 200 ppp y en SVG)
-----------------------------------------------------------------------
1. ``histograma_pas_pad``: densidad de PAS y PAD con las cuotas críticas de
   distribución poblacional de ANSI/AAMI/ISO 81060-2.
2. ``bland_altman_referencia``: diferencia intra-dispositivo frente a la media
   (Riesgo R3), con sesgo, límites de concordancia al 95 % y prueba de
   heterocedasticidad.
3. ``psd_aceptadas_vs_rechazadas``: densidad espectral de potencia de ventanas
   aceptadas frente a rechazadas por la compuerta RF4, con marcas de 0.5 Hz
   (deriva) y 50/60 Hz (red).
4. ``correlacion_spearman``: matriz de correlación no paramétrica entre las
   características de ECG y PAS/PAD.
5. ``rechazo_longitudinal``: porcentaje de ventanas descartadas por sujeto a
   lo largo de la grabación, con alerta al superar el 30 %.

Modo de verificación funcional
------------------------------
``--synthetic-demo`` genera las figuras 1-3 con datos sintéticos etiquetados
con la marca de agua "DATOS SINTÉTICOS - VERIFICACIÓN FUNCIONAL". Esas figuras
sirven únicamente para comprobar el formato y la lógica del script; no
constituyen evidencia clínica ni sustituyen a las figuras del corpus real.

Uso::

    python -m src.reports.generate_visualizations --synthetic-demo
    python -m src.reports.generate_visualizations \\
        --labels-csv data/processed/labels.csv --out figures
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import signal, stats

FloatArray = NDArray[np.float64]

# Paleta de referencia (modo claro): azul = aceptado, naranja = rechazado.
C_OK = "#2a78d6"
C_BAD = "#eb6834"
C_INK = "#0b0b0b"
C_INK2 = "#52514e"
C_GRID = "#e3e2dc"
C_ZONE = "#efeeea"

DPI = 200
WATERMARK = "DATOS SINTÉTICOS - VERIFICACIÓN FUNCIONAL"


# --------------------------------------------------------------------------
# Cuotas de distribución poblacional (ANSI/AAMI/ISO 81060-2)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Quota:
    """Cuota mínima de lecturas de referencia en un rango crítico."""

    label: str
    variable: str  # "sbp" | "dbp"
    direction: str  # "le" | "ge"
    limit: float
    min_fraction: float = 0.05


#: Rangos críticos parametrizados. Los valores numéricos deben contrastarse con
#: el texto vigente de la norma licenciada antes de la firma del DQR.
ISO_QUOTAS: tuple[Quota, ...] = (
    Quota("PAS <= 100 mmHg", "sbp", "le", 100.0),
    Quota("PAS >= 160 mmHg", "sbp", "ge", 160.0),
    Quota("PAD <= 60 mmHg", "dbp", "le", 60.0),
    Quota("PAD >= 100 mmHg", "dbp", "ge", 100.0),
)


def iso_distribution_check(
    sbp: FloatArray, dbp: FloatArray, quotas: tuple[Quota, ...] = ISO_QUOTAS
) -> pd.DataFrame:
    """Evalúa las cuotas de distribución de las etiquetas de referencia.

    Args:
        sbp: PAS de referencia admisibles (mmHg).
        dbp: PAD de referencia admisibles (mmHg).
        quotas: Rangos críticos y fracción mínima exigida.

    Returns:
        Tabla con la fracción observada, la mínima exigida y el veredicto.
    """
    data = {"sbp": np.asarray(sbp, dtype=float), "dbp": np.asarray(dbp, dtype=float)}
    rows = []
    for q in quotas:
        v = data[q.variable]
        frac = float(
            np.mean(v <= q.limit) if q.direction == "le" else np.mean(v >= q.limit)
        )
        rows.append(
            {
                "rango": q.label,
                "n": int(
                    np.sum(v <= q.limit)
                    if q.direction == "le"
                    else np.sum(v >= q.limit)
                ),
                "fraccion_observada": frac,
                "fraccion_minima": q.min_fraction,
                "cumple": bool(frac >= q.min_fraction),
            }
        )
    return pd.DataFrame(rows)


def label_statistics_table(sbp: FloatArray, dbp: FloatArray) -> pd.DataFrame:
    """Estadísticos univariados de PAS, PAD, PP y PAM (tabla del DQR).

    Incluye media, desviación estándar (ddof=1), P5, P25, P50, P75, P95, mínimo,
    máximo, asimetría y curtosis (exceso). La PAM se aproxima como
    ``PAD + (PAS - PAD) / 3``.
    """
    s, d = np.asarray(sbp, dtype=float), np.asarray(dbp, dtype=float)
    series = {"PAS": s, "PAD": d, "PP": s - d, "PAM": d + (s - d) / 3.0}
    rows = {}
    for name, v in series.items():
        p5, p25, p50, p75, p95 = np.percentile(v, [5, 25, 50, 75, 95])
        rows[name] = {
            "n": v.size,
            "media": v.mean(),
            "desv_est": v.std(ddof=1),
            "P5": p5,
            "P25": p25,
            "P50": p50,
            "P75": p75,
            "P95": p95,
            "min": v.min(),
            "max": v.max(),
            "asimetria": stats.skew(v),
            "curtosis_exceso": stats.kurtosis(v),
        }
    return pd.DataFrame(rows).T


# --------------------------------------------------------------------------
# Estilo
# --------------------------------------------------------------------------
def _style_axes(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_INK2)
    ax.tick_params(colors=C_INK2, labelsize=8)
    ax.grid(axis="y", color=C_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(C_INK2)
    ax.yaxis.label.set_color(C_INK2)


def _save(fig: plt.Figure, out_dir: Path, stem: str, watermark: bool) -> list[Path]:
    if watermark:
        fig.text(
            0.5,
            0.5,
            WATERMARK,
            ha="center",
            va="center",
            rotation=25,
            fontsize=17,
            color=C_INK2,
            alpha=0.16,
            weight="bold",
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{stem}.png", out_dir / f"{stem}.svg"]
    fig.savefig(paths[0], dpi=DPI, facecolor="white", bbox_inches="tight")
    fig.savefig(paths[1], facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return paths


# --------------------------------------------------------------------------
# Figura 1: histogramas de PAS/PAD con cuotas ISO 81060-2
# --------------------------------------------------------------------------
def plot_bp_histograms(
    sbp: FloatArray,
    dbp: FloatArray,
    out_dir: Path,
    watermark: bool = False,
    stem: str = "histograma_pas_pad",
) -> list[Path]:
    """Histogramas de PAS y PAD con zonas críticas y veredicto de cuota.

    Cada panel resalta las colas exigidas por la norma y rotula, con texto, la
    fracción observada y si cumple el mínimo (5 %); el veredicto nunca se
    comunica solo por color.
    """
    check = iso_distribution_check(sbp, dbp)
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.9), sharey=False)
    for ax, (var, data, xlab) in zip(
        axes,
        (
            ("sbp", sbp, "PAS de referencia (mmHg)"),
            ("dbp", dbp, "PAD de referencia (mmHg)"),
        ),
        strict=True,
    ):
        lo, hi = np.floor(data.min() / 5) * 5, np.ceil(data.max() / 5) * 5 + 5
        bins = np.arange(lo, hi, 5)
        ax.hist(data, bins=bins, color=C_OK, edgecolor="white", linewidth=1.0)
        sub = check[check["rango"].str.startswith("PAS" if var == "sbp" else "PAD")]
        verdicts = []
        for _, row in sub.iterrows():
            limit = float(row["rango"].split()[2])
            is_le = "<=" in row["rango"]
            ax.axvspan(
                lo if is_le else limit, limit if is_le else hi, color=C_ZONE, zorder=0
            )
            ax.axvline(limit, color=C_INK2, linestyle="--", linewidth=1.0)
            verdict = "cumple" if row["cumple"] else "NO cumple"
            verdicts.append(
                f"{row['rango']}: {100 * row['fraccion_observada']:.1f} % "
                f"(mín. 5 %) - {verdict}"
            )
        ax.set_title("\n".join(verdicts), fontsize=8, color=C_INK, loc="left")
        ax.set_xlabel(xlab, fontsize=9)
        ax.set_ylabel("Lecturas (n)", fontsize=9)
        ax.set_xlim(lo, hi)
        _style_axes(ax)
    fig.suptitle(
        "Distribución de las etiquetas de referencia y cuotas ANSI/AAMI/ISO 81060-2",
        fontsize=10.5,
        color=C_INK,
        x=0.02,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return _save(fig, out_dir, stem, watermark)


def _fmt_p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


# --------------------------------------------------------------------------
# Figura 2: Bland-Altman
# --------------------------------------------------------------------------
def bland_altman_statistics(a: FloatArray, b: FloatArray) -> dict[str, float]:
    """Sesgo, límites de concordancia al 95 % y heterocedasticidad.

    La heterocedasticidad se evalúa regresando ``|diferencia|`` sobre la media
    de cada par; una pendiente significativa indica error proporcional.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    diff, mean = a - b, (a + b) / 2.0
    bias, sd = float(diff.mean()), float(diff.std(ddof=1))
    lower, upper = bias - 1.96 * sd, bias + 1.96 * sd
    reg = stats.linregress(mean, np.abs(diff))
    return {
        "n": float(diff.size),
        "sesgo": bias,
        "desv_est_diferencias": sd,
        "limite_inferior": lower,
        "limite_superior": upper,
        "fraccion_dentro_limites": float(np.mean((diff >= lower) & (diff <= upper))),
        "pendiente_abs_diff_vs_media": float(reg.slope),
        "p_heterocedasticidad": float(reg.pvalue),
    }


def plot_bland_altman(
    a: FloatArray,
    b: FloatArray,
    out_dir: Path,
    label: str = "PAS (mmHg)",
    watermark: bool = False,
    stem: str = "bland_altman_referencia",
) -> tuple[list[Path], dict[str, float]]:
    """Diagrama de Bland-Altman de lecturas pareadas del comparador (R3)."""
    st = bland_altman_statistics(a, b)
    diff, mean = np.asarray(a) - np.asarray(b), (np.asarray(a) + np.asarray(b)) / 2.0
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    ax.scatter(
        mean, diff, s=16, color=C_OK, alpha=0.55, edgecolor="white", linewidth=0.4
    )
    xr = np.array([mean.min(), mean.max()])
    ax.hlines(st["sesgo"], *xr, color=C_INK, linewidth=1.4)
    for key in ("limite_superior", "limite_inferior"):
        ax.hlines(st[key], *xr, color=C_INK2, linestyle="--", linewidth=1.1)
    x_lab = xr[1]
    ax.text(
        x_lab,
        st["sesgo"],
        f"Sesgo {st['sesgo']:+.2f}",
        ha="right",
        va="bottom",
        fontsize=8,
        color=C_INK,
    )
    ax.text(
        x_lab,
        st["limite_superior"],
        f"+1.96 DE: {st['limite_superior']:+.2f}",
        ha="right",
        va="bottom",
        fontsize=8,
        color=C_INK2,
    )
    ax.text(
        x_lab,
        st["limite_inferior"],
        f"-1.96 DE: {st['limite_inferior']:+.2f}",
        ha="right",
        va="top",
        fontsize=8,
        color=C_INK2,
    )
    ax.set_xlabel(f"Media de las dos lecturas - {label}", fontsize=9)
    ax.set_ylabel(f"Diferencia (A - B) - {label}", fontsize=9)
    ax.set_title(
        f"Bland-Altman del comparador: {100 * st['fraccion_dentro_limites']:.1f} % "
        f"dentro de los límites\npendiente |dif| vs media = "
        f"{st['pendiente_abs_diff_vs_media']:+.3f} "
        f"({_fmt_p(st['p_heterocedasticidad'])})",
        fontsize=8.6,
        color=C_INK,
        loc="left",
    )
    _style_axes(ax)
    fig.tight_layout()
    return _save(fig, out_dir, stem, watermark), st


# --------------------------------------------------------------------------
# Figura 3: PSD aceptadas vs rechazadas
# --------------------------------------------------------------------------
def _mean_psd(
    segments: FloatArray, fs: float
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    freqs, psd = signal.welch(
        segments, fs=fs, nperseg=int(min(segments.shape[-1], 4 * fs)), axis=-1
    )
    return (
        freqs,
        np.median(psd, axis=0),
        np.percentile(psd, 25, axis=0),
        np.percentile(psd, 75, axis=0),
    )


def plot_psd_comparison(
    accepted: FloatArray,
    rejected: FloatArray,
    fs: float,
    out_dir: Path,
    mains_hz: float = 50.0,
    watermark: bool = False,
    stem: str = "psd_aceptadas_vs_rechazadas",
) -> list[Path]:
    """PSD mediana (rango intercuartílico sombreado) de ventanas aceptadas y rechazadas.

    Permite verificar visualmente la atenuación del notch en la frecuencia de
    red, la supresión de la deriva bajo 0.5 Hz y el corte a 45 Hz, así como el
    perfil espectral que desencadena el rechazo (pSQI).

    Args:
        accepted: Matriz ``(n_ventanas, n_muestras)`` con ``quality_flag = 0``.
        rejected: Matriz con ``quality_flag = 1``.
        fs: Frecuencia de muestreo (Hz).
        out_dir: Directorio de salida.
        mains_hz: Frecuencia de red a marcar (50 o 60 Hz).
        watermark: Agrega marca de agua de datos sintéticos.
        stem: Nombre base del archivo.
    """
    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    for data, color, name in (
        (accepted, C_OK, "Aceptadas (quality_flag = 0)"),
        (rejected, C_BAD, "Rechazadas (quality_flag = 1)"),
    ):
        f, med, q1, q3 = _mean_psd(data, fs)
        ax.fill_between(f, q1, q3, color=color, alpha=0.18, linewidth=0)
        ax.plot(f, med, color=color, linewidth=1.6, label=name)
    ax.set_yscale("log")
    x_max = min(80.0, fs / 2)
    ax.set_xlim(0, x_max)
    lows = []
    for data in (accepted, rejected):
        f, _, q1, _ = _mean_psd(data, fs)
        lows.append(q1[(f > 0) & (f <= x_max)].min())
    ax.set_ylim(bottom=10 ** np.floor(np.log10(min(lows)) - 0.3))
    y_top = ax.get_ylim()[1]
    for x, txt, ha in (
        (0.5, "0.5 Hz (deriva)", "left"),
        (45.0, "45 Hz (pasa-bajos)", "right"),
        (mains_hz, f"{mains_hz:.0f} Hz (red)", "left"),
    ):
        ax.axvline(x, color=C_INK2, linestyle=":", linewidth=1.0)
        ax.text(x, y_top, f" {txt} ", fontsize=7, color=C_INK2, ha=ha, va="top")
    ax.set_xlabel("Frecuencia (Hz)", fontsize=9)
    ax.set_ylabel("Densidad espectral de potencia (mediana y RIC)", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    ax.set_title(
        "PSD de ventanas aceptadas y rechazadas tras el filtrado",
        fontsize=10,
        color=C_INK,
        loc="left",
    )
    _style_axes(ax)
    fig.tight_layout()
    return _save(fig, out_dir, stem, watermark)


# --------------------------------------------------------------------------
# Figuras 4 y 5 (requieren tablas del corpus real)
# --------------------------------------------------------------------------
def plot_spearman_heatmap(
    features: pd.DataFrame,
    sbp: FloatArray,
    dbp: FloatArray,
    out_dir: Path,
    stem: str = "correlacion_spearman",
    watermark: bool = False,
) -> list[Path]:
    """Mapa de calor de correlación de Spearman entre características y PAS/PAD."""
    cols = list(features.columns)
    table = np.zeros((len(cols), 2))
    for i, c in enumerate(cols):
        ok = features[c].notna().to_numpy()
        table[i, 0] = stats.spearmanr(features[c][ok], np.asarray(sbp)[ok]).statistic
        table[i, 1] = stats.spearmanr(features[c][ok], np.asarray(dbp)[ok]).statistic
    fig, ax = plt.subplots(figsize=(4.2, max(3.0, 0.24 * len(cols) + 1.2)))
    im = ax.imshow(table, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks([0, 1], ["PAS", "PAD"], fontsize=8)
    ax.set_yticks(range(len(cols)), cols, fontsize=6.5)
    for i in range(len(cols)):
        for j in range(2):
            ax.text(
                j,
                i,
                f"{table[i, j]:+.2f}",
                ha="center",
                va="center",
                fontsize=6.5,
                color=C_INK,
            )
    fig.colorbar(im, ax=ax, fraction=0.06, label="rho de Spearman")
    ax.set_title("Correlación morfología-hemodinámica", fontsize=9, loc="left")
    fig.tight_layout()
    return _save(fig, out_dir, stem, watermark)


def plot_rejection_timeline(
    windows: pd.DataFrame,
    out_dir: Path,
    bin_s: float = 300.0,
    alert: float = 0.30,
    stem: str = "rechazo_longitudinal",
    watermark: bool = False,
) -> list[Path]:
    """Porcentaje de ventanas descartadas por sujeto a lo largo del tiempo.

    Args:
        windows: Columnas ``subject_id``, ``t_start_s`` y ``quality_flag``.
        out_dir: Directorio de salida.
        bin_s: Ancho del intervalo de agregación (s).
        alert: Umbral de auditoría individualizada (30 %).
    """
    w = windows.copy()
    w["bin"] = (w["t_start_s"] // bin_s).astype(int)
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    for sid, grp in w.groupby("subject_id"):
        rate = grp.groupby("bin")["quality_flag"].mean() * 100
        overall = grp["quality_flag"].mean()
        flagged = overall > alert
        ax.plot(
            rate.index * bin_s / 60,
            rate.values,
            color=C_BAD if flagged else C_OK,
            alpha=0.9 if flagged else 0.35,
            linewidth=1.6 if flagged else 0.9,
        )
        if flagged:
            ax.text(
                rate.index[-1] * bin_s / 60,
                rate.values[-1],
                f" {sid}",
                fontsize=7,
                color=C_INK,
                va="center",
            )
    ax.axhline(alert * 100, color=C_INK2, linestyle="--", linewidth=1.0)
    ax.text(
        ax.get_xlim()[0],
        alert * 100 + 1,
        "umbral de auditoría 30 %",
        fontsize=7.5,
        color=C_INK2,
        va="bottom",
    )
    ax.set_xlabel("Tiempo de grabación (min)", fontsize=9)
    ax.set_ylabel("Ventanas descartadas (%)", fontsize=9)
    ax.set_title(
        "Rechazo longitudinal por sujeto (naranja: sujetos sobre el umbral)",
        fontsize=10,
        loc="left",
        color=C_INK,
    )
    _style_axes(ax)
    fig.tight_layout()
    return _save(fig, out_dir, stem, watermark)


# --------------------------------------------------------------------------
# Figura: visor de una ventana ECG + ABP de PulseDB
# --------------------------------------------------------------------------
def plot_ecg_abp_window(
    ecg: FloatArray,
    abp: FloatArray,
    sbp: float,
    dbp: float,
    out_dir: Path,
    *,
    fs: float = 125.0,
    title: str = "",
    include_flag: float | None = None,
    stem: str = "ventana_ecg_abp",
    watermark: bool = False,
) -> list[Path]:
    """Panel doble ECG + presión invasiva para una ventana de PulseDB.

    Migra el visor exploratorio del cuaderno
    (``src/Pruebas_jupyter/Mi_cuaderno.ipynb``, ``inspeccionar_ventana``) a un
    módulo de reporte reproducible: en lugar de ``plt.show()`` guarda PNG y SVG
    en ``out_dir`` con el estilo del DQR.

    Panel superior: ECG crudo con los latidos de la ventana. Panel inferior:
    ABP continuo con líneas de PAS y PAD de referencia del segmento.

    Args:
        ecg: ECG crudo (mV).
        abp: ABP crudo (mmHg).
        sbp: PAS de referencia del segmento (mmHg).
        dbp: PAD de referencia del segmento (mmHg).
        out_dir: Directorio de salida.
        fs: Frecuencia de muestreo (Hz) para los ejes de tiempo.
        title: Título del panel; si está vacío se compone uno genérico.
        include_flag: Bandera de inclusión de PulseDB, solo para rotular; no es
            la compuerta SQI/RF4 del proyecto.
        stem: Nombre base del archivo sin extensión.
        watermark: Superpone la marca de "datos sintéticos" (verificación).
    """
    raise NotImplementedError(
        "Pendiente: construir el panel ECG/ABP y guardarlo con _save"
    )


# --------------------------------------------------------------------------
# Modo de verificación funcional con datos sintéticos
# --------------------------------------------------------------------------
def _synthetic_labels(
    n: int, rng: np.random.Generator
) -> tuple[FloatArray, FloatArray]:
    """Etiquetas sintéticas con colas hipo/hipertensas (cuotas cumplidas)."""
    grp = rng.choice(4, size=n, p=[0.16, 0.44, 0.16, 0.24])
    mu_s = np.array([92.0, 122.0, 150.0, 172.0])[grp]
    mu_d = np.array([56.0, 76.0, 92.0, 104.0])[grp]
    sbp = np.clip(rng.normal(mu_s, 9.0), 71, 239)
    dbp = np.clip(rng.normal(mu_d, 6.5), 41, 139)
    return sbp, dbp


def run_synthetic_demo(out_dir: Path) -> list[Path]:
    """Genera las figuras 1-3 con datos sintéticos rotulados como tales."""
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    import synthetic_ecg as se

    from src.preprocessing.filters import (
        FilterConfig,
        apply_filter_chain,
    )
    from src.sqi.quality_assessment import assess_window

    rng = np.random.default_rng(7)
    fs = 250.0
    sbp, dbp = _synthetic_labels(800, rng)
    paths = plot_bp_histograms(sbp, dbp, out_dir, watermark=True)

    a = rng.normal(125, 22, 300)
    b = a + rng.normal(1.2, 3.0 + 0.03 * (a - 125), 300)
    p2, _ = plot_bland_altman(a, b, out_dir, "PAS (mmHg)", watermark=True)
    paths += p2

    cfg = FilterConfig(fs)
    acc: list[FloatArray] = []
    rej: list[FloatArray] = []
    for i in range(24):
        rec = se.make_ecg(10.0, fs, hr_bpm=float(rng.uniform(55, 95)), seed=100 + i)
        clean = se.contaminate(rec.ecg_mv, fs, seed=i)
        noisy = se.make_corrupted(rec.ecg_mv, fs, seed=i) if i % 3 == 0 else clean
        for raw in (clean, noisy):
            filt = apply_filter_chain(raw, cfg).signal[int(2 * fs) :]
            (rej if assess_window(filt, fs).quality_flag else acc).append(filt)
    n = min(len(acc), len(rej))
    if n == 0:
        raise RuntimeError("La demostración sintética no produjo ambos grupos")
    paths += plot_psd_comparison(
        np.vstack(acc), np.vstack(rej), fs, out_dir, watermark=True
    )
    return paths


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""
    p = argparse.ArgumentParser(description="Visualizaciones del DQR de AASIM (Fase 2)")
    p.add_argument("--out", type=Path, default=Path("figures"))
    p.add_argument(
        "--synthetic-demo",
        action="store_true",
        help="Genera figuras 1-3 con datos sintéticos (solo verificación funcional).",
    )
    p.add_argument(
        "--labels-csv",
        type=Path,
        help="CSV con ref_systolic_bp y ref_diastolic_bp (etiquetas admisibles).",
    )
    p.add_argument(
        "--pairs-csv",
        type=Path,
        help="CSV con device_a y device_b (lecturas pareadas del comparador).",
    )
    p.add_argument(
        "--windows-csv", type=Path, help="CSV con subject_id, t_start_s y quality_flag."
    )
    p.add_argument(
        "--print-tables",
        action="store_true",
        help="Imprime en Markdown las tablas estadísticas de --labels-csv.",
    )
    args = p.parse_args(argv)

    written: list[Path] = []
    if args.synthetic_demo:
        written += run_synthetic_demo(args.out / "verificacion_sintetica")
    if args.labels_csv:
        lab = pd.read_csv(args.labels_csv)
        sbp = lab["ref_systolic_bp"].to_numpy(float)
        dbp = lab["ref_diastolic_bp"].to_numpy(float)
        written += plot_bp_histograms(sbp, dbp, args.out)
        if args.print_tables:
            print(label_statistics_table(sbp, dbp).round(2).to_string())
            print(iso_distribution_check(sbp, dbp).round(4).to_string(index=False))
    if args.pairs_csv:
        pr = pd.read_csv(args.pairs_csv)
        paths, _ = plot_bland_altman(
            pr["device_a"].to_numpy(float), pr["device_b"].to_numpy(float), args.out
        )
        written += paths
    if args.windows_csv:
        written += plot_rejection_timeline(pd.read_csv(args.windows_csv), args.out)
    if not written:
        p.error("Indique --synthetic-demo o al menos una entrada CSV.")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
