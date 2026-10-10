"""Partición anti-fuga del corpus PulseDB v2.0 (Fase 2, AASIM).

Aplica sobre el catálogo de sujetos adultos las particiones definidas en
``src/partitioning/split_dataset.py``:

* Patient-Wise 70/15/15 estratificada por fuente, grupo de edad, sexo y estrato de PAS
  mediana del sujeto, con aserción criptográfica de intersección vacía y manifiesto sellado.
* Leave-one-site-out entre las dos fuentes (MIMIC y VitalDB). Con solo dos centros no es
  posible una partición site-wise 70/15/15 (exige tres o más); se documenta como limitación.

Los manifiestos usan los identificadores opacos ``SUBJ-xxxxx`` del catálogo, no los nombres
originales de PulseDB.

Responsable: Rocha (ingeniería TI); revisión de privacidad: Hidalgo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from src.partitioning.split_dataset import (
    SplitConfig,
    SplitManifest,
    assert_disjoint_subjects,
    leave_one_site_out,
    patient_wise_split,
    seal_manifest,
    verify_seal,
)
from src.preprocessing.transformations import sbp_stratum

GRUPOS_EDAD = [17, 39, 64, 200]
ETIQUETAS_EDAD = ["18-39", "40-64", "65+"]


def preparar_sujetos(dir_cat: Path) -> pd.DataFrame:
    """Tabla de sujetos adultos con las columnas de estratificación y ``site_id``."""
    suj = pd.read_csv(dir_cat / "sujetos.csv")
    lab = pd.read_csv(
        dir_cat / "etiquetas_segmentos.csv.gz", usecols=["subject_id", "sbp_mmhg"]
    )
    mediana = lab.groupby("subject_id")["sbp_mmhg"].median().rename("sbp_mediana")
    suj = suj.merge(mediana, on="subject_id")
    suj = suj[suj["Subj_Age"] >= 18.0].copy()
    suj["site_id"] = suj["source"].map({"MIMIC": "SITE-001", "VitalDB": "SITE-002"})
    suj["age_group"] = pd.cut(
        suj["Subj_Age"], GRUPOS_EDAD, labels=ETIQUETAS_EDAD
    ).astype(str)
    suj["sbp_stratum"] = [int(sbp_stratum(v)) for v in suj["sbp_mediana"]]
    return suj


def _resumen(m: SplitManifest, suj: pd.DataFrame) -> dict[str, Any]:
    asign = m.assignment()
    t = suj.assign(particion=suj["subject_id"].map(asign))
    return {
        "sujetos": m.counts(),
        "por_fuente": t.groupby(["particion", "source"])
        .size()
        .unstack()
        .fillna(0)
        .astype(int)
        .to_dict("index"),
        "edad_media": t.groupby("particion")["Subj_Age"].mean().round(1).to_dict(),
        "pas_mediana_media": t.groupby("particion")["sbp_mediana"]
        .mean()
        .round(1)
        .to_dict(),
        "mujeres_pct": (
            t.assign(f=t["biological_sex"] == "F").groupby("particion")["f"].mean()
            * 100
        )
        .round(1)
        .to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    """Genera manifiestos, certificados y resumen."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--catalogo", type=Path, default=Path("data/processed/pulsedb_catalogo")
    )
    p.add_argument("--out", type=Path, default=Path("data/processed/pulsedb_particion"))
    p.add_argument("--semilla", type=int, default=20260920)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    suj = preparar_sujetos(args.catalogo)
    cfg = SplitConfig(
        seed=args.semilla,
        stratify_by=("source", "age_group", "biological_sex", "sbp_stratum"),
    )
    pw = patient_wise_split(suj, cfg)
    cert = assert_disjoint_subjects(pw)
    verify_seal(pw, seal_manifest(pw))
    salida: dict[str, Any] = {
        "patient_wise": _resumen(pw, suj),
        "certificado_patient_wise": json.loads(cert.to_json()),
        "estratos": int(suj.groupby(list(cfg.stratify_by)).ngroups),
        "adultos": len(suj),
    }
    (args.out / "manifiesto_patient_wise.json").write_text(
        json.dumps(
            {
                "seed": pw.seed,
                "ratios": pw.ratios,
                "salt": pw.salt,
                "partitions": pw.partitions,
            },
            indent=1,
        )
    )
    (args.out / "certificado_patient_wise.json").write_text(cert.to_json())

    loso: dict[str, Any] = {}
    for sitio, m in leave_one_site_out(suj, SplitConfig(seed=args.semilla)):
        c = assert_disjoint_subjects(m)
        loso[sitio] = {"sujetos": m.counts(), "sha256": c.manifest_sha256}
        (args.out / f"manifiesto_loso_{sitio}.json").write_text(
            json.dumps(
                {"seed": m.seed, "salt": m.salt, "partitions": m.partitions}, indent=1
            )
        )
    salida["leave_one_site_out"] = loso
    (args.out / "resumen_particion.json").write_text(
        json.dumps(salida, indent=2, ensure_ascii=False, default=float)
    )
    print(json.dumps(salida, indent=2, ensure_ascii=False, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
