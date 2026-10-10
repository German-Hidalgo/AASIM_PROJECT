"""Cadena de filtrado digital de ECG y censura hemodinámica de etiquetas.

Proyecto AASIM (SaMD para la estimación continua de PAS/PAD/PAM a partir de
ECG) - Fase 2: Preparación de datos, gobernanza y mitigación de riesgos de
validez.

Responsables
------------
* Implementación y comentarios técnicos: Luis Carlos Rocha (Ingeniería TI).
* Límites hemodinámicos de las etiquetas de referencia (RF3, S1): Juan
  Manuel Buitrago (Validación Clínica).

Requisitos del sistema atendidos
--------------------------------
* RF1: procesamiento automatizado de la bioseñal.
* RF3 / S1: admisibilidad de las etiquetas del dispositivo de referencia.
* R1 (ruido y artefactos): mitigado con una cadena de filtros de fase
  controlada (Butterworth pasa-altos, notch adaptativo de red eléctrica y
  Butterworth pasa-bajos).
* RNF2: el modo causal permite procesar por bloques sin superar la cota de
  latencia de 5 s.

Nota metodológica sobre causalidad (lookahead bias)
---------------------------------------------------
El filtrado de fase cero (``sosfiltfilt``) recorre la señal en ambos sentidos
y, por tanto, usa muestras futuras para calcular muestras pasadas. Es válido
únicamente en análisis retrospectivo (auditoría de calidad, delineación de
referencia, elaboración del Data Quality Report). Queda prohibido en cualquier
ruta de código destinada a inferencia en tiempo real; para ello se dispone del
modo causal (``FilterMode.CAUSAL``) y de la clase de flujo ``CausalECGFilter``.
Como principio de consistencia entrenamiento-despliegue, se recomienda extraer
las características de entrenamiento con el mismo modo causal que se usará en
producción; el modo de fase cero se reserva para auditoría.

Convenciones
------------
* Frecuencias en Hz, tiempos en s (salvo sufijo ``_ms``), presiones en mmHg.
* Las señales son vectores ``float64`` de una sola derivación (derivación II).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from numpy.typing import NDArray
from scipy import signal
from scipy.interpolate import CubicSpline

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

#: Frecuencia de muestreo mínima admitida por el esquema de metadatos.
MIN_SAMPLING_RATE_HZ: float = 125.0
#: Factor de calidad mínimo del filtro muesca exigido por la especificación.
MIN_NOTCH_Q: float = 35.0


class FilterMode(str, Enum):
    """Modo de aplicación de la cadena de filtros."""

    #: Filtrado hacia adelante (``sosfilt``); apto para tiempo real.
    CAUSAL = "causal"
    #: Filtrado bidireccional (``sosfiltfilt``); solo análisis retrospectivo.
    ZERO_PHASE = "zero_phase"


class NonCausalFilterError(RuntimeError):
    """Se intentó usar filtrado bidireccional en una ruta de inferencia."""


@dataclass(frozen=True)
class FilterConfig:
    """Parámetros de diseño de la cadena de filtrado.

    Attributes:
        fs: Frecuencia de muestreo nativa (Hz); debe ser >= 125 Hz (ver diccionario de datos).
        hp_cutoff_hz: Frecuencia de corte (-3 dB) del pasa-altos que elimina
            la deriva de línea base (0.1-0.5 Hz).
        hp_order: Orden del Butterworth pasa-altos (2 según la especificación).
        lp_cutoff_hz: Frecuencia de corte del pasa-bajos (ruido mioeléctrico).
        lp_order: Orden del Butterworth pasa-bajos (4 según la especificación).
        notch_q: Factor de calidad del notch; la especificación exige Q >= 35.
        mains_candidates_hz: Frecuencias nominales de red a inspeccionar.
        mains_search_halfwidth_hz: Semiancho de la búsqueda del pico de red
            alrededor de cada frecuencia nominal (deriva de la red eléctrica).
        mains_min_prominence_db: Prominencia mínima del pico respecto a su
            entorno espectral para considerar que hay interferencia de red.
    """

    fs: float
    hp_cutoff_hz: float = 0.5
    hp_order: int = 2
    lp_cutoff_hz: float = 45.0
    lp_order: int = 4
    notch_q: float = 35.0
    mains_candidates_hz: tuple[float, ...] = (50.0, 60.0)
    mains_search_halfwidth_hz: float = 1.0
    mains_min_prominence_db: float = 6.0

    def __post_init__(self) -> None:
        if self.fs < MIN_SAMPLING_RATE_HZ:
            raise ValueError(
                f"fs={self.fs} Hz inferior al mínimo de {MIN_SAMPLING_RATE_HZ} Hz"
            )
        if self.notch_q < MIN_NOTCH_Q:
            raise ValueError(f"Q={self.notch_q} inferior al mínimo {MIN_NOTCH_Q}")
        nyq = self.fs / 2.0
        if not 0.0 < self.hp_cutoff_hz < self.lp_cutoff_hz < nyq:
            raise ValueError("Se requiere 0 < f_hp < f_lp < fs/2")
        for f0 in self.mains_candidates_hz:
            if f0 + self.mains_search_halfwidth_hz >= nyq:
                raise ValueError(f"Frecuencia de red {f0} Hz fuera de Nyquist")


@dataclass(frozen=True)
class MainsEstimate:
    """Resultado de la estimación de la interferencia de red eléctrica."""

    frequency_hz: float
    prominence_db: float
    detected: bool


@dataclass(frozen=True)
class FilterResult:
    """Salida de la cadena de filtrado."""

    signal: FloatArray
    mode: FilterMode
    mains: MainsEstimate
    notch_applied: bool


# --------------------------------------------------------------------------
# Diseño de filtros
# --------------------------------------------------------------------------
def design_highpass(cfg: FilterConfig) -> FloatArray:
    """Butterworth pasa-altos en secciones de segundo orden (SOS).

    El corte nominal (-3 dB) corresponde al prototipo unidireccional. En modo
    de fase cero la respuesta en magnitud se eleva al cuadrado, de modo que la
    atenuación en ``hp_cutoff_hz`` es de -6 dB.
    """
    sos = signal.butter(
        cfg.hp_order, cfg.hp_cutoff_hz, btype="highpass", fs=cfg.fs, output="sos"
    )
    return np.asarray(sos, dtype=np.float64)


def design_lowpass(cfg: FilterConfig) -> FloatArray:
    """Butterworth pasa-bajos de orden ``lp_order`` en formato SOS."""
    sos = signal.butter(
        cfg.lp_order, cfg.lp_cutoff_hz, btype="lowpass", fs=cfg.fs, output="sos"
    )
    return np.asarray(sos, dtype=np.float64)


def design_notch(f0_hz: float, fs: float, q: float) -> FloatArray:
    """Filtro muesca IIR de segundo orden en formato SOS.

    Args:
        f0_hz: Frecuencia central a rechazar (Hz).
        fs: Frecuencia de muestreo (Hz).
        q: Factor de calidad; el ancho de banda a -3 dB es ``f0_hz / q``.

    Raises:
        ValueError: Si ``q`` es inferior al mínimo exigido (35).
    """
    if q < MIN_NOTCH_Q:
        raise ValueError(f"Q={q} inferior al mínimo {MIN_NOTCH_Q}")
    b, a = signal.iirnotch(f0_hz, q, fs=fs)
    return np.asarray(signal.tf2sos(b, a), dtype=np.float64)


# --------------------------------------------------------------------------
# Estimación adaptativa de la frecuencia de red
# --------------------------------------------------------------------------
def estimate_mains_frequency(x: FloatArray, cfg: FilterConfig) -> MainsEstimate:
    """Localiza la interferencia de red (50/60 Hz) y su desviación fina.

    Se estima la densidad espectral de potencia con el método de Welch y, para
    cada frecuencia nominal candidata, se busca el máximo espectral dentro de
    ``±mains_search_halfwidth_hz``. La prominencia se define como el cociente
    (en dB) entre ese máximo y la mediana de la PSD en dos bandas laterales
    contiguas (de 2 a 5 Hz a cada lado del pico), lo que resiste la pendiente
    espectral. Se elige el candidato con mayor prominencia.

    Args:
        x: Segmento de ECG (idealmente >= 4 s para resolución de 0.25 Hz).
        cfg: Configuración de la cadena.

    Returns:
        ``MainsEstimate``; ``detected`` es ``False`` si ninguna prominencia
        supera ``mains_min_prominence_db``. En ese caso no debe aplicarse el
        notch, evitando distorsionar el espectro sin necesidad.
    """
    nperseg = int(min(x.size, round(4.0 * cfg.fs)))
    freqs, psd = signal.welch(x, fs=cfg.fs, nperseg=nperseg)
    best = MainsEstimate(
        frequency_hz=cfg.mains_candidates_hz[0], prominence_db=-np.inf, detected=False
    )
    eps = np.finfo(np.float64).tiny
    for f_nom in cfg.mains_candidates_hz:
        band = (freqs >= f_nom - cfg.mains_search_halfwidth_hz) & (
            freqs <= f_nom + cfg.mains_search_halfwidth_hz
        )
        if not band.any():
            continue
        idx_band = np.flatnonzero(band)
        k = idx_band[np.argmax(psd[idx_band])]
        f_peak = float(freqs[k])
        side = ((freqs >= f_peak - 5.0) & (freqs <= f_peak - 2.0)) | (
            (freqs >= f_peak + 2.0) & (freqs <= f_peak + 5.0)
        )
        # Las bandas laterales no deben rebasar el Nyquist ni quedar vacías.
        if not side.any():
            continue
        floor = float(np.median(psd[side]))
        prom_db = 10.0 * np.log10((psd[k] + eps) / (floor + eps))
        if prom_db > best.prominence_db:
            best = MainsEstimate(f_peak, float(prom_db), False)
    detected = best.prominence_db >= cfg.mains_min_prominence_db
    return MainsEstimate(best.frequency_hz, best.prominence_db, bool(detected))


# --------------------------------------------------------------------------
# Aplicación de la cadena
# --------------------------------------------------------------------------
def _run_sos(sos: FloatArray, x: FloatArray, mode: FilterMode) -> FloatArray:
    """Aplica una cascada SOS en el modo solicitado."""
    if mode is FilterMode.ZERO_PHASE:
        return np.asarray(signal.sosfiltfilt(sos, x), dtype=np.float64)
    # Condición inicial estacionaria para minimizar el transitorio de arranque.
    zi = signal.sosfilt_zi(sos) * x[0]
    y, _ = signal.sosfilt(sos, x, zi=zi)
    return np.asarray(y, dtype=np.float64)


def apply_filter_chain(
    x: FloatArray,
    cfg: FilterConfig,
    mode: FilterMode = FilterMode.CAUSAL,
    mains: MainsEstimate | None = None,
) -> FilterResult:
    """Aplica notch adaptativo -> pasa-altos -> pasa-bajos.

    Args:
        x: ECG crudo (una derivación) sin valores no finitos.
        cfg: Parámetros de diseño.
        mode: ``CAUSAL`` (por defecto, apto para inferencia) o
            ``ZERO_PHASE`` (solo análisis retrospectivo).
        mains: Estimación de red precalculada; si es ``None`` se estima sobre
            ``x``.

    Returns:
        ``FilterResult`` con la señal filtrada y los metadatos del proceso.

    Raises:
        ValueError: Si ``x`` contiene NaN/inf o es demasiado corta.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or x.size < int(cfg.fs):
        raise ValueError("Se requiere un vector 1-D de al menos 1 s de señal")
    if not np.all(np.isfinite(x)):
        raise ValueError("Señal con valores no finitos; use censor_discontinuities")

    est = mains if mains is not None else estimate_mains_frequency(x, cfg)
    y = x
    if est.detected:
        y = _run_sos(design_notch(est.frequency_hz, cfg.fs, cfg.notch_q), y, mode)
    y = _run_sos(design_highpass(cfg), y, mode)
    y = _run_sos(design_lowpass(cfg), y, mode)
    return FilterResult(signal=y, mode=mode, mains=est, notch_applied=est.detected)


