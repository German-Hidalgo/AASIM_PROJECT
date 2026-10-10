"""Generador de ECG sintético para verificación funcional del pipeline.

Proyecto AASIM - Fase 2 (Luis Carlos Rocha, Ingeniería TI).

Los registros producidos aquí NO son datos clínicos ni pretenden serlo: se usan
exclusivamente para verificar el comportamiento determinista de los módulos
(filtros, SQI, extracción de características, partición y latencia) con
verdad-terreno conocida. Ningún resultado obtenido con estas señales constituye
evidencia de desempeño clínico.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class SyntheticRecord:
    """ECG sintético con su verdad-terreno."""

    ecg_mv: FloatArray
    fs: float
    r_peaks: NDArray[np.int64]
    rr_s: FloatArray


# (centro relativo a R [s], amplitud [mV], desviación estándar [s])
_WAVES = {
    "P": (-0.20, 0.10, 0.022),
    "Q": (-0.028, -0.10, 0.008),
    "R": (0.0, 1.00, 0.014),
    "S": (0.030, -0.22, 0.010),
    "T": (0.27, 0.25, 0.055),
}


def make_ecg(
    duration_s: float = 30.0,
    fs: float = 250.0,
    hr_bpm: float = 70.0,
    seed: int = 0,
    hrv_lf: float = 0.03,
    hrv_hf: float = 0.02,
) -> SyntheticRecord:
    """Genera un ECG limpio de derivación II con variabilidad de RR.

    Args:
        duration_s: Duración (s).
        fs: Frecuencia de muestreo (Hz).
        hr_bpm: Frecuencia cardíaca media.
        seed: Semilla del generador.
        hrv_lf: Amplitud (s) de la modulación de baja frecuencia (0.1 Hz).
        hrv_hf: Amplitud (s) de la modulación respiratoria (0.25 Hz).
    """
    rng = np.random.default_rng(seed)
    mean_rr = 60.0 / hr_bpm
    t_beats: list[float] = []
    t = 0.4 + rng.uniform(0.0, 0.1)
    while t < duration_s - 0.6:
        t_beats.append(t)
        rr = (
            mean_rr
            + hrv_lf * np.sin(2 * np.pi * 0.10 * t)
            + hrv_hf * np.sin(2 * np.pi * 0.25 * t)
            + rng.normal(0.0, 0.008)
        )
        t += rr
    beats = np.asarray(t_beats)
    n = int(duration_s * fs)
    time = np.arange(n) / fs
    ecg = np.zeros(n)
    rr_arr = np.diff(beats, prepend=beats[0] - mean_rr)
    for tb, rr in zip(beats, rr_arr, strict=True):
        scale = np.sqrt(rr / 0.857)  # el QT crece con la raíz del RR
        for name, (c, a, s) in _WAVES.items():
            centre = tb + (c * scale if name in ("T", "S") else c)
            ecg += a * np.exp(-0.5 * ((time - centre) / s) ** 2)
    r_idx = np.round(beats * fs).astype(np.int64)
    return SyntheticRecord(ecg, fs, r_idx, np.diff(beats))


def contaminate(
    ecg: FloatArray,
    fs: float,
    seed: int = 1,
    mains_hz: float | None = 50.0,
    mains_amp: float = 0.15,
    baseline_amp: float = 0.4,
    emg_std: float = 0.02,
) -> FloatArray:
    """Añade deriva de línea base, interferencia de red y ruido de banda ancha."""
    rng = np.random.default_rng(seed)
    t = np.arange(ecg.size) / fs
    out = ecg + baseline_amp * np.sin(2 * np.pi * 0.25 * t + 0.7)
    out += 0.5 * baseline_amp * np.sin(2 * np.pi * 0.08 * t)
    if mains_hz is not None:
        out += mains_amp * np.sin(2 * np.pi * mains_hz * t)
    out += rng.normal(0.0, emg_std, ecg.size)
    return out


def make_corrupted(ecg: FloatArray, fs: float, seed: int = 2) -> FloatArray:
    """ECG severamente degradado (ruido incoherente dominante) para pruebas RF4."""
    rng = np.random.default_rng(seed)
    return ecg * 0.15 + rng.normal(0.0, 0.6, ecg.size)
