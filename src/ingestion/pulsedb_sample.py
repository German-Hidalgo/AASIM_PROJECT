"""Muestreo estratificado de formas de onda de PulseDB v2.0 para el DQR de la Fase 2.

Los archivos de ``Segment_Files`` ocupan cientos de gigabytes; este módulo lee solo una
muestra reproducible (sujetos adultos elegidos al azar por fuente y ventanas al azar por
sujeto) y ejecuta sobre ella el pipeline de la Fase 2: censura de etiquetas, filtrado causal,
compuerta de calidad (RF4), extracción de características y medición de latencia (RNF2).

Cada ventana de PulseDB dura 10 s a 125 Hz (1 250 muestras). Se procesa el campo
``ECG_Raw`` con la cadena causal del proyecto; la etiqueta es la presión arterial invasiva
del segmento (``SegSBP``, ``SegDBP``). El script es reanudable: si se interrumpe, al
relanzarlo omite los sujetos ya procesados.

Autores: Rocha (ingeniería TI) y Buitrago (validación clínica).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

from src.features.extract_features import feature_names, process_window
from src.preprocessing.filters import (
    FilterConfig,
    apply_filter_chain,
    censor_reference_labels,
)
from src.sqi.quality_assessment import (
    flatline_fraction,
    match_beats,
    pan_tompkins_detector,
)

FS_PULSEDB: float = 125.0
CARPETA_FUENTE: dict[str, str] = {"MIMIC": "PulseDB_MIMIC", "VitalDB": "PulseDB_Vital"}
COLUMNAS_BASE: tuple[str, ...] = (
    "subject_id",
    "source",
    "biological_sex",
    "age",
    "win_index",
    "sbp_mmhg",
    "dbp_mmhg",
    "label_reason_code",
    "abp_lag_samples",
    "include_flag",
    "ppg_abp_corr",
    "raw_std_mv",
    "raw_ptp_mv",
    "flatline_fraction",
    "mains_detected",
    "mains_hz",
    "bsqi",
    "ksqi",
    "psqi",
    "ssqi",
    "sqi_composite",
    "quality_flag",
    "failed_criteria",
    "n_beats",
    "hr_bpm",
    "rpeak_f1_vs_pulsedb",
    "latency_ms",
)


def _leer(h: h5py.File, grupo: h5py.Group, campo: str, j: int) -> np.ndarray:
    """Lee el campo ``campo`` de la ventana ``j`` (referencia de objeto MATLAB)."""
    ref = grupo[campo][0, j]
    if not isinstance(ref, h5py.Reference):
        return np.array([np.nan])  # campo vacío en MATLAB (almacenado como número)
    return np.asarray(h[ref])


def _f1_picos(a: np.ndarray, b: np.ndarray, tol: int) -> float:
    """Concordancia F1 entre dos conjuntos de picos R con tolerancia ``tol`` muestras."""
    if a.size == 0 and b.size == 0:
        return 1.0
    if a.size == 0 or b.size == 0:
        return 0.0
    tp = match_beats(a, b, tol)
    return float(2.0 * tp / (a.size + b.size))


def seleccionar_sujetos(
    sujetos: pd.DataFrame,
    correspondencia: pd.DataFrame,
    n_por_fuente: int,
    semilla: int,
) -> pd.DataFrame:
    """Elige sujetos adultos al azar y de forma reproducible en cada fuente."""
    df = sujetos.merge(correspondencia, on="subject_id")
    df = df[df["Subj_Age"] >= 18.0]
    elegidos = []
    for fuente in CARPETA_FUENTE:
        sub = df[df["source"] == fuente].sort_values("subject_id")
        elegidos.append(sub.sample(n=min(n_por_fuente, len(sub)), random_state=semilla))
    plan = pd.concat(elegidos, ignore_index=True)
    # Intercala las fuentes para que cualquier prefijo del plan quede equilibrado.
    plan["_orden"] = plan.groupby("source").cumcount()
    plan = plan.sort_values(["_orden", "source"], kind="stable")
    return plan.drop(columns="_orden").reset_index(drop=True)


def procesar_sujeto(
    ruta: Path,
    fila: pd.Series,
    k_ventanas: int,
    rng: np.random.Generator,
    escritor: Any,
    columnas_feat: list[str],
    dir_ventanas: Path,
) -> int:
    """Procesa ``k_ventanas`` ventanas al azar de un archivo de sujeto."""
    cfg = FilterConfig(FS_PULSEDB)
    n_escritas = 0
    guardar: dict[str, list[np.ndarray]] = {"aceptadas": [], "rechazadas": []}
    with h5py.File(ruta, "r") as h:
        g = h["Subj_Wins"]
        n = g["SegSBP"].shape[1]
        idx = np.sort(rng.choice(n, size=min(k_ventanas, n), replace=False))
        for j in idx:
            ecg = _leer(h, g, "ECG_Raw", j).ravel().astype(np.float64)
            sbp = float(_leer(h, g, "SegSBP", j).ravel()[0])
            dbp = float(_leer(h, g, "SegDBP", j).ravel()[0])
            lag = float(_leer(h, g, "ABP_Lag", j).ravel()[0])
            inc_raw = float(_leer(h, g, "IncludeFlag", j).ravel()[0])
            inc = int(inc_raw) if np.isfinite(inc_raw) else -1  # -1: campo ausente
            corr = float(_leer(h, g, "PPG_ABP_Corr", j).ravel()[0])
            picos_ref = _leer(h, g, "ECG_RPeaks", j).ravel().astype(np.float64)
            picos_ref = picos_ref[np.isfinite(picos_ref)].astype(int)
            cens = censor_reference_labels(np.array([sbp]), np.array([dbp]))
            fila_out: dict[str, Any] = {
                "subject_id": fila["subject_id"],
                "source": fila["source"],
                "biological_sex": fila["biological_sex"],
                "age": fila["Subj_Age"],
                "win_index": int(j),
                "sbp_mmhg": sbp,
                "dbp_mmhg": dbp,
                "label_reason_code": int(cens.reason_code[0]),
                "abp_lag_samples": lag,
                "include_flag": inc,
                "ppg_abp_corr": corr,
            }
            if not np.all(np.isfinite(ecg)) or ecg.size != int(10 * FS_PULSEDB):
                fila_out.update({"quality_flag": 1, "failed_criteria": "no_finito"})
            else:
                filt = apply_filter_chain(ecg, cfg)
                res = process_window(ecg, FS_PULSEDB, cfg)
                q = res.quality
                pt = pan_tompkins_detector(filt.signal, FS_PULSEDB)
                rr = np.diff(pt) / FS_PULSEDB
                fila_out.update(
                    {
                        "raw_std_mv": float(np.std(ecg)),
                        "raw_ptp_mv": float(np.ptp(ecg)),
                        "flatline_fraction": flatline_fraction(ecg, FS_PULSEDB),
                        "mains_detected": int(filt.mains.detected),
                        "mains_hz": filt.mains.frequency_hz,
                        "bsqi": q.bsqi,
                        "ksqi": q.ksqi,
                        "psqi": q.psqi,
                        "ssqi": q.ssqi,
                        "sqi_composite": q.sqi_composite,
                        "quality_flag": q.quality_flag,
                        "failed_criteria": "|".join(q.failed_criteria),
                        "n_beats": int(pt.size),
                        "hr_bpm": float(60.0 / np.median(rr)) if rr.size else np.nan,
                        "rpeak_f1_vs_pulsedb": _f1_picos(
                            pt, picos_ref, int(0.05 * FS_PULSEDB)
                        ),
                        "latency_ms": 1e3 * res.total_latency_s,
                    }
                )
                if res.features is not None:
                    fila_out.update(res.features.features)
                clave = "aceptadas" if q.quality_flag == 0 else "rechazadas"
                if len(guardar[clave]) < 4:
                    guardar[clave].append(ecg)
            escritor.writerow(
                [fila_out.get(c, "") for c in (*COLUMNAS_BASE, *columnas_feat)]
            )
            n_escritas += 1
    for clave, lista in guardar.items():
        if lista:
            dir_ventanas.mkdir(parents=True, exist_ok=True)
            np.save(dir_ventanas / f"{fila['subject_id']}_{clave}.npy", np.stack(lista))
    return n_escritas


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: procesa sujetos hasta agotar el tiempo disponible."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raiz-pulsedb", type=Path, required=True)
    p.add_argument(
        "--catalogo", type=Path, default=Path("data/processed/pulsedb_catalogo")
    )
    p.add_argument(
        "--tabla-correspondencia",
        type=Path,
        default=Path("data/metadata/tabla_correspondencia_RESTRINGIDA.csv"),
    )
    p.add_argument("--out", type=Path, default=Path("data/processed/pulsedb_muestra"))
    p.add_argument("--n-por-fuente", type=int, default=40)
    p.add_argument("--k-ventanas", type=int, default=60)
    p.add_argument("--semilla", type=int, default=20260920)
    p.add_argument(
        "--tiempo-max", type=float, default=150.0, help="segundos por corrida"
    )
    p.add_argument(
        "--parte", type=int, default=0, help="índice de la parte (paralelismo)"
    )
    p.add_argument("--partes", type=int, default=1, help="número de partes en paralelo")
    args = p.parse_args(argv)

    t0 = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    sujetos = pd.read_csv(args.catalogo / "sujetos.csv")
    corr = pd.read_csv(args.tabla_correspondencia)
    plan = seleccionar_sujetos(sujetos, corr, args.n_por_fuente, args.semilla)
    plan = plan.iloc[args.parte :: args.partes]
    ruta_csv = args.out / (
        "ventanas.csv" if args.partes == 1 else f"ventanas_p{args.parte}.csv"
    )
    columnas_feat = feature_names()
    hechos: set[str] = set()
    for previo in args.out.glob("ventanas*.csv"):
        try:
            hechos |= set(pd.read_csv(previo, usecols=["subject_id"])["subject_id"])
        except (pd.errors.EmptyDataError, ValueError):
            continue  # archivo aún vacío de otra parte en ejecución
    nuevo = not ruta_csv.exists()
    with open(ruta_csv, "a", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow([*COLUMNAS_BASE, *columnas_feat])
        for _, fila in plan.iterrows():
            if fila["subject_id"] in hechos:
                continue
            if time.time() - t0 > args.tiempo_max:
                print("Tiempo agotado; relance para continuar.", flush=True)
                return 3
            nombre = str(fila["nombre_original_pulsedb"]).split("_")[0]
            ruta = args.raiz_pulsedb / "Segment_Files" / CARPETA_FUENTE[fila["source"]]
            rng = np.random.default_rng(
                [args.semilla, int(str(fila["subject_id"])[5:])]
            )
            try:
                n = procesar_sujeto(
                    ruta / f"{nombre}.mat",
                    fila,
                    args.k_ventanas,
                    rng,
                    w,
                    columnas_feat,
                    args.out / "ventanas_npy",
                )
            except (KeyError, TypeError, ValueError, OSError) as exc:
                print(f"ERROR {fila['subject_id']}: {exc!r}", flush=True)
                continue
            f.flush()
            hechos.add(fila["subject_id"])
            print(
                f"{fila['subject_id']} {fila['source']}: {n} ventanas "
                f"({len(hechos)}/{len(plan)}) {time.time() - t0:6.1f} s",
                flush=True,
            )
    print("Muestreo completo.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
