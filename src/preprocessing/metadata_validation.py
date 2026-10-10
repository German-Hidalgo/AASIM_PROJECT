"""Validación de metadatos de adquisición contra ``config/metadata_schema.json``.

Proyecto AASIM - Fase 2.

Responsables
------------
* Implementación y versionado de datos: Luis Carlos Rocha (Ingeniería TI).
* Reglas de gobernanza y coherencia de calidad: German Alberto Hidalgo (Ética
  y Pacientes).

El esquema JSON valida tipos, rangos y enumeraciones. Las reglas que
involucran varios campos a la vez (integridad referencial interna) no se
expresan de forma natural en JSON Schema y se comprueban aquí:

* ``acquisition.primary_lead`` debe pertenecer a ``acquisition.leads_utilized``.
* ``quality_control.n_windows_rejected <= n_windows_total`` y la tasa de
  rechazo debe coincidir con el cociente de ambos conteos (tolerancia 0.1 pp).
* Un registro con ``reference_validation_standard = none_documented`` no puede
  certificarse en el DQR (supuesto S1): se emite una advertencia bloqueante.
* Un registro con ``custody_key_status = pseudonymised_key_retained`` se
  reporta como seudonimizado (no como anonimizado irreversiblemente).

La dependencia ``jsonschema`` es necesaria solo en este módulo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "metadata_schema.json"


@dataclass
class MetadataValidation:
    """Resultado de validar un registro de metadatos."""

    schema_errors: list[str] = field(default_factory=list)
    semantic_errors: list[str] = field(default_factory=list)
    blocking_warnings: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """``True`` si no hay errores de esquema ni semánticos."""
        return not (self.schema_errors or self.semantic_errors)

    @property
    def is_certifiable(self) -> bool:
        """``True`` si además no existen advertencias bloqueantes para el DQR."""
        return self.is_valid and not self.blocking_warnings


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Carga el esquema JSON de metadatos."""
    with path.open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


def validate_metadata(
    record: dict[str, Any], schema: dict[str, Any] | None = None
) -> MetadataValidation:
    """Valida un registro contra el esquema y las reglas de integridad cruzada.

    Args:
        record: Metadatos de una sesión de monitorización.
        schema: Esquema ya cargado; por defecto se lee ``SCHEMA_PATH``.

    Returns:
        ``MetadataValidation`` con los errores y advertencias detectados.
    """
    from jsonschema import Draft202012Validator

    sch = schema or load_schema()
    Draft202012Validator.check_schema(sch)
    result = MetadataValidation()
    validator = Draft202012Validator(sch)
    for err in sorted(validator.iter_errors(record), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<raíz>"
        result.schema_errors.append(f"{where}: {err.message}")
    if result.schema_errors:
        return result

    acq = record["acquisition"]
    if acq["primary_lead"] not in acq["leads_utilized"]:
        result.semantic_errors.append(
            "acquisition.primary_lead no pertenece a acquisition.leads_utilized"
        )

    qc = record["quality_control"]
    total, rejected = qc.get("n_windows_total"), qc.get("n_windows_rejected")
    if total is not None and rejected is not None:
        if rejected > total:
            result.semantic_errors.append("n_windows_rejected supera n_windows_total")
        elif total > 0:
            implied = 100.0 * rejected / total
            if abs(implied - qc["rejection_ratio_percentage"]) > 0.1:
                result.semantic_errors.append(
                    "rejection_ratio_percentage no coincide con n_windows_rejected / "
                    f"n_windows_total ({implied:.2f} %)"
                )

    if record["reference_sync"]["reference_validation_standard"] == "none_documented":
        result.blocking_warnings.append(
            "Comparador sin norma de validación documentada (S1): el registro no "
            "puede certificarse en el DQR."
        )
    if record["provenance"]["custody_key_status"] == "pseudonymised_key_retained":
        result.notices.append(
            "Registro seudonimizado (llave retenida por el custodio); no es "
            "anonimización irreversible."
        )
    return result
