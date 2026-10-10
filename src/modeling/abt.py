"""ABT (Analytical Base Table) versionada para la Fase 3 del sistema AASIM.

Une la muestra de características por ventana de la Fase 2
(``data/processed/pulsedb_muestra/ventanas*.csv``) con las etiquetas de presión y
la asignación de partición patient-wise (``data/processed/pulsedb_particion``),
y produce un dataset modelable con **versión y huella SHA-256**.

Reglas
------
* La unidad de modelado es la ventana; el grupo de agrupación es el sujeto
  (``subject_id``), también para la validación cruzada.
* La columna ``split`` (train/val/test) proviene del manifiesto certificado.
* Ninguna característica se deriva con información de val/test (anti-fuga).

Responsable: Rocha (ingeniería TI).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

#: Versión semántica por defecto de la ABT.
ABT_VERSION_DEFAULT = "1.0.0"

#: Columnas de contexto que se conservan además de las características ``feat_*``.
COLUMNAS_CONTEXTO: tuple[str, ...] = (
    "subject_id",
    "source",
    "biological_sex",
    "age",
    "win_index",
    "sbp_mmhg",
    "dbp_mmhg",
    "label_reason_code",
    "quality_flag",
)


def _sha256(path: Path) -> str:
    """Huella SHA-256 de un archivo, leída por bloques (apto para archivos grandes)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _leer_csv_tolerante(path: Path) -> pd.DataFrame:
    """Lee un CSV recortando filas con más campos que el encabezado.

    Las ventanas de la muestra pueden tener filas con campos extra vacíos
    (escritas por una versión anterior del pipeline). Se conserva el prefijo
    válido de cada fila y se restaura la inferencia de tipos al volver a
    analizar el contenido.
    """
    lineas = path.read_text(encoding="utf-8").splitlines()
    n = len(lineas[0].split(","))
    limpias: list[list[str]] = [lineas[0].split(",")]
    malas = 0
    for ln in lineas[1:]:
        campos = ln.split(",")
        if len(campos) != n:
            malas += 1
            campos = campos[:n] + [""] * (n - len(campos))
        limpias.append(campos)
    if malas:
        print(
            f"[ABT] {path.name}: {malas} fila(s) con campos extra, "
            f"recortadas a {n} columnas",
            flush=True,
        )
    buf = io.StringIO()
    csv.writer(buf).writerows(limpias)
    buf.seek(0)
    return pd.read_csv(buf)


def _cargar_ventanas(muestra: Path) -> pd.DataFrame:
    """Carga ``ventanas*.csv`` de un directorio (o un archivo CSV único).

    Si ``muestra`` es un directorio, concatena todas las ``ventanas*.csv`` que
    contiene (incluidas las partes ``ventanas_p0..pn``) y elimina duplicados de
    ``(subject_id, win_index)``.
    """
    if muestra.is_dir():
        archivos = sorted(muestra.glob("ventanas*.csv"))
        if not archivos:
            raise FileNotFoundError(f"No hay ventanas*.csv en {muestra}")
        df = pd.concat([_leer_csv_tolerante(a) for a in archivos], ignore_index=True)
    else:
        df = _leer_csv_tolerante(muestra)
    return df.drop_duplicates(subset=["subject_id", "win_index"]).sort_values(
        ["subject_id", "win_index"]
    )