def assert_causal_for_inference(mode: FilterMode) -> None:
    """Impide el uso de filtros bidireccionales en la ruta de inferencia.

    Debe invocarse al inicio de toda función que construya la vía de tiempo
    real (RNF2) para blindar el pipeline contra el sesgo retrospectivo.

    Raises:
        NonCausalFilterError: Si ``mode`` no es ``FilterMode.CAUSAL``.
    """
    if mode is not FilterMode.CAUSAL:
        raise NonCausalFilterError(
            "El filtrado de fase cero usa muestras futuras y está prohibido "
            "en inferencia en tiempo real (lookahead bias)."
        )


class CausalECGFilter:
    """Filtro causal con estado para procesamiento por bloques (streaming).

    Mantiene el estado interno de cada sección SOS entre llamadas, de modo que
    el resultado concatenado de ``process`` es idéntico al de filtrar la señal
    completa de una sola vez. El notch puede resintonizarse cuando la
    frecuencia de red se desplaza (``retune_notch``), reiniciando únicamente el
    estado de esa etapa.
    """

    def __init__(self, cfg: FilterConfig, mains_hz: float | None = None) -> None:
        self._cfg = cfg
        self._sos_hp = design_highpass(cfg)
        self._sos_lp = design_lowpass(cfg)
        self._sos_notch: FloatArray | None = None
        self._zi_notch: FloatArray | None = None
        self._zi_hp: FloatArray | None = None
        self._zi_lp: FloatArray | None = None
        if mains_hz is not None:
            self.retune_notch(mains_hz)

    def retune_notch(self, mains_hz: float | None) -> None:
        """Sintoniza (o desactiva con ``None``) el notch de red."""
        if mains_hz is None:
            self._sos_notch, self._zi_notch = None, None
            return
        self._sos_notch = design_notch(mains_hz, self._cfg.fs, self._cfg.notch_q)
        self._zi_notch = None

    def process(self, chunk: FloatArray) -> FloatArray:
        """Filtra un bloque contiguo de muestras preservando el estado."""
        y = np.asarray(chunk, dtype=np.float64)
        if y.size == 0:
            return y
        if self._sos_notch is not None:
            y, self._zi_notch = self._step(self._sos_notch, y, self._zi_notch)
        y, self._zi_hp = self._step(self._sos_hp, y, self._zi_hp)
        y, self._zi_lp = self._step(self._sos_lp, y, self._zi_lp)
        return y

    @staticmethod
    def _step(
        sos: FloatArray, y: FloatArray, zi: FloatArray | None
    ) -> tuple[FloatArray, FloatArray]:
        if zi is None:
            zi = signal.sosfilt_zi(sos) * y[0]
        out, zf = signal.sosfilt(sos, y, zi=zi)
        return np.asarray(out, dtype=np.float64), np.asarray(zf, dtype=np.float64)


