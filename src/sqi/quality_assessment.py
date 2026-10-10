"""Índices de calidad de señal (SQI) y compuerta de auto-rechazo (RF4).

Proyecto AASIM - Fase 2.

Responsables
------------
* Implementación de detectores QRS e índices: Luis Carlos Rocha (Ingeniería
  TI).
* Calibración de umbrales y política de notificación al usuario (RF4, R4):
  German Alberto Hidalgo (Ética y Pacientes), en coordinación con ingeniería,
  para equilibrar la barrera contra interpretaciones erróneas y la
  disponibilidad global del sistema.

Requisitos del sistema atendidos
--------------------------------
* RF4: advertir mala calidad y **suspender la inferencia numérica**.
* R4 (mala interpretación clínica): supresión de la salida numérica cuando
  la señal es inadecuada, informando la causa del descarte.
* RNF2 / RNF3: todos los cómputos usan operaciones vectorizadas de NumPy/SciPy
  y filtros causales, aptos para hardware accesible.

Definición de los índices
-------------------------
``bSQI`` (concordancia de detectores)
    Puntuación F1 de latidos coincidentes entre dos detectores independientes:
    Pan-Tompkins (energía de la derivada) y un detector de longitud de curva
    (tipo WQRS/Zong)::

        bSQI = 2 * N_coincidentes / (N_PT + N_LC)

    con una tolerancia de coincidencia configurable (por defecto 50 ms, el
    valor de la implementación de referencia ``bsqi.m`` del toolbox
    cardiovascular de PhysioNet).
``kSQI`` (curtosis)
    Curtosis de Pearson (no exceso; gaussiana = 3) del ECG en bloques
    consecutivos de 5 s, agregada con la mediana. Un ECG íntegro presenta colas
    pesadas (kSQI >= 5); el ruido incoherente converge a ~3 y la saturación
    produce distribuciones subgaussianas.
``pSQI`` (potencia espectral relativa)
    Cociente entre la potencia en 5-15 Hz (donde se concentra el complejo QRS)
    y la potencia en 1-40 Hz.
``sSQI`` (asimetría, informativo)
    Tercer momento estandarizado; no interviene en la compuerta, pero se
    reporta para auditar desprendimientos parciales de electrodo.

Compuerta lógica combinada (RF4)::

    quality_flag = 0  si  bSQI >= 0.85  y  kSQI >= 5.0  y  pSQI >= 0.50
    quality_flag = 1  en cualquier otro caso  (inferencia bloqueada)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy import signal, stats

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SQIThresholds:
    """Umbrales de aceptación de la compuerta RF4 (Fase 2)."""

    bsqi_min: float = 0.70
    ksqi_min: float = 4.0
    psqi_min: float = 0.40
    #: Tolerancia de coincidencia entre detectores (s).
    match_tolerance_s: float = 0.05
    #: Duración del bloque para el cómputo de curtosis (s), entre 2 y 5 s.
    kurtosis_block_s: float = 5.0
    #: Agregador de curtosis entre bloques: ``median`` o ``min``.
    kurtosis_aggregate: str = "median"
    #: Bandas espectrales del pSQI (Hz).
    psqi_num_band: tuple[float, float] = (5.0, 15.0)
    psqi_den_band: tuple[float, float] = (1.0, 40.0)


# --------------------------------------------------------------------------
# Detector 1: Pan-Tompkins
# --------------------------------------------------------------------------
def _refine_peaks(
    ecg: FloatArray,
    candidates: IntArray,
    fs: float,
    back_s: float,
    fwd_s: float,
    refractory_s: float = 0.2,
) -> IntArray:
    """Ajusta candidatos al máximo de ``|ECG - mediana|`` y aplica refractariedad.

    Los detectores basados en transformadas causales presentan un retardo
    (integración en ventana móvil o longitud de curva); por ello se busca el
    pico de R en la ventana ``[c - back_s, c + fwd_s]`` sobre el ECG filtrado.
    """
    if candidates.size == 0:
        return np.empty(0, dtype=np.int64)
    centered = np.abs(ecg - np.median(ecg))
    peaks: list[int] = []
    for c in candidates:
        lo = max(0, int(c - round(back_s * fs)))
        hi = min(ecg.size, int(c + round(fwd_s * fs)) + 1)
        if hi <= lo:
            continue
        peaks.append(lo + int(np.argmax(centered[lo:hi])))
    peaks_arr = np.unique(np.asarray(peaks, dtype=np.int64))
    # Refractariedad: entre picos demasiado próximos se conserva el mayor.
    keep: list[int] = []
    min_dist = round(refractory_s * fs)
    for p in peaks_arr:
        if keep and p - keep[-1] < min_dist:
            if centered[p] > centered[keep[-1]]:
                keep[-1] = int(p)
        else:
            keep.append(int(p))
    return np.asarray(keep, dtype=np.int64)


def pan_tompkins_detector(ecg: FloatArray, fs: float) -> IntArray:
    """Detector QRS de Pan-Tompkins (versión causal con búsqueda hacia atrás).

    Etapas: pasa-banda 5-15 Hz, derivada, elevación al cuadrado, integración en
    ventana móvil de 150 ms y umbrales adaptativos (SPKI/NPKI) con búsqueda de
    latidos perdidos cuando el intervalo RR excede 166 % del promedio.

    Args:
        ecg: ECG filtrado (0.5-45 Hz) de una ventana.
        fs: Frecuencia de muestreo (Hz).

    Returns:
        Índices de muestra de los picos R detectados (ordenados).
    """
    x = np.asarray(ecg, dtype=np.float64)
    if x.size < int(2 * fs):
        return np.empty(0, dtype=np.int64)
    sos = signal.butter(2, [5.0, 15.0], btype="bandpass", fs=fs, output="sos")
    band = signal.sosfilt(sos, x - np.median(x))
    deriv = np.gradient(band) * fs
    squared = deriv**2
    win = max(1, round(0.150 * fs))
    integ = np.convolve(squared, np.ones(win) / win, mode="full")[: x.size]

    cand, _ = signal.find_peaks(integ, distance=max(1, int(0.2 * fs)))
    if cand.size == 0:
        return np.empty(0, dtype=np.int64)

    # Fase de aprendizaje con los primeros 2 s.
    learn = integ[: int(2 * fs)]
    spki = 0.25 * float(learn.max())
    npki = float(learn.mean())
    thr1 = npki + 0.25 * (spki - npki)
    accepted: list[int] = []
    rr_hist: list[int] = []
    for k, idx in enumerate(cand):
        peak = float(integ[idx])
        # Búsqueda hacia atrás si se sospecha un latido perdido.
        if accepted and rr_hist:
            avg_rr = float(np.mean(rr_hist[-8:]))
            if idx - accepted[-1] > 1.66 * avg_rr:
                prev = [c for c in cand[:k] if c > accepted[-1] + 0.2 * fs]
                if prev:
                    best = max(prev, key=lambda c: integ[c])
                    if integ[best] > 0.5 * thr1:
                        rr_hist.append(int(best - accepted[-1]))
                        accepted.append(int(best))
                        spki = 0.25 * float(integ[best]) + 0.75 * spki
        if peak > thr1:
            if accepted:
                rr_hist.append(int(idx - accepted[-1]))
            accepted.append(int(idx))
            spki = 0.125 * peak + 0.875 * spki
        else:
            npki = 0.125 * peak + 0.875 * npki
        thr1 = npki + 0.25 * (spki - npki)
    return _refine_peaks(
        x, np.asarray(accepted, dtype=np.int64), fs, back_s=0.25, fwd_s=0.03
    )


# --------------------------------------------------------------------------
# Detector 2: longitud de curva (tipo WQRS / Zong)
# --------------------------------------------------------------------------
def curve_length_detector(ecg: FloatArray, fs: float) -> IntArray:
    """Detector QRS basado en la transformada de longitud de curva.

    Principio complementario al de Pan-Tompkins: en lugar de energía de la
    derivada, se acumula la longitud de la curva ``sqrt(1 + (g*dx)^2)`` en una
    ventana de 130 ms tras un pasa-bajos de 16 Hz. El umbral se adapta a cada
    ventana con percentiles de la propia transformada.

    Args:
        ecg: ECG filtrado (0.5-45 Hz) de una ventana.
        fs: Frecuencia de muestreo (Hz).

    Returns:
        Índices de muestra de los picos R detectados.
    """
    x = np.asarray(ecg, dtype=np.float64)
    if x.size < int(2 * fs):
        return np.empty(0, dtype=np.int64)
    sos = signal.butter(2, 16.0, btype="lowpass", fs=fs, output="sos")
    smooth = signal.sosfilt(sos, x - np.median(x))
    dx = np.diff(smooth, prepend=smooth[0])
    scale = float(np.std(dx))
    if scale <= 0.0:
        return np.empty(0, dtype=np.int64)
    step = np.sqrt(1.0 + (dx / scale) ** 2)
    w = max(1, round(0.130 * fs))
    length = np.convolve(step, np.ones(w), mode="full")[: x.size]
    length = length - w  # retira el aporte de la línea plana (sqrt(1) por muestra)

    p50, p95 = np.percentile(length, [50.0, 95.0])
    if p95 - p50 <= 0.0:
        return np.empty(0, dtype=np.int64)
    height = p50 + 0.35 * (p95 - p50)
    cand, _ = signal.find_peaks(length, height=height, distance=max(1, int(0.2 * fs)))
    return _refine_peaks(x, cand.astype(np.int64), fs, back_s=0.20, fwd_s=0.03)


# --------------------------------------------------------------------------
# Índices individuales
# --------------------------------------------------------------------------
def match_beats(a: IntArray, b: IntArray, tol_samples: int) -> int:
    """Cuenta latidos coincidentes uno a uno entre dos listas ordenadas.

    Emparejamiento voraz por proximidad: cada latido de ``a`` se asocia con el
    latido libre de ``b`` más cercano dentro de ``tol_samples``.
    """
    i = j = matches = 0
    while i < a.size and j < b.size:
        d = int(a[i]) - int(b[j])
        if abs(d) <= tol_samples:
            matches += 1
            i += 1
            j += 1
        elif d < 0:
            i += 1
        else:
            j += 1
    return matches


def compute_bsqi(
    ecg: FloatArray, fs: float, tol_s: float = 0.05
) -> tuple[float, int, int]:
    """Índice de concordancia de detectores (F1 de latidos coincidentes).

    Returns:
        ``(bSQI, n_latidos_PT, n_latidos_LC)``. Si ninguno de los detectores
        encuentra latidos el índice es 0 (ausencia de evidencia de QRS).
    """
    a = pan_tompkins_detector(ecg, fs)
    b = curve_length_detector(ecg, fs)
    if a.size + b.size == 0:
        return 0.0, int(a.size), int(b.size)
    n_match = match_beats(a, b, round(tol_s * fs))
    return float(2.0 * n_match / (a.size + b.size)), int(a.size), int(b.size)


def compute_ksqi(
    ecg: FloatArray, fs: float, block_s: float = 5.0, aggregate: str = "median"
) -> float:
    """Curtosis de Pearson por bloques de ``block_s`` s, agregada entre bloques.

    Args:
        ecg: ECG filtrado de la ventana.
        fs: Frecuencia de muestreo (Hz).
        block_s: Duración del bloque (2-5 s).
        aggregate: ``"median"`` (por defecto) o ``"min"`` (política estricta:
            un solo bloque degradado invalida la ventana).
    """
    if not 2.0 <= block_s <= 5.0:
        raise ValueError("block_s debe estar entre 2 y 5 s")
    n = round(block_s * fs)
    n_blocks = max(1, ecg.size // n)
    values = np.array(
        [
            stats.kurtosis(ecg[k * n : (k + 1) * n], fisher=False, bias=True)
            for k in range(n_blocks)
        ],
        dtype=np.float64,
    )
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.0
    if aggregate == "min":
        return float(values.min())
    if aggregate == "median":
        return float(np.median(values))
    raise ValueError("aggregate debe ser 'median' o 'min'")


def compute_psqi(
    ecg: FloatArray,
    fs: float,
    num_band: tuple[float, float] = (5.0, 15.0),
    den_band: tuple[float, float] = (1.0, 40.0),
) -> float:
    """Potencia espectral relativa de la banda del QRS respecto a la banda ECG."""
    nperseg = int(min(ecg.size, round(4.0 * fs)))
    freqs, psd = signal.welch(ecg - np.mean(ecg), fs=fs, nperseg=nperseg)
    num = psd[(freqs >= num_band[0]) & (freqs <= num_band[1])].sum()
    den = psd[(freqs >= den_band[0]) & (freqs <= den_band[1])].sum()
    return float(num / den) if den > 0.0 else 0.0


def compute_ssqi(ecg: FloatArray) -> float:
    """Asimetría (tercer momento estandarizado) del segmento."""
    val = stats.skew(ecg, bias=True)
    return float(val) if np.isfinite(val) else 0.0


# --------------------------------------------------------------------------
# Compuerta RF4
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class QualityResult:
    """Resultado de la evaluación de calidad de una ventana."""

    bsqi: float
    ksqi: float
    psqi: float
    ssqi: float
    sqi_composite: float
    quality_flag: int
    failed_criteria: tuple[str, ...]
    n_beats_pan_tompkins: int
    n_beats_curve_length: int

    @property
    def is_valid(self) -> bool:
        """``True`` si la ventana supera la compuerta (``quality_flag == 0``)."""
        return self.quality_flag == 0


def assess_window(
    ecg_filtered: FloatArray,
    fs: float,
    thresholds: SQIThresholds | None = None,
) -> QualityResult:
    """Evalúa una ventana y aplica la compuerta lógica de RF4.

    ``sqi_composite`` es el promedio de los cocientes recortados
    ``min(1, índice/umbral)`` de los tres índices de la compuerta; vale
    exactamente 1.0 si y solo si los tres criterios se cumplen.

    Args:
        ecg_filtered: ECG tras la cadena de filtros (0.5-45 Hz), 10-30 s.
        fs: Frecuencia de muestreo (Hz).
        thresholds: Umbrales; por defecto los de la Fase 2.

    Returns:
        ``QualityResult``; ``quality_flag = 1`` indica que la inferencia de
        presión arterial debe omitirse.
    """
    th = thresholds or SQIThresholds()
    x = np.asarray(ecg_filtered, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        # Señal con valores no finitos: rechazo inmediato, sin cómputo.
        return QualityResult(0.0, 0.0, 0.0, 0.0, 0.0, 1, ("no_finito",), 0, 0)
    bsqi, n_pt, n_cl = compute_bsqi(x, fs, th.match_tolerance_s)
    ksqi = compute_ksqi(x, fs, th.kurtosis_block_s, th.kurtosis_aggregate)
    psqi = compute_psqi(x, fs, th.psqi_num_band, th.psqi_den_band)
    ssqi = compute_ssqi(x)

    failed: list[str] = []
    if bsqi < th.bsqi_min:
        failed.append("bSQI")
    if ksqi < th.ksqi_min:
        failed.append("kSQI")
    if psqi < th.psqi_min:
        failed.append("pSQI")
    ratios = [
        min(1.0, max(0.0, bsqi / th.bsqi_min)),
        min(1.0, max(0.0, ksqi / th.ksqi_min)),
        min(1.0, max(0.0, psqi / th.psqi_min)),
    ]
    return QualityResult(
        bsqi=bsqi,
        ksqi=ksqi,
        psqi=psqi,
        ssqi=ssqi,
        sqi_composite=float(np.mean(ratios)),
        quality_flag=int(bool(failed)),
        failed_criteria=tuple(failed),
        n_beats_pan_tompkins=n_pt,
        n_beats_curve_length=n_cl,
    )


#: Mensajes de notificación al usuario por criterio incumplido (R4).
USER_MESSAGES: Mapping[str, str] = {
    "bSQI": "Los detectores de QRS no concuerdan: posible artefacto de movimiento.",
    "kSQI": "Morfología de ECG no fisiológica: ruido incoherente o saturación.",
    "pSQI": "Distribución espectral anómala: deriva de línea base o ruido muscular.",
    "no_finito": "Señal incompleta o con valores no válidos.",
}


@dataclass(frozen=True)
class InferenceOutcome:
    """Resultado de una inferencia protegida por la compuerta RF4."""

    blocked: bool
    prediction: Mapping[str, float] | None
    quality: QualityResult
    message: str


def gated_inference(
    ecg_filtered: FloatArray,
    fs: float,
    predict_fn: Callable[[FloatArray], Mapping[str, float]],
    thresholds: SQIThresholds | None = None,
) -> InferenceOutcome:
    """Ejecuta ``predict_fn`` solo si la ventana supera la compuerta.

    Si ``quality_flag = 1`` **no se invoca** ``predict_fn``: no se emite ningún
    valor numérico de PAS/PAD/PAM y se devuelve la causa del descarte y la
    indicación de reposicionar los electrodos (RF4, R4).
    """
    quality = assess_window(ecg_filtered, fs, thresholds)
    if quality.quality_flag == 1:
        reasons = " ".join(USER_MESSAGES[c] for c in quality.failed_criteria)
        msg = f"Estimación suspendida. {reasons} Reposicione los electrodos."
        return InferenceOutcome(True, None, quality, msg)
    return InferenceOutcome(
        False, predict_fn(ecg_filtered), quality, "Estimación válida."
    )


# --------------------------------------------------------------------------
# Métricas de calidad para el Data Quality Report
# --------------------------------------------------------------------------
def saturation_fraction(
    raw_counts: FloatArray, adc_min: float, adc_max: float, guard_codes: float = 0.0
) -> float:
    """Fracción de muestras en los rieles del ADC (tasa de saturación).

    Args:
        raw_counts: Muestras crudas en códigos ADC (o en la unidad de los
            rieles).
        adc_min: Valor mínimo representable.
        adc_max: Valor máximo representable.
        guard_codes: Margen para considerar "en riel" (por defecto 0).
    """
    x = np.asarray(raw_counts, dtype=np.float64)
    if x.size == 0:
        return 0.0
    at_rail = (x <= adc_min + guard_codes) | (x >= adc_max - guard_codes)
    return float(at_rail.mean())


def flatline_fraction(x: FloatArray, fs: float, min_duration_s: float = 0.5) -> float:
    """Fracción de la señal en tramos planos (derivada nula) >= ``min_duration_s``."""
    v = np.asarray(x, dtype=np.float64)
    if v.size < 2:
        return 0.0
    flat = np.concatenate(([False], np.diff(v) == 0.0))
    edges = np.diff(np.concatenate(([0], flat.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    min_len = round(min_duration_s * fs)
    total = sum(
        int(e - s) for s, e in zip(starts, ends, strict=True) if e - s >= min_len
    )
    return float(total / v.size)


def rejection_by_subject(
    quality_flags: Sequence[int],
    subject_ids: Sequence[str],
    alert_threshold: float = 0.30,
) -> dict[str, tuple[float, bool]]:
    """Tasa de descarte por sujeto y alerta de auditoría individual.

    Args:
        quality_flags: ``quality_flag`` por ventana.
        subject_ids: Sujeto de cada ventana.
        alert_threshold: Tasa a partir de la cual se solicita auditoría
            clínica individualizada (30 %).

    Returns:
        ``{subject_id: (tasa_de_rechazo, requiere_auditoria)}``.
    """
    flags = np.asarray(quality_flags, dtype=np.float64)
    ids = np.asarray(subject_ids)
    out: dict[str, tuple[float, bool]] = {}
    for sid in np.unique(ids):
        rate = float(flags[ids == sid].mean())
        out[str(sid)] = (rate, rate > alert_threshold)
    return out


@dataclass
class RejectionBalance:
    """Balance global de retención/rechazo de ventanas."""

    n_windows: int = 0
    n_rejected: int = 0
    by_criterion: dict[str, int] = field(default_factory=dict)

    @property
    def rejection_ratio(self) -> float:
        """Fracción de ventanas rechazadas."""
        return self.n_rejected / self.n_windows if self.n_windows else 0.0

    def update(self, result: QualityResult) -> None:
        """Acumula el resultado de una ventana."""
        self.n_windows += 1
        if result.quality_flag:
            self.n_rejected += 1
            for crit in result.failed_criteria:
                self.by_criterion[crit] = self.by_criterion.get(crit, 0) + 1
