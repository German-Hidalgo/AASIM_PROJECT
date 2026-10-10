"""Particionamiento jerárquico anti-fuga (Patient-Wise y Site-Wise).

Proyecto AASIM - Fase 2.

Responsables
------------
* Diseño de la arquitectura de partición y sellado: Luis Carlos Rocha
  (Ingeniería TI).
* Requisitos de aislamiento de sujetos y de estratificación demográfica
  (R2, S4): German Alberto Hidalgo (Ética y Pacientes).

Fundamento
----------
La morfología del ECG es casi biométrica (eje de despolarización, masa
miocárdica, posición de los electrodos). Si ventanas o latidos de un mismo
paciente se reparten entre entrenamiento y prueba, el modelo aprende la
identidad electrofisiológica del sujeto y no la relación hemodinámica
generalizable (Identity Leakage). Por ello la unidad de partición es siempre
el **paciente** (y, en datos multicéntricos, el **centro**), nunca el latido,
la época o la ventana.

Garantías que ofrece este módulo
--------------------------------
1. Asignación determinista (independiente del orden de las filas) basada en el
   hash SHA-256 de ``semilla:sujeto``.
2. Partición 70 % / 15 % / 15 % con estratificación opcional; el error de
   redondeo se compensa entre estratos para que las proporciones globales sean
   fieles.
3. ``assert_disjoint_subjects``: aserción criptográfica de intersección vacía
   entre entrenamiento, validación y prueba (sobre identificadores y sobre sus
   huellas SHA-256 con sal), con sellado del manifiesto (``seal_manifest``).
4. ``fit_transform_partitions``: todo estadístico de normalización (mediana/IQR)
   se ajusta exclusivamente con las filas de entrenamiento.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from src.preprocessing.transformations import DataLeakageError, TrainOnlyRobustScaler

PARTITIONS: tuple[str, str, str] = ("train", "val", "test")
DEFAULT_RATIOS: tuple[float, float, float] = (0.70, 0.15, 0.15)


# --------------------------------------------------------------------------
# Configuración y estructuras
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SplitConfig:
    """Parámetros de la partición.

    Attributes:
        ratios: Proporciones ``(train, val, test)``; deben sumar 1.
        seed: Semilla de la asignación determinista (se guarda en el manifiesto).
        stratify_by: Columnas de la tabla de sujetos usadas para estratificar
            (p. ej., ``("sbp_stratum", "age_bracket", "biological_sex")``).
    """

    ratios: tuple[float, float, float] = DEFAULT_RATIOS
    seed: int = 20260919
    stratify_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.ratios) != 3 or any(r <= 0 for r in self.ratios):
            raise ValueError("ratios debe tener tres valores positivos")
        if abs(sum(self.ratios) - 1.0) > 1e-9:
            raise ValueError("ratios debe sumar 1")


@dataclass
class SplitManifest:
    """Manifiesto de una partición: quién pertenece a qué subconjunto."""

    scheme: str
    seed: int
    ratios: tuple[float, float, float]
    partitions: dict[str, list[str]]
    subject_site: dict[str, str] = field(default_factory=dict)
    salt: str = ""

    def subjects(self, name: str) -> set[str]:
        """Conjunto de sujetos de una partición."""
        return set(self.partitions[name])

    def assignment(self) -> dict[str, str]:
        """Mapa ``sujeto -> partición``."""
        return {s: p for p, ids in self.partitions.items() for s in ids}

    def counts(self) -> dict[str, int]:
        """Número de sujetos por partición."""
        return {p: len(ids) for p, ids in self.partitions.items()}

    def sites(self, name: str) -> set[str]:
        """Centros presentes en una partición (si hay información de centro)."""
        return {
            self.subject_site[s]
            for s in self.partitions[name]
            if s in self.subject_site
        }


@dataclass(frozen=True)
class SplitCertificate:
    """Certificado de aislamiento emitido por ``assert_disjoint_subjects``."""

    scheme: str
    counts: dict[str, int]
    pairwise_subject_intersections: dict[str, int]
    pairwise_hash_intersections: dict[str, int]
    manifest_sha256: str

    def to_json(self) -> str:
        """Serializa el certificado (para el expediente de la Fase 2)."""
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


# --------------------------------------------------------------------------
# Utilidades criptográficas
# --------------------------------------------------------------------------
def _rank_key(subject_id: str, seed: int) -> str:
    """Clave de ordenamiento pseudoaleatoria y reproducible de un sujeto."""
    return hashlib.sha256(f"{seed}:{subject_id}".encode()).hexdigest()


def hash_subject(subject_id: str, salt: str) -> str:
    """Huella SHA-256 con sal de un identificador de sujeto."""
    return hashlib.sha256(f"{salt}|{subject_id}".encode()).hexdigest()


def _canonical_payload(m: SplitManifest) -> str:
    """Representación canónica (orden estable) del manifiesto para el sellado."""
    body = {
        "scheme": m.scheme,
        "seed": m.seed,
        "ratios": list(m.ratios),
        "partitions": {p: sorted(ids) for p, ids in sorted(m.partitions.items())},
        "subject_site": dict(sorted(m.subject_site.items())),
        "salt": m.salt,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def seal_manifest(manifest: SplitManifest) -> str:
    """Devuelve el SHA-256 del manifiesto canónico (sello de inmutabilidad)."""
    return hashlib.sha256(_canonical_payload(manifest).encode()).hexdigest()


def verify_seal(manifest: SplitManifest, digest: str) -> None:
    """Comprueba que el manifiesto no fue alterado desde su sellado.

    Raises:
        DataLeakageError: Si el resumen no coincide.
    """
    if seal_manifest(manifest) != digest:
        raise DataLeakageError(
            "El manifiesto de partición fue modificado tras el sellado."
        )


# --------------------------------------------------------------------------
# Asignación por estratos con compensación de redondeo
# --------------------------------------------------------------------------
def _allocate(
    n: int, targets_after: NDArray[np.float64], assigned: NDArray[np.int64]
) -> NDArray[np.int64]:
    """Reparte ``n`` sujetos entre 3 particiones minimizando la desviación global."""
    desired = targets_after - assigned
    counts = np.floor(np.maximum(desired, 0.0)).astype(np.int64)
    while counts.sum() < n:
        counts[int(np.argmax(desired - counts))] += 1
    while counts.sum() > n:
        cand = np.where(counts > 0, counts - desired, -np.inf)
        counts[int(np.argmax(cand))] -= 1
    return counts


def _require_columns(subjects: pd.DataFrame, cols: Iterable[str]) -> None:
    missing = [c for c in cols if c not in subjects.columns]
    if missing:
        raise ValueError(f"Faltan columnas en la tabla de sujetos: {missing}")
    if subjects["subject_id"].duplicated().any():
        raise ValueError("subject_id debe ser único en la tabla de sujetos")


def patient_wise_split(
    subjects: pd.DataFrame, cfg: SplitConfig | None = None
) -> SplitManifest:
    """Partición Patient-Wise 70/15/15 con estratificación opcional.

    Args:
        subjects: Tabla con una fila por sujeto: ``subject_id`` (obligatoria),
            ``site_id`` (opcional) y las columnas de estratificación.
        cfg: Configuración.

    Returns:
        ``SplitManifest`` con esquema ``patient_wise``.

    Raises:
        ValueError: Si hay menos de 3 sujetos o falta alguna columna.
    """
    c = cfg or SplitConfig()
    _require_columns(subjects, ("subject_id", *c.stratify_by))
    if len(subjects) < 3:
        raise ValueError("Se requieren al menos 3 sujetos para tres particiones")
    ratios = np.asarray(c.ratios, dtype=np.float64)
    parts: dict[str, list[str]] = {p: [] for p in PARTITIONS}

    if c.stratify_by:
        groups = list(subjects.groupby(list(c.stratify_by), sort=True, dropna=False))
    else:
        groups = [((), subjects)]
    assigned = np.zeros(3, dtype=np.int64)
    cum_n = 0
    for _, grp in groups:
        ids = sorted(grp["subject_id"].astype(str), key=lambda s: _rank_key(s, c.seed))
        cum_n += len(ids)
        counts = _allocate(len(ids), ratios * cum_n, assigned)
        start = 0
        for p, k in zip(PARTITIONS, counts, strict=True):
            parts[p].extend(ids[start : start + int(k)])
            start += int(k)
        assigned += counts

    site_map = _site_map(subjects)
    manifest = SplitManifest(
        "patient_wise", c.seed, c.ratios, parts, site_map, _salt(c.seed)
    )
    if any(len(v) == 0 for v in parts.values()):
        raise ValueError("Alguna partición quedó vacía; aumente el número de sujetos")
    return manifest


def _site_map(subjects: pd.DataFrame) -> dict[str, str]:
    if "site_id" not in subjects.columns:
        return {}
    return dict(
        zip(
            subjects["subject_id"].astype(str),
            subjects["site_id"].astype(str),
            strict=True,
        )
    )


def _salt(seed: int) -> str:
    return hashlib.sha256(f"aasim-phase2-salt:{seed}".encode()).hexdigest()[:32]


def site_wise_split(
    subjects: pd.DataFrame, cfg: SplitConfig | None = None
) -> SplitManifest:
    """Partición Site-Wise: cada centro completo pertenece a un único subconjunto.

    Los centros se ordenan por tamaño decreciente (desempate por hash) y se
    asignan de forma voraz a la partición con mayor déficit respecto de su
    objetivo de sujetos. Permite estimar la generalización a centros no vistos.

    Raises:
        ValueError: Si hay menos de 3 centros.
    """
    c = cfg or SplitConfig()
    _require_columns(subjects, ("subject_id", "site_id"))
    sites = subjects.groupby(subjects["site_id"].astype(str))["subject_id"].apply(
        lambda s: sorted(s.astype(str))
    )
    if len(sites) < 3:
        raise ValueError("La partición site-wise requiere al menos 3 centros")
    order = sorted(sites.index, key=lambda s: (-len(sites[s]), _rank_key(s, c.seed)))
    total = len(subjects)
    target = np.asarray(c.ratios) * total
    load = np.zeros(3)
    parts: dict[str, list[str]] = {p: [] for p in PARTITIONS}
    # Garantiza un centro por partición antes del reparto voraz por déficit.
    for i, site in enumerate(order):
        if i < 3:
            k = int(np.argsort(-target)[i])
        else:
            k = int(np.argmax(target - load))
        parts[PARTITIONS[k]].extend(sites[site])
        load[k] += len(sites[site])
    return SplitManifest(
        "site_wise", c.seed, c.ratios, parts, _site_map(subjects), _salt(c.seed)
    )


def leave_one_site_out(
    subjects: pd.DataFrame, cfg: SplitConfig | None = None
) -> Iterator[tuple[str, SplitManifest]]:
    """Genera un manifiesto por centro: ese centro completo es la prueba.

    Los demás centros se reparten patient-wise entre entrenamiento y validación
    en proporción 70:15 (re-normalizada).
    """
    c = cfg or SplitConfig()
    _require_columns(subjects, ("subject_id", "site_id"))
    for site in sorted(subjects["site_id"].astype(str).unique()):
        held = subjects[subjects["site_id"].astype(str) == site]
        rest = subjects[subjects["site_id"].astype(str) != site]
        if len(rest) < 2:
            raise ValueError("No quedan sujetos para entrenamiento/validación")
        r_tr = c.ratios[0] / (c.ratios[0] + c.ratios[1])
        ids = sorted(rest["subject_id"].astype(str), key=lambda s: _rank_key(s, c.seed))
        n_val = max(1, round((1 - r_tr) * len(ids)))
        parts = {
            "train": ids[n_val:],
            "val": ids[:n_val],
            "test": sorted(held["subject_id"].astype(str)),
        }
        yield (
            site,
            SplitManifest(
                f"leave_one_site_out[{site}]",
                c.seed,
                c.ratios,
                parts,
                _site_map(subjects),
                _salt(c.seed),
            ),
        )


@dataclass
class HierarchicalSplit:
    """Resultado de la partición jerárquica obligatoria de la Fase 2."""

    patient_wise: SplitManifest
    site_wise: SplitManifest | None
    multicenter: bool
    notes: list[str] = field(default_factory=list)


def hierarchical_split(
    subjects: pd.DataFrame, cfg: SplitConfig | None = None
) -> HierarchicalSplit:
    """Partición jerárquica: primero por paciente y, si es multicéntrico, por centro.

    * Siempre genera la partición Patient-Wise 70/15/15 (vinculante para la
      Fase 3).
    * Si existe ``site_id`` con >= 3 centros, genera además la partición
      Site-Wise (validación de generalización a centros no vistos).
    * Ambos manifiestos se verifican con ``assert_disjoint_subjects``.
    """
    c = cfg or SplitConfig()
    pw = patient_wise_split(subjects, c)
    assert_disjoint_subjects(pw)
    notes: list[str] = []
    sw: SplitManifest | None = None
    multicenter = "site_id" in subjects.columns and subjects["site_id"].nunique() >= 3
    if multicenter:
        sw = site_wise_split(subjects, c)
        assert_disjoint_subjects(sw)
        assert_disjoint_sites(sw)
    else:
        notes.append(
            "Datos monocéntricos (< 3 centros): se omite la partición site-wise."
        )
    return HierarchicalSplit(pw, sw, multicenter, notes)


# --------------------------------------------------------------------------
# Aserciones de aislamiento
# --------------------------------------------------------------------------
def assert_disjoint_subjects(manifest: SplitManifest) -> SplitCertificate:
    """Aserción criptográfica: intersección de sujetos entre particiones = vacío.

    Comprueba, para cada par de particiones, que:

    * la intersección de identificadores es el conjunto vacío;
    * la intersección de las huellas SHA-256 (con sal) es el conjunto vacío;
    * ningún sujeto figura dos veces dentro de una misma partición;
    * las tres particiones son no vacías.

    Returns:
        ``SplitCertificate`` (con el sello SHA-256 del manifiesto).

    Raises:
        DataLeakageError: Ante cualquier violación.
    """
    for name in PARTITIONS:
        ids = manifest.partitions.get(name, [])
        if not ids:
            raise DataLeakageError(f"La partición '{name}' está vacía.")
        if len(ids) != len(set(ids)):
            raise DataLeakageError(f"Sujetos duplicados dentro de '{name}'.")
    hashed = {
        p: {hash_subject(s, manifest.salt) for s in manifest.partitions[p]}
        for p in PARTITIONS
    }
    inter_ids: dict[str, int] = {}
    inter_hash: dict[str, int] = {}
    for a, b in combinations(PARTITIONS, 2):
        n_ids = len(manifest.subjects(a) & manifest.subjects(b))
        n_hash = len(hashed[a] & hashed[b])
        inter_ids[f"{a}&{b}"] = n_ids
        inter_hash[f"{a}&{b}"] = n_hash
        if n_ids or n_hash:
            raise DataLeakageError(
                f"Fuga de identidad: {n_ids} sujeto(s) compartido(s) entre {a} y {b}."
            )
    return SplitCertificate(
        scheme=manifest.scheme,
        counts=manifest.counts(),
        pairwise_subject_intersections=inter_ids,
        pairwise_hash_intersections=inter_hash,
        manifest_sha256=seal_manifest(manifest),
    )


def assert_disjoint_sites(manifest: SplitManifest) -> None:
    """Comprueba que ningún centro aparece en más de una partición (site-wise).

    Raises:
        DataLeakageError: Si un centro está en dos particiones o falta la
            información de centro.
    """
    if not manifest.subject_site:
        raise DataLeakageError("El manifiesto no contiene información de centro.")
    for a, b in combinations(PARTITIONS, 2):
        shared = manifest.sites(a) & manifest.sites(b)
        if shared:
            raise DataLeakageError(
                f"Centros compartidos entre {a} y {b}: {sorted(shared)}"
            )


# --------------------------------------------------------------------------
# Ventanas y validación cruzada agrupada
# --------------------------------------------------------------------------
def make_window_grid(
    n_samples: int, fs: float, window_s: float, hop_s: float
) -> NDArray[np.int64]:
    """Rejilla de ventanas ``(inicio, fin)`` dentro de **una** grabación.

    Las ventanas pueden solaparse (``hop_s < window_s``); esto es inocuo solo
    porque toda la grabación, y por tanto todas sus ventanas, pertenece a un
    único sujeto y a una única partición. Nunca debe construirse una rejilla
    que atraviese fronteras de sujetos o de particiones.
    """
    win, hop = round(window_s * fs), round(hop_s * fs)
    if win <= 0 or hop <= 0:
        raise ValueError("window_s y hop_s deben ser positivos")
    starts = np.arange(0, n_samples - win + 1, hop, dtype=np.int64)
    return np.column_stack([starts, starts + win])


def assign_windows(windows: pd.DataFrame, manifest: SplitManifest) -> pd.DataFrame:
    """Añade la columna ``partition`` a una tabla de ventanas por sujeto.

    Raises:
        DataLeakageError: Si hay sujetos ausentes del manifiesto o un sujeto
            terminara en más de una partición.
    """
    if "subject_id" not in windows.columns:
        raise ValueError("La tabla de ventanas requiere 'subject_id'")
    mapping = manifest.assignment()
    unknown = sorted(set(windows["subject_id"].astype(str)) - set(mapping))
    if unknown:
        raise DataLeakageError(
            f"Sujetos sin asignación en el manifiesto: {unknown[:5]}"
        )
    out = windows.copy()
    out["partition"] = out["subject_id"].astype(str).map(mapping)
    assert_no_cross_partition_subjects(out)
    return out


def assert_no_cross_partition_subjects(windows_with_partition: pd.DataFrame) -> None:
    """Verifica que cada sujeto de la tabla pertenezca a una sola partición."""
    n_parts = windows_with_partition.groupby("subject_id")["partition"].nunique()
    bad = n_parts[n_parts > 1]
    if len(bad):
        raise DataLeakageError(f"Sujetos en varias particiones: {list(bad.index[:5])}")


def subject_group_kfold(
    train_subjects: Sequence[str], k: int, seed: int
) -> list[tuple[set[str], set[str]]]:
    """Pliegues de validación cruzada agrupados por sujeto dentro de train.

    Sirve para el ajuste de hiperparámetros sin romper el aislamiento entre
    sujetos (las ventanas de un mismo paciente nunca se dividen entre pliegues).

    Returns:
        Lista de tuplas ``(sujetos_entrenamiento_pliegue, sujetos_validación)``.
    """
    if k < 2 or k > len(train_subjects):
        raise ValueError("k debe estar entre 2 y el número de sujetos")
    ordered = sorted(train_subjects, key=lambda s: _rank_key(s, seed))
    folds = [set(ordered[i::k]) for i in range(k)]
    return [(set(ordered) - f, f) for f in folds]


# --------------------------------------------------------------------------
# Ajuste de transformaciones únicamente con entrenamiento
# --------------------------------------------------------------------------
def fit_transform_partitions(
    features: pd.DataFrame,
    manifest: SplitManifest,
    feature_cols: Sequence[str],
) -> tuple[dict[str, pd.DataFrame], TrainOnlyRobustScaler]:
    """Normaliza (mediana/IQR) ajustando solo con entrenamiento.

    Args:
        features: Tabla con ``subject_id`` y las columnas de características.
        manifest: Manifiesto ya verificado (se re-verifica aquí).
        feature_cols: Columnas a escalar.

    Returns:
        ``(particiones_transformadas, escalador)`` donde el escalador se ajustó
        con las filas de ``train`` y se aplicó sin modificación a ``val`` y
        ``test``.
    """
    assert_disjoint_subjects(manifest)
    tab = assign_windows(features, manifest)
    train_rows = tab[tab["partition"] == "train"]
    scaler = TrainOnlyRobustScaler().fit(
        train_rows[list(feature_cols)],
        train_rows["subject_id"].astype(str).tolist(),
        manifest.subjects("train"),
    )
    out: dict[str, pd.DataFrame] = {}
    for name in PARTITIONS:
        rows = tab[tab["partition"] == name]
        scaled = scaler.transform(rows[list(feature_cols)])
        out[name] = pd.concat([rows[["subject_id"]], scaled], axis=1)
    assert_scaler_train_only(scaler, tab, manifest)
    return out, scaler


def assert_scaler_train_only(
    scaler: TrainOnlyRobustScaler,
    table_with_partition: pd.DataFrame,
    manifest: SplitManifest,
) -> None:
    """Verifica la procedencia del escalador: solo sujetos de entrenamiento.

    Recalcula la huella de los sujetos de ``train`` presentes en la tabla y la
    compara con la registrada en el escalador durante el ajuste.

    Raises:
        DataLeakageError: Si la huella no coincide.
    """
    train_ids = sorted(
        set(
            table_with_partition.loc[
                table_with_partition["partition"] == "train", "subject_id"
            ].astype(str)
        )
        & manifest.subjects("train")
    )
    digest = hashlib.sha256("|".join(train_ids).encode()).hexdigest()
    if digest != scaler.fitted_on_subjects_digest_:
        raise DataLeakageError(
            "La huella del escalador no coincide con los sujetos de entrenamiento."
        )
