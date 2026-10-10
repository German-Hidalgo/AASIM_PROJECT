"""Transformaciones y estandarización de bioseñales y covariables.

Proyecto AASIM - Fase 2.

Responsables
------------
* Implementación: Luis Carlos Rocha (Ingeniería TI).
* Reglas anti-fuga y codificación de covariables demográficas: German Alberto
  Hidalgo (Ética y Pacientes), con revisión de Juan Manuel Buitrago en la
  definición de los estratos hemodinámicos.

Principios de diseño
--------------------
1. **Normalización local de la señal (causal).** La amplitud del ECG se
   normaliza por ventana con la mediana y el rango intercuartílico (IQR),
   ``x' = (x - mediana) / IQR``. La operación no usa información de ninguna
   otra ventana ni de ningún otro paciente, por lo que no introduce fuga entre
   particiones y es robusta a artefactos de gran voltaje (RNF4).
2. **Estadísticos aprendidos solo con entrenamiento.** Cualquier estadístico
   estimado sobre un conjunto de datos (mediana/IQR de características,
   escalado de edad e IMC, pesos de remuestreo) se ajusta exclusivamente con
   sujetos del subconjunto de entrenamiento. Las clases ajustables de este
   módulo verifican la pertenencia de cada fila a ``train`` y lanzan
   ``DataLeakageError`` si detectan sujetos de validación o prueba.
3. **Categorías definidas por el esquema, no por los datos.** El codificador
   One-Hot usa listas de categorías fijas (alineadas con
   ``config/metadata_schema.json``); una categoría desconocida es un error, no
   una columna nueva, para que el tamaño del vector de entrada no dependa del
   contenido del conjunto de prueba.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


class DataLeakageError(RuntimeError):
    """Se detectó (o se habría producido) contaminación entre particiones."""


# --------------------------------------------------------------------------
# Normalización robusta de la señal (por ventana / por latido)
# --------------------------------------------------------------------------
def robust_window_normalize(
    x: FloatArray, min_iqr: float = 1e-9
) -> tuple[FloatArray, bool]:
    """Normaliza un segmento con mediana e IQR: ``(x - mediana) / IQR``.

    Args:
        x: Segmento de señal (1-D) sin valores no finitos.
        min_iqr: IQR mínimo admisible; por debajo se considera señal plana.

    Returns:
        Tupla ``(x_normalizada, es_valida)``. Si el IQR es menor que
        ``min_iqr`` (línea plana, saturación o desconexión) se devuelve un
        vector nulo y ``es_valida = False`` para que el llamador rechace la
        ventana en lugar de amplificar ruido.
    """
    arr = np.asarray(x, dtype=np.float64)
    q1, med, q3 = np.percentile(arr, [25.0, 50.0, 75.0])
    iqr = q3 - q1
    if not np.isfinite(iqr) or iqr < min_iqr:
        return np.zeros_like(arr), False
    return (arr - med) / iqr, True


def robust_beat_normalize(beats: FloatArray, min_iqr: float = 1e-9) -> FloatArray:
    """Normalización mediana/IQR latido a latido.

    Args:
        beats: Matriz ``(n_latidos, n_muestras)``.
        min_iqr: IQR mínimo por latido.

    Returns:
        Matriz normalizada; las filas de IQR degenerado quedan en ``NaN`` para
        que puedan excluirse explícitamente aguas abajo.
    """
    out = np.full(beats.shape, np.nan, dtype=np.float64)
    for i, beat in enumerate(beats):
        normalized, ok = robust_window_normalize(beat, min_iqr)
        if ok:
            out[i] = normalized
    return out


# --------------------------------------------------------------------------
# Escalador robusto ajustado únicamente con entrenamiento
# --------------------------------------------------------------------------
@dataclass
class TrainOnlyRobustScaler:
    """Escalado robusto (mediana/IQR) de características, ajustable solo en train.

    Attributes:
        feature_names: Nombres de las columnas ajustadas.
        median_: Mediana de entrenamiento por característica.
        iqr_: IQR de entrenamiento por característica (mínimo ``1.0`` cuando la
            columna es constante, para evitar divisiones por cero).
        n_train_subjects_: Número de sujetos usados en el ajuste.
        fitted_on_subjects_digest_: Resumen (SHA-256) de los sujetos de ajuste.
    """

    feature_names: list[str] = field(default_factory=list)
    median_: FloatArray | None = None
    iqr_: FloatArray | None = None
    n_train_subjects_: int = 0
    fitted_on_subjects_digest_: str = ""

    def fit(
        self,
        features: pd.DataFrame,
        subject_ids: Sequence[str],
        train_subject_ids: Iterable[str],
    ) -> TrainOnlyRobustScaler:
        """Ajusta mediana e IQR con las filas pertenecientes a entrenamiento.

        Args:
            features: Matriz de características (una fila por ventana).
            subject_ids: Sujeto propietario de cada fila (mismo largo).
            train_subject_ids: Conjunto oficial de sujetos de entrenamiento.

        Raises:
            DataLeakageError: Si alguna fila pertenece a un sujeto ajeno al
                subconjunto de entrenamiento.
            ValueError: Si los tamaños no coinciden.
        """
        import hashlib

        if len(features) != len(subject_ids):
            raise ValueError("features y subject_ids deben tener el mismo largo")
        train = set(train_subject_ids)
        foreign = sorted(set(subject_ids) - train)
        if foreign:
            raise DataLeakageError(
                f"El ajuste incluye {len(foreign)} sujeto(s) fuera de "
                f"entrenamiento (p. ej., {foreign[:3]}). Los estadísticos de "
                "normalización solo pueden calcularse con train."
            )
        values = features.to_numpy(dtype=np.float64)
        q1, med, q3 = np.nanpercentile(values, [25.0, 50.0, 75.0], axis=0)
        iqr = q3 - q1
        iqr = np.where(iqr > 0.0, iqr, 1.0)
        self.feature_names = list(features.columns)
        self.median_ = med
        self.iqr_ = iqr
        self.n_train_subjects_ = len(set(subject_ids))
        digest = hashlib.sha256("|".join(sorted(set(subject_ids))).encode())
        self.fitted_on_subjects_digest_ = digest.hexdigest()
        return self

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        """Aplica el escalado con los estadísticos congelados de entrenamiento."""
        if self.median_ is None or self.iqr_ is None:
            raise RuntimeError("El escalador no ha sido ajustado")
        if list(features.columns) != self.feature_names:
            raise ValueError("Las columnas no coinciden con las del ajuste")
        scaled = (features.to_numpy(dtype=np.float64) - self.median_) / self.iqr_
        return pd.DataFrame(scaled, index=features.index, columns=features.columns)

    def to_json(self) -> str:
        """Serializa los estadísticos para su versionado y auditoría."""
        if self.median_ is None or self.iqr_ is None:
            raise RuntimeError("El escalador no ha sido ajustado")
        payload: dict[str, Any] = {
            "feature_names": self.feature_names,
            "median": self.median_.tolist(),
            "iqr": self.iqr_.tolist(),
            "n_train_subjects": self.n_train_subjects_,
            "fitted_on_subjects_digest": self.fitted_on_subjects_digest_,
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> TrainOnlyRobustScaler:
        """Reconstruye un escalador previamente ajustado."""
        p = json.loads(text)
        return cls(
            feature_names=p["feature_names"],
            median_=np.asarray(p["median"], dtype=np.float64),
            iqr_=np.asarray(p["iqr"], dtype=np.float64),
            n_train_subjects_=int(p["n_train_subjects"]),
            fitted_on_subjects_digest_=p["fitted_on_subjects_digest"],
        )


# --------------------------------------------------------------------------
# Codificación de covariables demográficas y de contexto
# --------------------------------------------------------------------------
#: Categorías cerradas, alineadas con ``config/metadata_schema.json``.
SEX_CATEGORIES: tuple[str, ...] = ("female", "male", "intersex")
POSTURE_CATEGORIES: tuple[str, ...] = (
    "supine",
    "seated",
    "standing",
    "ambulatory",
    "not_available",  # fuentes públicas sin registro de postura (p. ej. PulseDB)
)
MEDICATION_CATEGORIES: tuple[str, ...] = (
    "beta_blocker",
    "ace_inhibitor",
    "arb",
    "calcium_channel_blocker",
    "diuretic",
    "other_cardiovascular",
)
#: Marca de banda decenal -> punto medio (años) para el escalado numérico.
AGE_BRACKET_MIDPOINT: dict[str, float] = {
    "18-29": 24.0,
    "30-39": 34.5,
    "40-49": 44.5,
    "50-59": 54.5,
    "60-69": 64.5,
    "70-79": 74.5,
    "80-89": 84.5,
    "90+": 93.0,
}
#: Categoría de IMC (OMS) -> valor representativo (kg/m^2) para escalado.
BMI_CATEGORY_REPRESENTATIVE: dict[str, float] = {
    "underweight": 17.0,
    "normal": 22.0,
    "overweight": 27.5,
    "obese_class_1": 32.5,
    "obese_class_2": 37.5,
    "obese_class_3": 42.0,
    # Imputación constante (punto medio de la categoría "normal"); el indicador
    # ``bmi__not_available`` permite al modelo distinguir el valor imputado.
    "not_available": 22.0,
}


@dataclass
class CovariateEncoder:
    """Codifica covariables clínicas como factores auxiliares de ajuste.

    * ``biological_sex`` y ``posture``: One-Hot con categorías cerradas.
    * ``active_cardiovascular_medication``: codificación multi-hot (un sujeto
      puede recibir varios fármacos); ``"none"``/lista vacía = todo ceros.
    * ``age_bracket`` y ``bmi_category``: se convierten a un valor numérico
      representativo y se escalan de forma robusta (mediana/IQR) con
      estadísticos de **entrenamiento**.
    """

    scaler_: TrainOnlyRobustScaler = field(default_factory=TrainOnlyRobustScaler)

    _NUMERIC_COLUMNS = ("age_years_mid", "bmi_representative")

    @staticmethod
    def _numeric_frame(meta: pd.DataFrame) -> pd.DataFrame:
        try:
            age = meta["age_bracket"].map(AGE_BRACKET_MIDPOINT)
            bmi = meta["bmi_category"].map(BMI_CATEGORY_REPRESENTATIVE)
        except KeyError as exc:  # pragma: no cover - defensivo
            raise ValueError(f"Falta la columna de metadatos {exc}") from exc
        if age.isna().any() or bmi.isna().any():
            raise ValueError("Banda de edad o categoría de IMC fuera del esquema")
        return pd.DataFrame(
            {
                "age_years_mid": age.astype(float),
                "bmi_representative": bmi.astype(float),
            },
            index=meta.index,
        )

    def fit(
        self, meta: pd.DataFrame, subject_ids: Sequence[str], train_ids: Iterable[str]
    ) -> CovariateEncoder:
        """Ajusta el escalado robusto de edad/IMC solo con entrenamiento."""
        self.scaler_.fit(self._numeric_frame(meta), subject_ids, train_ids)
        return self

    def transform(self, meta: pd.DataFrame) -> pd.DataFrame:
        """Genera la matriz de covariables codificadas (mismo orden de filas)."""
        numeric = self.scaler_.transform(self._numeric_frame(meta))
        cols: dict[str, NDArray[np.float64]] = {}
        for cat in SEX_CATEGORIES:
            cols[f"sex__{cat}"] = (meta["biological_sex"] == cat).to_numpy(float)
        if not set(meta["biological_sex"]) <= set(SEX_CATEGORIES):
            raise ValueError("Valor de biological_sex fuera del esquema")
        for cat in POSTURE_CATEGORIES:
            cols[f"posture__{cat}"] = (meta["posture"] == cat).to_numpy(float)
        if not set(meta["posture"]) <= set(POSTURE_CATEGORIES):
            raise ValueError("Valor de posture fuera del esquema")
        meds = meta["active_cardiovascular_medication"].apply(
            lambda v: set(v) if isinstance(v, (list, tuple, set)) else set()
        )
        for drug in MEDICATION_CATEGORIES:
            cols[f"med__{drug}"] = meds.apply(lambda s, d=drug: d in s).to_numpy(float)
        unknown = (
            set().union(*meds) - set(MEDICATION_CATEGORIES) - {"unknown"}
            if len(meds)
            else set()
        )
        if unknown:
            raise ValueError(f"Medicación fuera del esquema: {sorted(unknown)}")
        cols["med__unknown"] = meds.apply(lambda s: "unknown" in s).to_numpy(float)
        cols["bmi__not_available"] = (meta["bmi_category"] == "not_available").to_numpy(
            float
        )
        encoded = pd.DataFrame(cols, index=meta.index)
        return pd.concat([numeric, encoded], axis=1)


# --------------------------------------------------------------------------
# Estratificación hemodinámica y pesos anti-colapso hacia la media
# --------------------------------------------------------------------------
#: Bordes de los estratos de PAS (mmHg) para balanceo y auditoría.
SBP_STRATUM_EDGES: tuple[float, ...] = (100.0, 120.0, 140.0, 160.0)
SBP_STRATUM_LABELS: tuple[str, ...] = (
    "PAS<100",
    "100-119",
    "120-139",
    "140-159",
    "PAS>=160",
)


def sbp_stratum(sbp: FloatArray) -> NDArray[np.int64]:
    """Asigna cada PAS a un estrato hemodinámico (0..4)."""
    return np.digitize(np.asarray(sbp, dtype=np.float64), SBP_STRATUM_EDGES).astype(
        np.int64
    )


def fit_inverse_frequency_weights(
    train_strata: NDArray[np.int64], max_ratio: float = 10.0
) -> dict[int, float]:
    """Pesos de costo inversamente proporcionales a la frecuencia del estrato.

    Mitiga el colapso hacia la media (Regression-to-the-Mean) causado por el
    predominio normotenso. Se calculan **solo con el conjunto de entrenamiento**
    y se aplican sin modificación a cualquier otra partición.

    Args:
        train_strata: Estratos de las ventanas de entrenamiento.
        max_ratio: Cociente máximo peso_máx/peso_mín; recorta pesos extremos
            de estratos casi vacíos para no amplificar ruido de etiqueta.

    Returns:
        Diccionario ``estrato -> peso`` normalizado a media 1 en train.
    """
    strata, counts = np.unique(train_strata, return_counts=True)
    raw = counts.sum() / (len(strata) * counts.astype(np.float64))
    floor = raw.min()
    clipped = np.minimum(raw, floor * max_ratio)
    clipped = clipped / np.average(clipped, weights=counts)
    return {int(s): float(w) for s, w in zip(strata, clipped, strict=True)}


def apply_weights(
    strata: NDArray[np.int64], weights: dict[int, float], default: float = 1.0
) -> FloatArray:
    """Asigna pesos por estrato; estratos no vistos en train reciben ``default``."""
    return np.asarray([weights.get(int(s), default) for s in strata], dtype=np.float64)
