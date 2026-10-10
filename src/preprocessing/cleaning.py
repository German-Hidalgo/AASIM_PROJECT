"""Limpieza de datos (tablas y etiquetas) para la Fase 2 del sistema AASIM.

Este módulo trata los **datos**: el catálogo de sujetos, las etiquetas de presión
y las covariables. **No** procesa la señal: el filtrado (Butterworth, muesca de
red, cadena causal) y el tratamiento de discontinuidades del ECG viven en
``src/preprocessing/filters.py``.

Frontera conceptual
-------------------
* **Adecuación y procesamiento de señal** -> ``filters.py`` (filtrado causal,
  huecos del ECG). Opera sobre muestras.
* **Limpieza de datos** -> este módulo. Opera sobre registros tabulares:
  1. imputación de valores faltantes,
  2. manejo de atípicos (plausibilidad fisiológica e instrumental),
  3. corrección/censura de etiquetas de referencia,
  4. duplicados e integridad referencial.

Procedencia (pendiente de migración)
------------------------------------
Las funciones de limpieza **de etiquetas** que hoy residen en ``filters.py``
deberán trasladarse aquí para respetar la frontera anterior:

* ``HemodynamicLimits``, ``LabelCensorResult``, ``REASON_*``,
  ``censor_reference_labels`` y ``flag_unstable_reference``.

La imputación de covariables hoy vive acoplada a ``CovariateEncoder`` en
``transformations.py`` (BMI nulo -> punto medio + indicador de no disponible);
la regla de negocio se declara aquí y la codificación se mantiene en ese módulo.

Datos reales observados
------------------------
En el catálogo de PulseDB v2.0, la antropometría (``Subj_BMI``, ``Subj_Height``,
``Subj_Weight``) falta para toda la fuente MIMIC (2423 de 5361 sujetos); la
edad y el sexo están completos. La limpieza debe dejar constancia de la
imputación y de sus indicadores, sin inventar información clínica.

Responsable: Rocha (ingeniería TI); política de faltantes, atípicos y etiquetas:
Buitrago (validación clínica, RF3/S1) e Hidalgo (gobernanza, RNF1).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

#: Rangos de plausibilidad fisiológica/instrumental de las covariables.
EDAD_RANGO: tuple[float, float] = (18.0, 120.0)
BMI_RANGO: tuple[float, float] = (10.0, 80.0)
ALTURA_CM_RANGO: tuple[float, float] = (100.0, 250.0)
PESO_KG_RANGO: tuple[float, float] = (30.0, 300.0)


@dataclass
class CleaningReport:
    """Resumen auditable de la limpieza aplicada a una tabla.

    Attributes:
        n_filas: Filas de entrada.
        n_imputadas: Valores faltantes imputados (por columna en ``imputadas``).
        n_atipicos: Valores fuera de rango marcados (por columna en ``atipicos``).
        n_corregidas: Etiquetas de presión corregidas/censuradas.
        n_duplicados: Registros duplicados detectados.
        imputadas: Conteo de imputaciones por columna.
        atipicos: Conteo de atípicos por columna.
    """

    n_filas: int = 0
    n_imputadas: int = 0
    n_atipicos: int = 0
    n_corregidas: int = 0
    n_duplicados: int = 0
    imputadas: dict[str, int] = field(default_factory=dict)
    atipicos: dict[str, int] = field(default_factory=dict)

    def merge(self, other: CleaningReport) -> CleaningReport:
        """Acumula el informe de otra operación de limpieza."""
        raise NotImplementedError("Pendiente: fusionar contadores de limpieza")


# --------------------------------------------------------------------------
# 1. Imputación de faltantes
# --------------------------------------------------------------------------
def imputar_faltantes(
    datos: pd.DataFrame,
    columnas: tuple[str, ...] = ("Subj_BMI", "Subj_Height", "Subj_Weight"),
) -> tuple[pd.DataFrame, CleaningReport]:
    """Imputa valores faltantes dejando indicador de "no disponible".

    Política (sin imputación sintética que finja dato clínico):

    * Columnas antropométricas: imputación por mediana **solo** si procede y se
      añade ``<columna>__not_available`` para que el modelo distinga el valor
      imputado (coherente con ``CovariateEncoder``).
    * No se imputan etiquetas de presión ni variables clínicas críticas.

    Returns:
        ``(datos_imputados, informe)``.
    """
    raise NotImplementedError("Pendiente: imputación de faltantes + indicadores")


# --------------------------------------------------------------------------
# 2. Manejo de atípicos
# --------------------------------------------------------------------------
def marcar_atipicos(
    datos: pd.DataFrame,
    rangos: dict[str, tuple[float, float]] | None = None,
) -> tuple[pd.DataFrame, CleaningReport]:
    """Marca (no elimina) valores fuera de plausibilidad fisiológica.

    Añade columnas ``<columna>__outlier`` booleanas y cuenta los casos. No borra
    filas: la decisión de exclusión es de la validación clínica.

    Rangos por defecto: ``EDAD_RANGO``, ``BMI_RANGO``, ``ALTURA_CM_RANGO`` y
    ``PESO_KG_RANGO``.

    Returns:
        ``(datos_marcados, informe)``.
    """
    raise NotImplementedError("Pendiente: marcado de atípicos por rangos")


# --------------------------------------------------------------------------
# 3. Corrección/censura de etiquetas de referencia (RF3, S1, R3)
# --------------------------------------------------------------------------
def corregir_etiquetas_presion(
    sbp: np.ndarray,
    dbp: np.ndarray,
    limits: object | None = None,
) -> tuple[np.ndarray, CleaningReport]:
    """Censura etiquetas de referencia fisiológicamente inadmisibles.

    Reglas: PAS en [70, 240] mmHg, PAD en [40, 140] mmHg, PAS > PAD y presión de
    pulso >= 20 mmHg (``filters.HemodynamicLimits``). Reutiliza la lógica ya
    probada de ``filters.censor_reference_labels``; aquí se expone como limpieza
    de datos y no como procesamiento de señal.

    Returns:
        ``(mascara_admisible, informe)``.
    """
    raise NotImplementedError("Pendiente: reubicar/envolver el censurado de etiquetas")


# --------------------------------------------------------------------------
# 4. Duplicados e integridad
# --------------------------------------------------------------------------
def detectar_duplicados(
    datos: pd.DataFrame,
    claves: tuple[str, ...] = ("subject_id",),
) -> tuple[pd.DataFrame, CleaningReport]:
    """Detecta registros duplicados por clave sin eliminarlos en silencio.

    Returns:
        ``(datos_con_marca_duplicado, informe)``.
    """
    raise NotImplementedError("Pendiente: detección de duplicados por clave")


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------
def limpiar_catalogo_sujetos(
    sujetos: pd.DataFrame,
) -> tuple[pd.DataFrame, CleaningReport]:
    """Orquesta la limpieza del catálogo de sujetos.

    Aplica, en orden: duplicados, imputación de faltantes y marcado de atípicos,
    devolviendo un único informe auditable.
    """
    raise NotImplementedError("Pendiente: orquestar la limpieza del catálogo")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--catalogo", type=Path, default=Path("data/processed/pulsedb_catalogo")
    )
    p.add_argument("--out", type=Path, default=Path("data/processed/pulsedb_limpio"))
    args = p.parse_args(argv)  # noqa: F841  (esqueleto: ver TODO abajo)

    # TODO(Fase 2): leer sujetos.csv, limpiar_catalogo_sujetos y escribir el
    # resultado más el informe de limpieza (JSON) en --out.
    raise NotImplementedError("Pendiente: cablear el CLI de limpieza")


if __name__ == "__main__":
    sys.exit(main())