# --------------------------------------------------------------------------
# Datos faltantes y discontinuidades
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class GapReport:
    """Resumen del tratamiento de discontinuidades de señal."""

    n_gaps: int
    n_interpolated: int
    n_unrepaired: int
    longest_gap_ms: float
    discard_window: bool
    invalid_fraction: float


def censor_discontinuities(
    x: FloatArray,
    fs: float,
    tp_mask: BoolArray | None = None,
    interp_max_ms: float = 20.0,
    censor_ms: float = 200.0,
) -> tuple[FloatArray, BoolArray, GapReport]:
    """Aplica la política de datos faltantes de la Fase 2.

    Política (sin imputación sintética generalizada):

    * Discontinuidad < ``interp_max_ms`` **y** confinada al segmento isoeléctrico
      TP (``tp_mask``): se repara con spline cúbico.
    * Cualquier otra discontinuidad permanece sin reparar y su segmento se
      marca como inválido (``valid_mask == False``).
    * Si alguna discontinuidad supera ``censor_ms`` (200 ms) se recomienda
      descartar la ventana completa (``GapReport.discard_window``): interpolar
      complejos QRS crearía una regularidad temporal falsa que anularía la
      fidelidad de las métricas HRV.

    Args:
        x: Señal con ``NaN`` en las muestras perdidas.
        fs: Frecuencia de muestreo (Hz).
        tp_mask: Máscara booleana (mismo largo) de muestras en segmento TP. Si
            es ``None`` no se permite ninguna interpolación.
        interp_max_ms: Longitud máxima interpolable.
        censor_ms: Longitud a partir de la cual se descarta la ventana.

    Returns:
        Tupla ``(señal_reparada, valid_mask, informe)``.
    """
    y = np.asarray(x, dtype=np.float64).copy()
    missing = ~np.isfinite(y)
    valid = ~missing
    if not missing.any():
        return y, valid, GapReport(0, 0, 0, 0.0, False, 0.0)

    edges = np.diff(np.concatenate(([0], missing.view(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)  # exclusivo
    n_interp = 0
    longest_ms = 0.0
    for s, e in zip(starts, ends, strict=True):
        length_ms = 1000.0 * (e - s) / fs
        longest_ms = max(longest_ms, length_ms)
        in_tp = tp_mask is not None and bool(np.all(tp_mask[s:e]))
        has_support = s > 1 and e < y.size - 1
        if length_ms < interp_max_ms and in_tp and has_support:
            lo, hi = max(0, s - 3), min(y.size, e + 3)
            idx = np.arange(lo, hi)
            good = idx[np.isfinite(y[lo:hi])]
            spline = CubicSpline(good, y[good])
            y[s:e] = spline(np.arange(s, e))
            valid[s:e] = True
            n_interp += 1
    n_unrepaired = len(starts) - n_interp
    report = GapReport(
        n_gaps=len(starts),
        n_interpolated=n_interp,
        n_unrepaired=n_unrepaired,
        longest_gap_ms=float(longest_ms),
        discard_window=bool(longest_ms > censor_ms),
        invalid_fraction=float(1.0 - valid.mean()),
    )
    return y, valid, report


# --------------------------------------------------------------------------
# Censura hemodinámica de etiquetas de referencia (RF3, S1)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class HemodynamicLimits:
    """Límites de admisibilidad hemodinámica definidos por la supervisión clínica.

    Attributes:
        sbp_range: Intervalo admisible de PAS (mmHg).
        dbp_range: Intervalo admisible de PAD (mmHg).
        pulse_pressure_min: Presión de pulso mínima (PAS - PAD, mmHg).
        pulse_pressure_max: Presión de pulso máxima; ``None`` desactiva el
            límite superior (no fijado en esta versión de la especificación).
    """

    sbp_range: tuple[float, float] = (70.0, 240.0)
    dbp_range: tuple[float, float] = (40.0, 140.0)
    pulse_pressure_min: float = 20.0
    pulse_pressure_max: float | None = None


#: Códigos de motivo de exclusión (0 = lectura admisible).
REASON_OK = 0
REASON_NON_FINITE = 1
REASON_SBP_RANGE = 2
REASON_DBP_RANGE = 3
REASON_SBP_LE_DBP = 4
REASON_PP_LOW = 5
REASON_PP_HIGH = 6
REASON_LABELS: dict[int, str] = {
    REASON_OK: "admisible",
    REASON_NON_FINITE: "valor no finito",
    REASON_SBP_RANGE: "PAS fuera de rango",
    REASON_DBP_RANGE: "PAD fuera de rango",
    REASON_SBP_LE_DBP: "PAS <= PAD",
    REASON_PP_LOW: "presión de pulso inferior al mínimo",
    REASON_PP_HIGH: "presión de pulso superior al máximo",
}


@dataclass(frozen=True)
class LabelCensorResult:
    """Resultado de la censura de etiquetas de presión arterial."""

    valid_mask: BoolArray
    reason_code: NDArray[np.int8]
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def exclusion_rate(self) -> float:
        """Fracción de lecturas excluidas."""
        return float(1.0 - self.valid_mask.mean()) if self.valid_mask.size else 0.0


def censor_reference_labels(
    sbp: FloatArray,
    dbp: FloatArray,
    limits: HemodynamicLimits | None = None,
) -> LabelCensorResult:
    """Censura lecturas de referencia hemodinámicamente inadmisibles.

    Se excluyen las lecturas con PAS fuera de [70, 240] mmHg, PAD fuera de
    [40, 140] mmHg, PAS <= PAD o presión de pulso < 20 mmHg (típicas de
    despresurización incompleta del manguito o transitorios mecánicos del
    catéter). Cuando varias condiciones coinciden, se registra la primera en
    orden de prioridad de ``REASON_*``.

    Args:
        sbp: PAS de referencia (mmHg).
        dbp: PAD de referencia (mmHg).
        limits: Límites; por defecto los de la supervisión clínica.

    Returns:
        ``LabelCensorResult`` con máscara de admisibilidad, código de motivo
        por lectura y conteo por motivo.
    """
    lim = limits or HemodynamicLimits()
    s = np.asarray(sbp, dtype=np.float64)
    d = np.asarray(dbp, dtype=np.float64)
    if s.shape != d.shape:
        raise ValueError("sbp y dbp deben tener la misma forma")
    pp = s - d
    code = np.zeros(s.shape, dtype=np.int8)

    def _mark(mask: BoolArray, reason: int) -> None:
        code[(code == REASON_OK) & mask] = reason

    _mark(~(np.isfinite(s) & np.isfinite(d)), REASON_NON_FINITE)
    with np.errstate(invalid="ignore"):
        _mark((s < lim.sbp_range[0]) | (s > lim.sbp_range[1]), REASON_SBP_RANGE)
        _mark((d < lim.dbp_range[0]) | (d > lim.dbp_range[1]), REASON_DBP_RANGE)
        _mark(s <= d, REASON_SBP_LE_DBP)
        _mark(pp < lim.pulse_pressure_min, REASON_PP_LOW)
        if lim.pulse_pressure_max is not None:
            _mark(pp > lim.pulse_pressure_max, REASON_PP_HIGH)

    valid = code == REASON_OK
    counts = {label: int(np.sum(code == c)) for c, label in REASON_LABELS.items()}
    return LabelCensorResult(valid_mask=valid, reason_code=code, counts=counts)


def mean_arterial_pressure(sbp: FloatArray, dbp: FloatArray) -> FloatArray:
    """Aproximación clásica de la PAM: ``PAD + (PAS - PAD) / 3`` (mmHg).

    Debe usarse solo cuando el comparador no entrega la PAM medida; la
    aproximación pierde exactitud con frecuencias cardíacas elevadas.
    """
    s = np.asarray(sbp, dtype=np.float64)
    d = np.asarray(dbp, dtype=np.float64)
    return d + (s - d) / 3.0


def flag_unstable_reference(
    t_s: FloatArray,
    sbp: FloatArray,
    max_delta_mmhg: float = 15.0,
    span_s: float = 120.0,
) -> BoolArray:
    """Marca lecturas de referencia inestables en reposo (mitigación de R3).

    Una lectura se marca como inestable si, dentro de la ventana móvil de
    ``span_s`` segundos que la contiene, el rango de PAS supera
    ``max_delta_mmhg``. Debe aplicarse solo a segmentos en reposo; los
    cambios fisiológicos reales (estrés agudo, maniobras) no deben censurarse.

    Args:
        t_s: Instantes de las lecturas (s), no decrecientes.
        sbp: PAS de referencia (mmHg).
        max_delta_mmhg: Variación máxima tolerada (15 mmHg).
        span_s: Duración de la ventana (120 s).

    Returns:
        Vector booleano; ``True`` indica lectura inestable.
    """
    t = np.asarray(t_s, dtype=np.float64)
    s = np.asarray(sbp, dtype=np.float64)
    if t.shape != s.shape:
        raise ValueError("t_s y sbp deben tener la misma forma")
    if t.size and np.any(np.diff(t) < 0):
        raise ValueError("t_s debe ser no decreciente")
    unstable = np.zeros(t.shape, dtype=bool)
    for i in range(t.size):
        lo = np.searchsorted(t, t[i] - span_s, side="left")
        hi = np.searchsorted(t, t[i] + span_s, side="right")
        # Todas las ventanas de duración span_s que contienen la lectura i.
        for j in range(lo, i + 1):
            end = np.searchsorted(t, t[j] + span_s, side="right")
            seg = s[j : min(end, hi)]
            if seg.size > 1 and np.ptp(seg) > max_delta_mmhg:
                unstable[i] = True
                break
    return unstable
