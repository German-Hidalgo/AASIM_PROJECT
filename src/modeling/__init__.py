"""Modelado, validación y optimización de modelos (Fase 3 del sistema AASIM).

Esta etapa construye la ABT versionada, los pipelines de preproceso, la
evidencia de no-fuga, los modelos base y avanzados, la validación agrupada y la
optimización de hiperparámetros. Consume los artefactos de la Fase 2 en
``data/processed/`` y no modifica ninguna ruta de la cadena de inferencia.

Buenas prácticas transversales
------------------------------
* La unidad de agrupación es el **sujeto** (y el **centro** si aplica): nunca se
  reparte un sujeto entre entrenamiento y prueba.
* Todo estadístico de preproceso se ajusta **solo con train**.
* Cada artefacto y corrida se sella con versión y huella SHA-256 (trazabilidad).
"""