def _cargar_particion(particion_dir: Path) -> dict[str, list[str]]:
    """Lee el mapa ``split -> [subject_id...]`` del manifiesto patient-wise."""
    manifiesto = particion_dir / "manifiesto_patient_wise.json"
    with open(manifiesto, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return datos["partitions"]


@dataclass(frozen=True)
class AbtVersion:
    """Metadatos de una versión de la ABT.

    Attributes:
        version: Versión SemVer de la ABT.
        sha256: Huella SHA-256 del archivo de ABT.
        n_filas: Número de filas (ventanas).
        n_columnas: Número de columnas.
        target: Variable objetivo.
        grupos: Columnas de agrupación (p. ej. ``subject_id``).
    """

    version: str
    sha256: str
    n_filas: int
    n_columnas: int
    target: str
    grupos: tuple[str, ...]


def construir_abt(
    ventanas_csv: Path,
    particion_dir: Path,
    out_dir: Path,
    target: str = "sbp_mmhg",
    grupos: tuple[str, ...] = ("subject_id",),
    version: str = ABT_VERSION_DEFAULT,
) -> AbtVersion:
    """Construye la ABT, la escribe en ``out_dir`` y devuelve su versión.

    Une características y etiquetas, añade ``split`` desde el manifiesto
    patient-wise y sella el resultado con SHA-256 en un manifiesto de versión.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    df = _cargar_ventanas(ventanas_csv)
    particiones = _cargar_particion(particion_dir)

    # 1. Asignación de partición desde el manifiesto (fuente certificada).
    sujeto_a_split = {
        s: split for split, sujetos in particiones.items() for s in sujetos
    }
    df["split"] = df["subject_id"].map(sujeto_a_split)

    # 2. Solo ventanas admisibles (quality_flag == 0) y con objetivo válido.
    antes = len(df)
    df = df[df["quality_flag"] == 0]
    df = df[df[target].notna()]
    if len(df) < antes:
        print(
            f"[ABT] descartadas {antes - len(df)} ventanas "
            "(rechazadas por calidad o sin objetivo)",
            flush=True,
        )

    # 3. Selección de columnas: contexto + features en orden determinista.
    feature_cols = sorted(c for c in df.columns if c.startswith("feat_"))
    contexto = [c for c in COLUMNAS_CONTEXTO if c in df.columns]
    columnas = (
        ["subject_id", "split"]
        + [c for c in contexto if c not in ("subject_id", "split")]
        + feature_cols
    )
    df = df[columnas].copy()

    # 4. Escritura + sellado.
    archivo = out_dir / f"abt_v{version}.csv.gz"
    df.to_csv(archivo, index=False, compression="gzip")
    huella = _sha256(archivo)
    conteos = df["split"].value_counts().sort_index().to_dict()

    manifiesto_abt = {
        "version": version,
        "archivo": archivo.name,
        "sha256": huella,
        "n_filas": len(df),
        "n_columnas": df.shape[1],
        "target": target,
        "grupos": list(grupos),
        "columnas_features": feature_cols,
        "conteos_por_split": conteos,
        "fecha": datetime.now(UTC).isoformat(),
        "procedencia": {
            "ventanas": {
                str(a): _sha256(a)
                for a in sorted(ventanas_csv.iterdir())
                if a.is_file() and a.suffix == ".csv"
            }
            if ventanas_csv.is_dir()
            else {str(ventanas_csv): _sha256(ventanas_csv)},
            "manifiesto_patient_wise": _sha256(
                particion_dir / "manifiesto_patient_wise.json"
            ),
            "certificado_patient_wise": _sha256(
                particion_dir / "certificado_patient_wise.json"
            ),
        },
    }
    (out_dir / "abt_manifest.json").write_text(
        json.dumps(manifiesto_abt, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return AbtVersion(
        version=version,
        sha256=huella,
        n_filas=len(df),
        n_columnas=df.shape[1],
        target=target,
        grupos=grupos,
    )


def cargar_abt(abt_dir: Path) -> pd.DataFrame:
    """Carga la ABT y valida su huella frente al manifiesto de versión."""
    manifiesto_path = abt_dir / "abt_manifest.json"
    if not manifiesto_path.exists():
        raise FileNotFoundError(f"Manifiesto de ABT no encontrado en {abt_dir}")
    con_manifest = json.loads(manifiesto_path.read_text(encoding="utf-8"))
    archivo = abt_dir / con_manifest["archivo"]
    if not archivo.exists():
        raise FileNotFoundError(f"Archivo de ABT no encontrado: {archivo}")
    huella_real = _sha256(archivo)
    if huella_real != con_manifest["sha256"]:
        raise ValueError(
            f"Huella no coincide: {archivo} está alterado o truncado "
            f"(esperado {con_manifest['sha256'][:12]}…, real {huella_real[:12]}…)"
        )
    return pd.read_csv(archivo)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--ventanas",
        type=Path,
        default=Path("data/processed/pulsedb_muestra"),
        help="CSV de ventanas o directorio con ventanas*.csv",
    )
    p.add_argument(
        "--particion",
        type=Path,
        default=Path("data/processed/pulsedb_particion"),
    )
    p.add_argument("--out", type=Path, default=Path("data/processed/pulsedb_abt"))
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument(
        "--grupos",
        type=str,
        default="subject_id",
        help="Columnas de agrupación separadas por coma",
    )
    p.add_argument("--version", type=str, default=ABT_VERSION_DEFAULT)
    args = p.parse_args(argv)
    grupos = tuple(g.strip() for g in args.grupos.split(",") if g.strip())
    version = construir_abt(
        args.ventanas,
        args.particion,
        args.out,
        target=args.target,
        grupos=grupos,
        version=args.version,
    )
    print(json.dumps(asdict(version), indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
