"""Informe de calidad de datos genérico (EDA) para la Fase 2 del sistema AASIM.

Procedimiento **agnóstico al conjunto de datos**: opera sobre cualquier
``pandas.DataFrame`` y no depende del dominio ECG/Presión. Complementa (no
sustituye) a ``pulsedb_dqr_analysis.py``, que es el DQR específico de PulseDB.

Secciones operacionalizadas (guía de calidad de datos)
------------------------------------------------------
1. Identificación de valores faltantes (y priorización de acciones).
2. Detección de cardinalidad irregular.
3. Detección de valores atípicos (IQR de Tukey y z-score).
4. Validez contextual (reglas de plausibilidad fisiológica/experimental).
5. Análisis de correlación (soporte a decisiones).
6. Estructura de clases (balance para clasificación).
7. Plan de calidad de datos (plantilla de problemas/acciones).
8. Recomendaciones para el modelado posterior.

Ejemplo de aplicación
---------------------
El conjunto de referencia usado en la guía es "injury risk"
(``Knee_Flex_deg``, ``EMG_Quad_RMS_mV``, ``EMG_Ham_RMS_mV``,
``GRF_Vert_Norm_BW``, ``Omega_Shank_deg_s``, ``Hip_Flex_deg``, ``Risk_Lesion``).
Ese CSV no está versionado en el repositorio; el módulo trabaja sobre cualquier
DataFrame que se le entregue.

Fronteras
---------
* Calidad de **señal** (SQI/RF4) -> ``src/sqi/quality_assessment.py``.
* DQR específico de PulseDB -> ``src/reports/pulsedb_dqr_analysis.py``.
* Este módulo -> EDA/calidad de **datos tabulares** en general.

Responsable: Rocha (ingeniería TI); lectura clínica y umbrales de plausibilidad:
Buitrago; gobernanza y reglas de faltantes: Hidalgo.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np  # noqa: F401  (se usa al implementar límites IQR/z-score)
import pandas as pd

# Umbrales de decisión para faltantes (guía de calidad de datos).
UMBRAL_ELIMINAR_PCT: float = 60.0
UMBRAL_IMPUTAR_PCT: float = 30.0


# --------------------------------------------------------------------------
# 1. Valores faltantes
# --------------------------------------------------------------------------
def tabla_faltantes(
    df: pd.DataFrame,
    umbral_eliminar: float = UMBRAL_ELIMINAR_PCT,
    umbral_imputar: float = UMBRAL_IMPUTAR_PCT,
) -> pd.DataFrame:
    """Porcentaje de celdas faltantes por columna, con acción priorizada.

    Ordena de mayor a menor y clasifica la acción: ``eliminar`` si supera
    ``umbral_eliminar``, ``imputar`` entre ``umbral_imputar`` y
    ``umbral_eliminar``, ``evaluar`` por debajo.

    Returns:
        DataFrame con ``Porc_Faltantes_%`` y ``Accion`` por columna.
    """
    raise NotImplementedError("Pendiente: porcentaje de faltantes y acción")


# --------------------------------------------------------------------------
# 2. Cardinalidad
# --------------------------------------------------------------------------
def tabla_cardinalidad(df: pd.DataFrame) -> pd.DataFrame:
    """Número de valores únicos por columna (orden ascendente).

    Marca cardinalidad 1 (columna sin información) y valores sospechosos para
    detectar codificaciones erróneas o cardinalidad excesiva.

    Returns:
        DataFrame con ``Cardinalidad`` y banderas auxiliares.
    """
    raise NotImplementedError("Pendiente: cardinalidad por columna")


# --------------------------------------------------------------------------
# 3. Valores atípicos (IQR y z-score)
# --------------------------------------------------------------------------
def outlier_bounds_iqr(series: pd.Series, k: float = 1.5) -> tuple[float, float]:
    """Límites de Tukey ``[Q1 - k*IQR, Q3 + k*IQR]`` de una serie."""
    raise NotImplementedError("Pendiente: límites IQR de Tukey")


def outlier_summary(
    df_num: pd.DataFrame,
    method: str = "iqr",
    k: float = 1.5,
    z: float = 3.0,
) -> pd.DataFrame:
    """Resumen de atípicos por variable según ``method`` (``iqr`` o ``z``).

    Returns:
        DataFrame con ``Variable``, ``Límite_inferior``, ``Límite_superior`` y
        ``Conteo_outliers``.
    """
    raise NotImplementedError("Pendiente: resumen de atípicos IQR/z")


# --------------------------------------------------------------------------
# 4. Validez contextual (plausibilidad)
# --------------------------------------------------------------------------
def banderas_plausibilidad(
    df: pd.DataFrame,
    reglas: Mapping[str, tuple[float, float]],
) -> pd.DataFrame:
    """Banderas ``<columna>_out_of_range`` según reglas de plausibilidad.

    Args:
        df: Datos de entrada.
        reglas: Mapa ``columna -> (mínimo, máximo)`` inclusivos.

    Returns:
        DataFrame booleano con una columna de bandera por regla.
    """
    raise NotImplementedError("Pendiente: banderas de plausibilidad por reglas")


# --------------------------------------------------------------------------
# 5. Correlación
# --------------------------------------------------------------------------
def matriz_correlacion(df_num: pd.DataFrame) -> pd.DataFrame:
    """Matriz de correlación entre variables numéricas."""
    raise NotImplementedError("Pendiente: matriz de correlación")


# --------------------------------------------------------------------------
# 6. Balance de clases
# --------------------------------------------------------------------------
def tabla_balance_clases(series: pd.Series) -> pd.DataFrame:
    """Conteo y porcentaje por clase de una variable categórica."""
    raise NotImplementedError("Pendiente: balance de clases")


# --------------------------------------------------------------------------
# 7. Plan de calidad de datos
# --------------------------------------------------------------------------
def plan_calidad_datos(problemas: Sequence[Mapping[str, str]]) -> pd.DataFrame:
    """Construye la tabla del plan a partir de problemas detectados.

    Columnas: ``Variable``, ``Problema detectado``, ``Evidencia/Regla``,
    ``Acción propuesta``, ``Responsable``, ``Fecha``.
    """
    raise NotImplementedError("Pendiente: plantilla del plan de calidad")


# --------------------------------------------------------------------------
# 8. Recomendaciones
# --------------------------------------------------------------------------
def recomendaciones_modelado(
    tarea: str,
    target: str,
    *,
    asimetria: float | None = None,
    desbalance: float | None = None,
) -> list[str]:
    """Recomendaciones de modelado según ``tarea``.

    ``tarea`` es ``regresion`` o ``clasificacion``.
    """
    raise NotImplementedError("Pendiente: recomendaciones de modelado")


# --------------------------------------------------------------------------
# Visualizaciones (matplotlib, se delegarán en ``_save`` de reports)
# --------------------------------------------------------------------------
def plot_faltantes_y_cardinalidad(df: pd.DataFrame, out_dir: Path) -> list[Path]:
    """Barras horizontales de % de faltantes y de cardinalidad por variable."""
    raise NotImplementedError("Pendiente: gráficos de faltantes y cardinalidad")


def plot_outliers_boxplots(df_num: pd.DataFrame, out_dir: Path) -> list[Path]:
    """Boxplots univariados de las numéricas seleccionadas."""
    raise NotImplementedError("Pendiente: boxplots univariados")


def plot_matriz_correlacion(corr: pd.DataFrame, out_dir: Path) -> list[Path]:
    """Mapa de calor de la matriz de correlación (sin seaborn)."""
    raise NotImplementedError("Pendiente: mapa de calor de correlación")


def plot_balance_clases(series: pd.Series, out_dir: Path) -> list[Path]:
    """Barras de frecuencia por clase."""
    raise NotImplementedError("Pendiente: barras de balance de clases")


# --------------------------------------------------------------------------
# Orquestación y CLI
# --------------------------------------------------------------------------
def informe_calidad_datos(
    df: pd.DataFrame,
    target: str | None = None,
    reglas: Mapping[str, tuple[float, float]] | None = None,
    out_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Ejecuta las secciones 1-6 y devuelve las tablas del informe.

    Args:
        df: Conjunto de datos.
        target: Variable objetivo (p. ej. ``Risk_Lesion``); si es categórica se
            reporta su balance de clases.
        reglas: Reglas de plausibilidad ``columna -> (mín, máx)``.
        out_dir: Si se indica, además genera las figuras.
    """
    raise NotImplementedError("Pendiente: orquestar el informe de calidad")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, required=True, help="CSV del conjunto de datos.")
    p.add_argument("--target", type=str, default=None, help="Variable objetivo.")
    p.add_argument("--out", type=Path, default=None, help="Directorio de figuras.")
    args = p.parse_args(argv)  # noqa: F841  (esqueleto: ver TODO abajo)

    # TODO(Fase 2): leer el CSV, ejecutar informe_calidad_datos y volcar las
    # tablas (Markdown/JSON) y figuras en --out.
    raise NotImplementedError("Pendiente: cablear el CLI del informe de calidad")


if __name__ == "__main__":
    sys.exit(main())
