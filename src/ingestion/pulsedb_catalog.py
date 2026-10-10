"""Catálogo de metadatos y etiquetas de PulseDB v2.0 para la Fase 2 del sistema AASIM.

Lee únicamente los archivos ``Info_Files/PulseDB_Info.mat`` (metadatos por sujeto y presión
de referencia por segmento) sin abrir las formas de onda de ``Segment_Files``. Con ello se
obtiene, a bajo costo, la información necesaria para el Data Quality Report: distribución de
PAS/PAD, cuotas de la norma ANSI/AAMI/ISO 81060-2, composición demográfica y balance entre
las dos fuentes (MIMIC y VitalDB).

Privacidad (RNF1): el nombre original de cada sujeto (``p000160_0``) y las marcas temporales
de caso (fechas desplazadas) no se exportan al catálogo analítico. El catálogo usa
identificadores opacos ``SUBJ-xxxxx`` asignados por permutación aleatoria; la tabla de
correspondencia se escribe aparte, en un archivo de acceso restringido.

Autores: Rocha (ingeniería TI) e Hidalgo (privacidad).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import h5py
import numpy as np

CAMPOS_ESCALARES: tuple[str, ...] = (
    "Subj_Age",
    "Subj_BMI",
    "Subj_Height",
    "Subj_Weight",
)


def _cadena(a: np.ndarray) -> str:
    """Decodifica una cadena MATLAB (uint16) a ``str``."""
    return "".join(chr(int(c)) for c in np.asarray(a).ravel())


def _escalar(h: h5py.File, ref: Any) -> float:
    """Lee un escalar numérico referenciado; devuelve NaN si el dato no existe."""
    a = np.asarray(h[ref], dtype=float).ravel()
    return float(a[0]) if a.size else float("nan")


def catalogar(
    ruta_info: Path,
    salida: Path,
    ruta_corr: Path,
    max_sujetos: int | None = None,
    cada: int = 100,
    semilla: int | None = None,
) -> None:
    """Extrae el catálogo por sujeto y por segmento.

    Parameters
    ----------
    ruta_info:
        Ruta a ``PulseDB_Info.mat``.
    salida:
        Directorio de salida (se crea si no existe).
    ruta_corr:
        Archivo de la tabla de correspondencia (acceso restringido, fuera del catálogo).
    max_sujetos:
        Límite opcional de sujetos, útil para pruebas.
    cada:
        Frecuencia (en sujetos) de escritura del avance por consola.
    semilla:
        Semilla de la permutación de identificadores. Por defecto es aleatoria (los
        identificadores no son reproducibles, por privacidad); fíjela solo para
        regenerar exactamente un catálogo previo.
    """
    salida.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    filas_sujeto: list[dict[str, Any]] = []
    ruta_seg = salida / "etiquetas_segmentos.csv.gz"

    with h5py.File(ruta_info, "r") as h, gzip.open(ruta_seg, "wt", newline="") as fseg:
        info = h["Dataset_Info"]
        n = info["Subj_Age"].shape[1]
        if max_sujetos is not None:
            n = min(n, max_sujetos)
        # Identificadores opacos por permutación aleatoria (sin relación con el orden original).
        rng = np.random.default_rng(
            secrets.randbits(64) if semilla is None else semilla
        )
        perm = rng.permutation(n) + 1
        escritor = csv.writer(fseg)
        escritor.writerow(["subject_id", "segment_index", "sbp_mmhg", "dbp_mmhg"])

        for i in range(n):
            nombre = _cadena(h[info["Subj_Name"][0, i]])
            fuente = _cadena(h[info["Source"][0, i]])
            sexo = _cadena(h[info["Subj_Gender"][0, i]])
            sbp = np.asarray(h[info["Subj_SBP"][0, i]], dtype=float).ravel()
            dbp = np.asarray(h[info["Subj_DBP"][0, i]], dtype=float).ravel()
            sid = f"SUBJ-{perm[i]:05d}"
            fila: dict[str, Any] = {
                "subject_id": sid,
                "source": fuente,
                "biological_sex": sexo,
                "n_segments": int(sbp.size),
                "_nombre_original": nombre,
            }
            for campo in CAMPOS_ESCALARES:
                fila[campo] = _escalar(h, info[campo][0, i])
            filas_sujeto.append(fila)
            for k in range(sbp.size):
                escritor.writerow([sid, k, f"{sbp[k]:.2f}", f"{dbp[k]:.2f}"])
            if (i + 1) % cada == 0 or i + 1 == n:
                seg = time.time() - t0
                print(f"[{i + 1}/{n}] {seg:7.1f} s", flush=True)

    columnas = [
        "subject_id",
        "source",
        "biological_sex",
        "Subj_Age",
        "Subj_BMI",
        "Subj_Height",
        "Subj_Weight",
        "n_segments",
    ]
    with open(salida / "sujetos.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas_sujeto)

    # Tabla de correspondencia: acceso restringido (protocolo de custodia, RNF1).
    ruta_corr.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_corr, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject_id", "nombre_original_pulsedb"])
        for fila in filas_sujeto:
            w.writerow([fila["subject_id"], fila["_nombre_original"]])
    ruta_corr.chmod(0o600)
    print(f"Catálogo escrito en {salida} ({len(filas_sujeto)} sujetos).", flush=True)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--info", type=Path, required=True, help="Ruta a PulseDB_Info.mat")
    p.add_argument("--out", type=Path, default=Path("data/processed/pulsedb_catalogo"))
    p.add_argument(
        "--tabla-correspondencia",
        type=Path,
        default=Path("data/metadata/tabla_correspondencia_RESTRINGIDA.csv"),
    )
    p.add_argument("--max-sujetos", type=int, default=None)
    p.add_argument(
        "--semilla",
        type=int,
        default=None,
        help="semilla de la permutación de identificadores (por defecto aleatoria)",
    )
    args = p.parse_args(argv)
    catalogar(
        args.info,
        args.out,
        args.tabla_correspondencia,
        args.max_sujetos,
        semilla=args.semilla,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
