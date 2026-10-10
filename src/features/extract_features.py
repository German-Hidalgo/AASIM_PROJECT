"""Extracción multidimensional de características de ECG por ventana.

Proyecto AASIM - Fase 2.

Responsables
------------
* Implementación y comentarios técnicos: Luis Carlos Rocha (Ingeniería TI).
* Interpretación fisiológica de los biomarcadores morfológicos y de HRV:
  Juan Manuel Buitrago (Validación Clínica).

Requisitos del sistema atendidos
--------------------------------
* RF1: extracción de características en tiempo real sobre ventanas de 10-30 s.
* RF2: biomarcadores morfológicos, autonómicos, tiempo-frecuencia y de textura
  con capacidad de inferencia hemodinámica.
* RNF2: latencia extremo a extremo por ventana <= 5 s (``benchmark_latency``
  mide cada etapa).
* RNF3: solo NumPy/SciPy/PyWavelets; sin dependencias de aceleración.
* RNF4: las características morfológicas se calculan en unidades físicas del
  ECG filtrado; la normalización robusta se aplica aguas abajo y solo con
  estadísticos de entrenamiento (``src.preprocessing.transformations``).

Cuatro clases de características
--------------------------------
1. **Morfológicas**: intervalo PR, duración del QRS, intervalo QT, QTc de
   Bazett (``QT / sqrt(RR)``) y de Fridericia (``QT / RR^(1/3)``), pendiente
   máxima ascendente dV/dt de la onda R, profundidad de la onda S, desviación
   del segmento ST y amplitudes de R y T. Se agregan por ventana con la
   mediana de los latidos delineados.
2. **HRV**: dominio temporal (MeanNN, SDNN, RMSSD, pNN50), dominio espectral
   (VLF, LF, HF y LF/HF con interpolación spline a 4 Hz y estimador de Welch) y
   no lineales (SD1, SD2, entropía muestral y aproximada).
3. **Paquetes wavelet Daubechies 4**: energía normalizada y entropía de
   Shannon por subbanda.
4. **Textura GLCM** sobre el espectrograma, en regiones de interés (ROI) del
   complejo QRS (10-30 Hz) y de la onda T (1-7 Hz).

Advertencia sobre HRV espectral en ventanas cortas
--------------------------------------------------
La resolución espectral de una ventana de 10-30 s es de 0.03-0.1 Hz; la banda
VLF (< 0.04 Hz) y, en menor grado, LF quedan mal resueltas frente a los 5 min
que recomienda la literatura de HRV estándar. Se calculan por compatibilidad
con la especificación, pero ``FeatureResult.warnings`` lo indica y el modelado
de la Fase 3 debe tratarlos como descriptores de baja fiabilidad.

Todas las operaciones son causales respecto de la ventana: ninguna estadística
se comparte entre ventanas ni entre pacientes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pywt
from numpy.typing import NDArray
from scipy import signal
from scipy.interpolate import CubicSpline

from src.preprocessing.filters import (
    FilterConfig,
    FilterMode,
    apply_filter_chain,
    assert_causal_for_inference,
)
from src.sqi.quality_assessment import (
    QualityResult,
    SQIThresholds,
    assess_window,
    pan_tompkins_detector,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

#: Rango de duración de ventana admitido (s).
MIN_WINDOW_S: float = 10.0
MAX_WINDOW_S: float = 30.0


@dataclass(frozen=True)
class FeatureConfig:
    """Parámetros de la extracción de características.

    Attributes:
        rr_min_s: Intervalo RR mínimo fisiológico (300 ms = 200 lpm).
        rr_max_s: Intervalo RR máximo fisiológico (2 s = 30 lpm).
        ectopic_tolerance: Desviación relativa máxima respecto de la mediana
            local de RR para aceptar un intervalo normal (filtro de ectópicos).
        hrv_interp_hz: Frecuencia de remuestreo de la serie NN (4 Hz).
        min_intervals: Número mínimo de intervalos NN para calcular HRV.
        wavelet: Función madre (``db4``).
        wavelet_level: Nivel de descomposición de paquetes (2**nivel subbandas).
        glcm_levels: Niveles de gris de la cuantización para GLCM.
        stft_nperseg_s: Longitud del segmento de la STFT (s).
        stft_hop_s: Salto de la STFT (s).
        qrs_roi_hz / t_roi_hz: Bandas de frecuencia de las ROI.
        qrs_roi_s: Semiancho temporal de la ROI del QRS alrededor del pico R.
        t_roi_s: Límites temporales (respecto de R) de la ROI de la onda T.
    """

    rr_min_s: float = 0.30
    rr_max_s: float = 2.00
    ectopic_tolerance: float = 0.20
    hrv_interp_hz: float = 4.0
    min_intervals: int = 8
    wavelet: str = "db4"
    wavelet_level: int = 4
    glcm_levels: int = 16
    stft_nperseg_s: float = 0.192
    stft_hop_s: float = 0.016
    qrs_roi_hz: tuple[float, float] = (10.0, 30.0)
    t_roi_hz: tuple[float, float] = (1.0, 7.0)
    qrs_roi_s: float = 0.060
    t_roi_s: tuple[float, float] = (0.150, 0.400)


@dataclass
class FeatureResult:
    """Vector de características de una ventana y su trazabilidad."""

    features: dict[str, float]
    n_beats: int
    n_nn_intervals: int
    warnings: list[str] = field(default_factory=list)
    latency_ms: dict[str, float] = field(default_factory=dict)

    def as_vector(self, names: list[str]) -> FloatArray:
        """Ordena las características según ``names`` (``NaN`` si faltan)."""
        return np.asarray([self.features.get(n, np.nan) for n in names], dtype=float)


# --------------------------------------------------------------------------
# Latidos e intervalos NN
# --------------------------------------------------------------------------
def detect_r_peaks(ecg: FloatArray, fs: float) -> IntArray:
    """Detecta picos R con Pan-Tompkins (mismo detector que el bSQI)."""
    return pan_tompkins_detector(ecg, fs)


def nn_intervals(
    r_peaks: IntArray, fs: float, cfg: FeatureConfig
) -> tuple[FloatArray, FloatArray]:
    """Deriva intervalos NN (s) y sus instantes de fin (s).

    Se descartan los intervalos fuera del rango fisiológico o que se desvían
    más de ``ectopic_tolerance`` de la mediana de sus vecinos (filtro de latidos
    ectópicos/falsas detecciones). Los intervalos eliminados **no se
    interpolan** para no crear falsa regularidad.

    Returns:
        ``(nn_s, t_end_s)`` con las muestras aceptadas.
    """
    if r_peaks.size < 3:
        return np.empty(0), np.empty(0)
    rr = np.diff(r_peaks) / fs
    t_end = r_peaks[1:] / fs
    ok = (rr >= cfg.rr_min_s) & (rr <= cfg.rr_max_s)
    med = np.array(
        [np.median(rr[max(0, i - 4) : i + 5]) for i in range(rr.size)],
        dtype=np.float64,
    )
    ok &= np.abs(rr - med) <= cfg.ectopic_tolerance * med
    return rr[ok], t_end[ok]


# --------------------------------------------------------------------------
# Clase 2: HRV
# --------------------------------------------------------------------------
def time_domain_hrv(nn_s: FloatArray) -> dict[str, float]:
    """MeanNN, SDNN, RMSSD (ms) y pNN50 (%) a partir de intervalos NN (s)."""
    nn_ms = nn_s * 1000.0
    diff = np.diff(nn_ms)
    return {
        "feat_hrv_mean_nn_ms": float(nn_ms.mean()),
        "feat_hrv_sdnn_ms": float(nn_ms.std(ddof=1)),
        "feat_hrv_rmssd_ms": float(np.sqrt(np.mean(diff**2))),
        "feat_hrv_pnn50_pct": float(100.0 * np.mean(np.abs(diff) > 50.0)),
    }


def frequency_domain_hrv(
    nn_s: FloatArray, t_end_s: FloatArray, cfg: FeatureConfig
) -> dict[str, float]:
    """Potencias VLF, LF, HF (ms^2) y LF/HF con spline a 4 Hz y Welch.

    Bandas: VLF 0.0033-0.04 Hz, LF 0.04-0.15 Hz, HF 0.15-0.40 Hz. La serie NN se
    interpola con spline cúbico a ``hrv_interp_hz``, se le retira la tendencia
    lineal y se estima la PSD con el método de Welch (ventana de Hann, 50 % de
    solape).
    """
    t0, t1 = float(t_end_s[0]), float(t_end_s[-1])
    n_pts = int(np.floor((t1 - t0) * cfg.hrv_interp_hz)) + 1
    grid = t0 + np.arange(n_pts) / cfg.hrv_interp_hz
    series = CubicSpline(t_end_s, nn_s * 1000.0)(grid)
    series = signal.detrend(series, type="linear")
    nperseg = min(series.size, 256)
    freqs, psd = signal.welch(
        series,
        fs=cfg.hrv_interp_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        detrend=False,
    )
    df = freqs[1] - freqs[0]

    def band_power(lo: float, hi: float) -> float:
        sel = (freqs >= lo) & (freqs < hi)
        return float(psd[sel].sum() * df)

    vlf, lf, hf = (
        band_power(0.0033, 0.04),
        band_power(0.04, 0.15),
        band_power(0.15, 0.40),
    )
    return {
        "feat_hrv_vlf_ms2": vlf,
        "feat_hrv_lf_ms2": lf,
        "feat_hrv_hf_ms2": hf,
        "feat_hrv_lf_hf": float(lf / hf) if hf > 0.0 else float("nan"),
    }


def sample_entropy(x: FloatArray, m: int = 2, r_factor: float = 0.2) -> float:
    """Entropía muestral SampEn(m, r) con ``r = r_factor * desv. estándar``.

    Se emplean las primeras ``N - m`` plantillas para longitudes ``m`` y
    ``m + 1``, sin autocoincidencias. Devuelve ``NaN`` si no hay coincidencias.
    """
    v = np.asarray(x, dtype=np.float64)
    n = v.size
    if n <= m + 2:
        return float("nan")
    r = r_factor * float(v.std(ddof=0))
    if r <= 0.0:
        return float("nan")

    def count(length: int) -> int:
        tpl = np.lib.stride_tricks.sliding_window_view(v, length)[: n - m]
        dist = np.max(np.abs(tpl[:, None, :] - tpl[None, :, :]), axis=2)
        return int((np.sum(dist <= r) - tpl.shape[0]) // 2)

    b, a = count(m), count(m + 1)
    if a == 0 or b == 0:
        return float("nan")
    return float(-np.log(a / b))


def approximate_entropy(x: FloatArray, m: int = 2, r_factor: float = 0.2) -> float:
    """Entropía aproximada ApEn(m, r) (incluye autocoincidencias)."""
    v = np.asarray(x, dtype=np.float64)
    n = v.size
    if n <= m + 1:
        return float("nan")
    r = r_factor * float(v.std(ddof=0))
    if r <= 0.0:
        return float("nan")

    def phi(length: int) -> float:
        tpl = np.lib.stride_tricks.sliding_window_view(v, length)
        dist = np.max(np.abs(tpl[:, None, :] - tpl[None, :, :]), axis=2)
        c = np.mean(dist <= r, axis=1)
        return float(np.mean(np.log(c)))

    return float(phi(m) - phi(m + 1))


def nonlinear_hrv(nn_s: FloatArray) -> dict[str, float]:
    """SD1, SD2 (Poincaré, ms), SampEn y ApEn de la serie NN."""
    nn_ms = nn_s * 1000.0
    d = np.diff(nn_ms)
    sdsd = float(d.std(ddof=1))
    sdnn = float(nn_ms.std(ddof=1))
    sd1 = float(np.sqrt(0.5) * sdsd)
    sd2_sq = 2.0 * sdnn**2 - 0.5 * sdsd**2
    return {
        "feat_hrv_sd1_ms": sd1,
        "feat_hrv_sd2_ms": float(np.sqrt(sd2_sq)) if sd2_sq > 0.0 else float("nan"),
        "feat_hrv_sampen": sample_entropy(nn_ms),
        "feat_hrv_apen": approximate_entropy(nn_ms),
    }


# --------------------------------------------------------------------------
# Clase 1: morfología
# --------------------------------------------------------------------------
def _first_quiet(
    absd: FloatArray, start: int, stop: int, thr: float, run: int, step: int
) -> int:
    """Primer índice desde ``start`` hacia ``stop`` con ``run`` muestras < ``thr``.

    ``step`` = -1 recorre hacia atrás (inicio del QRS) y +1 hacia delante (fin).
    Si no se encuentra, devuelve ``stop``.
    """
    i = start
    while (i > stop) if step < 0 else (i < stop):
        seg = absd[i - run + 1 : i + 1] if step < 0 else absd[i : i + run]
        if seg.size == run and np.all(seg < thr):
            return i
        i += step
    return stop


def delineate_beats(
    ecg: FloatArray, fs: float, r_peaks: IntArray
) -> dict[str, FloatArray]:
    """Delineación latido a latido de P, QRS y T mediante pendientes y tangentes.

    Método:

    * Suavizado Savitzky-Golay (orden 3, ~36 ms) y derivada numérica.
    * Inicio/fin del QRS: primer tramo de >= 16 ms con pendiente inferior al
      12 % de la pendiente máxima del QRS, recorriendo desde R hacia atrás/
      delante.
    * Onda P: máximo en la ventana previa al QRS; inicio al caer al 10 % de su
      amplitud. Si su amplitud es < 2 % de la de R se considera ausente (PR
      queda como ``NaN``).
    * Onda T: extremo de mayor desviación tras el QRS; fin por el método de la
      tangente en el punto de máxima pendiente descendente.
    * Línea isoelectrónica: mediana del segmento PR previo al QRS.

    Args:
        ecg: ECG filtrado en unidades físicas (mV).
        fs: Frecuencia de muestreo (Hz).
        r_peaks: Índices de picos R.

    Returns:
        Diccionario de vectores por latido (``NaN`` cuando un fiducial no pudo
        determinarse). El primer latido se omite (sin RR previo).
    """
    win = round(0.036 * fs) | 1
    xs = signal.savgol_filter(ecg, max(win, 5), 3)
    dx = np.gradient(xs) * fs
    absd = np.abs(dx)
    n = ecg.size
    run = max(3, round(0.016 * fs))

    names = (
        "pr_ms",
        "qrs_ms",
        "qt_ms",
        "qtc_bazett_ms",
        "qtc_fridericia_ms",
        "dvdt_max",
        "s_depth",
        "st_dev",
        "r_amp",
        "t_amp",
    )
    out: dict[str, list[float]] = {k: [] for k in names}

    for k in range(1, r_peaks.size):
        r = int(r_peaks[k])
        prev_r = int(r_peaks[k - 1])
        rr_s = (r - prev_r) / fs
        nxt = int(r_peaks[k + 1]) if k + 1 < r_peaks.size else r + int(rr_s * fs)
        rec = dict.fromkeys(names, np.nan)

        lo, hi = r - int(0.10 * fs), r + int(0.14 * fs)
        if lo <= 0 or hi >= n - 1:
            for key in names:
                out[key].append(np.nan)
            continue
        peak_slope = float(absd[r - int(0.06 * fs) : r + int(0.06 * fs) + 1].max())
        thr = 0.12 * peak_slope
        on = _first_quiet(absd, r, lo, thr, run, -1)
        s_idx = r + int(np.argmin(xs[r : r + int(0.10 * fs) + 1]))
        off = _first_quiet(absd, s_idx, hi, thr, run, +1)
        iso_seg = xs[max(0, on - int(0.030 * fs)) : max(1, on - int(0.005 * fs))]
        iso = float(np.median(iso_seg)) if iso_seg.size else float(np.median(xs))
        r_amp = float(xs[r] - iso)

        rec["qrs_ms"] = 1000.0 * (off - on) / fs
        rec["dvdt_max"] = float(absd[on : r + 1].max())
        rec["s_depth"] = float(xs[s_idx] - iso)
        rec["r_amp"] = r_amp
        st_idx = min(n - 1, off + int(0.060 * fs))
        rec["st_dev"] = float(xs[st_idx] - iso)

        # --- Onda P y PR
        p_lo = max(r - int(0.30 * fs), prev_r + int(0.55 * (r - prev_r)))
        p_hi = on - int(0.02 * fs)
        if p_hi - p_lo > int(0.04 * fs) and r_amp > 0.0:
            seg = xs[p_lo:p_hi]
            p_pk = p_lo + int(np.argmax(seg))
            p_amp = float(xs[p_pk] - iso)
            if p_amp > 0.02 * r_amp:
                target = iso + 0.10 * p_amp
                j = p_pk
                while j > p_lo and xs[j] > target:
                    j -= 1
                rec["pr_ms"] = 1000.0 * (on - j) / fs

        # --- Onda T, QT y QTc
        t_lo = off + int(0.05 * fs)
        t_hi = min(r + int(min(0.55 * rr_s, 0.50) * fs), nxt - int(0.10 * fs), n - 2)
        if t_hi - t_lo > int(0.05 * fs):
            seg = xs[t_lo:t_hi] - iso
            t_pk = t_lo + int(np.argmax(np.abs(seg)))
            sign = 1.0 if xs[t_pk] - iso >= 0 else -1.0
            rec["t_amp"] = float(xs[t_pk] - iso)
            end_hi = min(t_pk + int(0.20 * fs), nxt - int(0.05 * fs), n - 2)
            if end_hi > t_pk + 2:
                slopes = -sign * dx[t_pk:end_hi]
                i_s = t_pk + int(np.argmax(slopes))
                if slopes.max() > 0.0:
                    # Tangente en el punto de máxima pendiente descendente: corta
                    # la línea isoeléctrica tras ``(iso - xs) / dx`` segundos
                    # (``dx`` está en unidades de ECG por segundo).
                    t_end = i_s + (iso - xs[i_s]) / dx[i_s] * fs
                    if t_pk < t_end < nxt:
                        qt_ms = 1000.0 * (t_end - on) / fs
                        rec["qt_ms"] = qt_ms
                        rec["qtc_bazett_ms"] = qt_ms / np.sqrt(rr_s)
                        rec["qtc_fridericia_ms"] = qt_ms / np.cbrt(rr_s)
        for key in names:
            out[key].append(float(rec[key]))
    return {k: np.asarray(v, dtype=np.float64) for k, v in out.items()}


def morphological_features(
    ecg: FloatArray, fs: float, r_peaks: IntArray
) -> tuple[dict[str, float], int]:
    """Agrega la delineación por ventana (mediana de latidos válidos).

    Returns:
        ``(características, n_latidos_con_QT_válido)``.
    """
    d = delineate_beats(ecg, fs, r_peaks)
    mapping = {
        "pr_ms": "feat_pr_interval_ms",
        "qrs_ms": "feat_qrs_duration_ms",
        "qt_ms": "feat_qt_interval_ms",
        "qtc_bazett_ms": "feat_qtc_bazett_ms",
        "qtc_fridericia_ms": "feat_qtc_fridericia_ms",
        "dvdt_max": "feat_dvdt_max",
        "s_depth": "feat_s_depth_mv",
        "st_dev": "feat_st_deviation_mv",
        "r_amp": "feat_r_amplitude_mv",
        "t_amp": "feat_t_amplitude_mv",
    }
    feats: dict[str, float] = {}
    for src, dst in mapping.items():
        vals = d[src][np.isfinite(d[src])]
        feats[dst] = float(np.median(vals)) if vals.size >= 3 else float("nan")
    return feats, int(np.isfinite(d["qt_ms"]).sum())


# --------------------------------------------------------------------------
# Clase 3: paquetes wavelet
# --------------------------------------------------------------------------
def wavelet_packet_features(ecg: FloatArray, cfg: FeatureConfig) -> dict[str, float]:
    """Energía normalizada y entropía de Shannon por subbanda de paquetes db4.

    Para un nivel ``L`` se obtienen ``2**L`` subbandas ordenadas por frecuencia,
    de ancho ``fs / 2**(L+1)`` Hz. Para cada subbanda ``i``:

    * ``feat_wpd_e_i``: energía relativa ``E_i / sum(E)``.
    * ``feat_wpd_h_i``: entropía de Shannon de la distribución de energía de
      sus coeficientes (normalizada por ``log(n)``, en [0, 1]).

    Se añade ``feat_wpd_entropy_total``, la entropía wavelet de la
    distribución de energía entre subbandas.
    """
    wp = pywt.WaveletPacket(
        data=ecg, wavelet=cfg.wavelet, mode="symmetric", maxlevel=cfg.wavelet_level
    )
    nodes = wp.get_level(cfg.wavelet_level, order="freq")
    energies = np.array([np.sum(nd.data**2) for nd in nodes], dtype=np.float64)
    total = float(energies.sum())
    feats: dict[str, float] = {}
    eps = np.finfo(np.float64).tiny
    for i, nd in enumerate(nodes):
        c2 = nd.data**2
        s = float(c2.sum())
        q = c2 / s if s > 0.0 else np.full_like(c2, 1.0 / c2.size)
        h = -np.sum(q * np.log(q + eps)) / np.log(q.size)
        feats[f"feat_wpd_e_{i:02d}"] = float(energies[i] / total) if total > 0 else 0.0
        feats[f"feat_wpd_h_{i:02d}"] = float(h)
    p = energies / total if total > 0 else np.full(energies.size, 1.0 / energies.size)
    feats["feat_wpd_entropy_total"] = float(-np.sum(p * np.log(p + eps)))
    return feats


# --------------------------------------------------------------------------
# Clase 4: texturas GLCM en ROI del espectrograma
# --------------------------------------------------------------------------
def _glcm_counts(patch: NDArray[np.int64], levels: int) -> FloatArray:
    """Matriz de co-ocurrencia simétrica (distancia 1; 0, 45, 90 y 135 grados)."""
    counts = np.zeros((levels, levels), dtype=np.float64)
    rows, cols = patch.shape
    for dr, dc in ((0, 1), (-1, 1), (-1, 0), (-1, -1)):
        r0, r1 = max(0, -dr), rows - max(0, dr)
        c0, c1 = max(0, -dc), cols - max(0, dc)
        if r1 <= r0 or c1 <= c0:
            continue
        a = patch[r0:r1, c0:c1].ravel()
        b = patch[r0 + dr : r1 + dr, c0 + dc : c1 + dc].ravel()
        pair = np.bincount(a * levels + b, minlength=levels * levels)
        m = pair.reshape(levels, levels).astype(np.float64)
        counts += m + m.T
    return counts


def _glcm_descriptors(counts: FloatArray) -> dict[str, float]:
    """Contraste, correlación, energía, homogeneidad y ASM de una GLCM."""
    total = counts.sum()
    if total <= 0.0:
        return dict.fromkeys(
            ("contrast", "correlation", "energy", "homogeneity", "asm"), float("nan")
        )
    p = counts / total
    lv = np.arange(p.shape[0], dtype=np.float64)
    ii, jj = np.meshgrid(lv, lv, indexing="ij")
    mu_i, mu_j = float((p * ii).sum()), float((p * jj).sum())
    sd_i = float(np.sqrt((p * (ii - mu_i) ** 2).sum()))
    sd_j = float(np.sqrt((p * (jj - mu_j) ** 2).sum()))
    asm = float((p**2).sum())
    corr = (
        float((p * (ii - mu_i) * (jj - mu_j)).sum() / (sd_i * sd_j))
        if sd_i > 0 and sd_j > 0
        else float("nan")
    )
    return {
        "contrast": float((p * (ii - jj) ** 2).sum()),
        "correlation": corr,
        "energy": float(np.sqrt(asm)),
        "homogeneity": float((p / (1.0 + np.abs(ii - jj))).sum()),
        "asm": asm,
    }


def glcm_roi_features(
    ecg: FloatArray, fs: float, r_peaks: IntArray, cfg: FeatureConfig
) -> dict[str, float]:
    """Descriptores GLCM de las ROI del QRS y de la onda T en el espectrograma.

    El espectrograma (STFT con ventana de Hann, ``nfft = 256``) se expresa en
    escala logarítmica y se cuantiza a ``glcm_levels`` niveles con los
    percentiles 1-99 **de la propia ventana** (sin estadísticos externos). Para
    cada latido se recorta la ROI del QRS (``qrs_roi_hz`` y ``±qrs_roi_s`` en
    torno a R) y de la onda T (``t_roi_hz`` y ``t_roi_s`` tras R); las matrices
    GLCM de todos los latidos se acumulan antes de calcular los descriptores.
    """
    nperseg = round(cfg.stft_nperseg_s * fs)
    hop = max(1, round(cfg.stft_hop_s * fs))
    freqs, times, sxx = signal.spectrogram(
        ecg,
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg - hop,
        nfft=256,
        mode="psd",
    )
    logs = np.log10(sxx + 1e-12)
    lo, hi = np.percentile(logs, [1.0, 99.0])
    span = hi - lo if hi > lo else 1.0
    q = np.clip(np.floor((logs - lo) / span * cfg.glcm_levels), 0, cfg.glcm_levels - 1)
    q = q.astype(np.int64)

    def roi_desc(
        band: tuple[float, float], t_bounds: list[tuple[float, float]]
    ) -> dict[str, float]:
        f_sel = np.flatnonzero((freqs >= band[0]) & (freqs <= band[1]))
        acc = np.zeros((cfg.glcm_levels, cfg.glcm_levels))
        for t_lo, t_hi in t_bounds:
            t_sel = np.flatnonzero((times >= t_lo) & (times <= t_hi))
            if f_sel.size < 2 or t_sel.size < 2:
                continue
            patch = q[f_sel[0] : f_sel[-1] + 1, t_sel[0] : t_sel[-1] + 1]
            acc += _glcm_counts(patch, cfg.glcm_levels)
        return _glcm_descriptors(acc)

    # Los tiempos de la STFT se refieren al centro de cada segmento.
    r_t = r_peaks[1:] / fs
    qrs_b = [(t - cfg.qrs_roi_s, t + cfg.qrs_roi_s) for t in r_t]
    t_b = [(t + cfg.t_roi_s[0], t + cfg.t_roi_s[1]) for t in r_t]
    feats: dict[str, float] = {}
    for tag, band, bounds in (
        ("qrs", cfg.qrs_roi_hz, qrs_b),
        ("t", cfg.t_roi_hz, t_b),
    ):
        for name, val in roi_desc(band, bounds).items():
            feats[f"feat_glcm_{tag}_{name}"] = val
    return feats


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------
def feature_names(cfg: FeatureConfig | None = None) -> list[str]:
    """Nombres ordenados del vector de características (contrato estable)."""
    c = cfg or FeatureConfig()
    names = [
        "feat_pr_interval_ms",
        "feat_qrs_duration_ms",
        "feat_qt_interval_ms",
        "feat_qtc_bazett_ms",
        "feat_qtc_fridericia_ms",
        "feat_dvdt_max",
        "feat_s_depth_mv",
        "feat_st_deviation_mv",
        "feat_r_amplitude_mv",
        "feat_t_amplitude_mv",
        "feat_hrv_mean_nn_ms",
        "feat_hrv_sdnn_ms",
        "feat_hrv_rmssd_ms",
        "feat_hrv_pnn50_pct",
        "feat_hrv_vlf_ms2",
        "feat_hrv_lf_ms2",
        "feat_hrv_hf_ms2",
        "feat_hrv_lf_hf",
        "feat_hrv_sd1_ms",
        "feat_hrv_sd2_ms",
        "feat_hrv_sampen",
        "feat_hrv_apen",
    ]
    for i in range(2**c.wavelet_level):
        names += [f"feat_wpd_e_{i:02d}", f"feat_wpd_h_{i:02d}"]
    names.append("feat_wpd_entropy_total")
    for tag in ("qrs", "t"):
        names += [
            f"feat_glcm_{tag}_{d}"
            for d in ("contrast", "correlation", "energy", "homogeneity", "asm")
        ]
    return names


def extract_window_features(
    ecg_filtered: FloatArray, fs: float, cfg: FeatureConfig | None = None
) -> FeatureResult:
    """Extrae el vector completo de características de una ventana filtrada.

    Args:
        ecg_filtered: ECG filtrado (0.5-45 Hz, en mV) de 10 a 30 s **que ya
            superó la compuerta de calidad** (``quality_flag == 0``).
        fs: Frecuencia de muestreo (Hz).
        cfg: Parámetros; por defecto los de la especificación.

    Raises:
        ValueError: Si la duración está fuera de 10-30 s.
    """
    c = cfg or FeatureConfig()
    x = np.asarray(ecg_filtered, dtype=np.float64)
    duration = x.size / fs
    if not MIN_WINDOW_S - 1e-6 <= duration <= MAX_WINDOW_S + 1e-6:
        raise ValueError(
            f"Duración de ventana {duration:.1f} s fuera de [{MIN_WINDOW_S}, "
            f"{MAX_WINDOW_S}] s"
        )
    timing: dict[str, float] = {}
    warnings: list[str] = []
    feats: dict[str, float] = {}

    t0 = time.perf_counter()
    peaks = detect_r_peaks(x, fs)
    timing["r_peaks"] = 1e3 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    morph, n_qt = morphological_features(x, fs, peaks)
    feats.update(morph)
    timing["morphology"] = 1e3 * (time.perf_counter() - t0)
    if n_qt < 3:
        warnings.append("Menos de 3 latidos con QT delineable: QT/QTc no fiables.")

    t0 = time.perf_counter()
    nn, t_end = nn_intervals(peaks, fs, c)
    if nn.size >= c.min_intervals:
        feats.update(time_domain_hrv(nn))
        feats.update(frequency_domain_hrv(nn, t_end, c))
        feats.update(nonlinear_hrv(nn))
        if duration < 250.0:
            warnings.append(
                "Ventana < 250 s: potencias VLF/LF con resolución espectral "
                "insuficiente (baja fiabilidad)."
            )
    else:
        warnings.append(
            f"Solo {nn.size} intervalos NN válidos (< {c.min_intervals}): HRV omitida."
        )
    timing["hrv"] = 1e3 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    feats.update(wavelet_packet_features(x, c))
    timing["wavelet"] = 1e3 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    feats.update(glcm_roi_features(x, fs, peaks, c))
    timing["glcm"] = 1e3 * (time.perf_counter() - t0)

    for name in feature_names(c):
        feats.setdefault(name, float("nan"))
    return FeatureResult(
        features=feats,
        n_beats=int(peaks.size),
        n_nn_intervals=int(nn.size),
        warnings=warnings,
        latency_ms=timing,
    )


# --------------------------------------------------------------------------
# Pipeline de ventana extremo a extremo y benchmark de latencia (RNF2)
# --------------------------------------------------------------------------
@dataclass
class WindowPipelineResult:
    """Resultado del procesamiento completo de una ventana cruda."""

    quality: QualityResult
    features: FeatureResult | None
    latency_ms: dict[str, float]

    @property
    def total_latency_s(self) -> float:
        """Latencia total (s) sumando todas las etapas medidas."""
        return sum(self.latency_ms.values()) / 1e3


def process_window(
    raw_ecg: FloatArray,
    fs: float,
    filter_cfg: FilterConfig | None = None,
    feature_cfg: FeatureConfig | None = None,
    thresholds: SQIThresholds | None = None,
    mode: FilterMode = FilterMode.CAUSAL,
) -> WindowPipelineResult:
    """Filtrado -> SQI -> (si ``quality_flag == 0``) características.

    La ruta de inferencia exige el modo causal; cualquier otro modo lanza
    ``NonCausalFilterError``. Si la ventana es rechazada por la compuerta RF4 no
    se extraen características y ``features`` es ``None``.
    """
    assert_causal_for_inference(mode)
    f_cfg = filter_cfg or FilterConfig(fs)
    timing: dict[str, float] = {}

    t0 = time.perf_counter()
    filtered = apply_filter_chain(raw_ecg, f_cfg, mode).signal
    timing["filtering"] = 1e3 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    quality = assess_window(filtered, fs, thresholds)
    timing["sqi"] = 1e3 * (time.perf_counter() - t0)
    if quality.quality_flag == 1:
        return WindowPipelineResult(quality, None, timing)

    res = extract_window_features(filtered, fs, feature_cfg)
    timing.update({f"feat_{k}": v for k, v in res.latency_ms.items()})
    return WindowPipelineResult(quality, res, timing)


def benchmark_latency(
    raw_ecg: FloatArray, fs: float, n_runs: int = 10
) -> dict[str, float]:
    """Mide la latencia extremo a extremo por ventana (RNF2 <= 5 s).

    Args:
        raw_ecg: Ventana cruda representativa (10-30 s).
        fs: Frecuencia de muestreo (Hz).
        n_runs: Repeticiones.

    Returns:
        Estadísticos en segundos: ``mean_s``, ``p95_s``, ``max_s`` y el margen
        respecto del límite de 5 s (``margin_vs_5s``).
    """
    totals: list[float] = []
    for _ in range(n_runs):
        totals.append(process_window(raw_ecg, fs).total_latency_s)
    arr = np.asarray(totals)
    return {
        "mean_s": float(arr.mean()),
        "p95_s": float(np.percentile(arr, 95)),
        "max_s": float(arr.max()),
        "margin_vs_5s": float(5.0 / arr.max()) if arr.max() > 0 else float("inf"),
    }
