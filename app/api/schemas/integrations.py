# app/api/schemas/integrations.py
#
# Schemas Pydantic para el módulo de Integraciones.
# Payload simplificado donde cada llave es el `label` de un campo del
# form_design del formato. Soporta repeaters (lista de objetos con labels
# hijos) y archivos (previamente subidos via POST /responses/upload-file/).
# Rechaza formatos con preguntas de tipo `firm` o `regisfacial`.
# Rechaza formatos con labels duplicados en el mismo scope.

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ────────────────────────────────────────────────────────────────────────────
# Payload del POST /integrations/answers
# ────────────────────────────────────────────────────────────────────────────

# Una respuesta puede ser:
#   - Un valor escalar (string, number, bool, file_path)
#   - Un dict (para preguntas tipo objeto)
#   - Una lista de dicts (para repeaters: cada dict es una iteración)
AnswerValue = Union[str, int, float, bool, Dict[str, Any], List[Dict[str, Any]], None]


class IntegrationAnswerPayload(BaseModel):
    """
    Payload simplificado para diligenciar un formato desde un sistema externo.
    Las llaves de `answers` son los `label` de los campos del form_design.

    Ejemplo:
    {
      "format_id": 123,
      "answers": {
        "Nombre del cliente": "Acme S.A.",
        "Monto factura": 1500000,
        "Fecha de emisión": "2026-05-20",
        "Items factura": [
          {"Descripción": "Producto A", "Cantidad": 2},
          {"Descripción": "Producto B", "Cantidad": 1}
        ],
        "Factura PDF": "uploaded_abc123.pdf"
      },
      "action": "send_and_close"
    }
    """
    format_id: int = Field(..., description="ID del formato a diligenciar")
    answers: Dict[str, AnswerValue] = Field(
        ...,
        description="Mapa label_del_campo → valor. Para repeaters, el valor es una lista de objetos cuyas llaves son los labels de los campos hijos."
    )
    action: str = Field(
        "send_and_close",
        description="'send' = guardar borrador, 'send_and_close' = enviar para aprobación/cerrar"
    )


# ────────────────────────────────────────────────────────────────────────────
# Respuesta del POST /integrations/answers
# ────────────────────────────────────────────────────────────────────────────

class IntegrationAnswerResult(BaseModel):
    response_id: int
    status: str
    message: str


# ────────────────────────────────────────────────────────────────────────────
# Admin: gestión de accesos
# ────────────────────────────────────────────────────────────────────────────

class IntegratorAccessAssign(BaseModel):
    """Body para asignar uno o varios formatos a un usuario integrador."""
    user_id: int
    format_ids: List[int] = Field(..., min_length=1)


class IntegratorAccessItem(BaseModel):
    id: int
    user_id: int
    format_id: int
    format_title: str
    assigned_by: Optional[int] = None
    assigned_at: datetime

    class Config:
        from_attributes = True


class IntegratorAccessList(BaseModel):
    items: List[IntegratorAccessItem]


# ────────────────────────────────────────────────────────────────────────────
# Sección "Mis integraciones" para el integrador
# ────────────────────────────────────────────────────────────────────────────

class IntegrationFieldDoc(BaseModel):
    """Un campo respondible del form_design (top-level o hijo de repeater)."""
    label: str
    field_type: str
    required: bool


class IntegrationRepeaterDoc(BaseModel):
    """Un repeater del form_design, con sus campos hijos."""
    label: str
    required: bool
    children: List[IntegrationFieldDoc]


class IntegrationFormatDoc(BaseModel):
    """Documentación de un formato asignado al integrador, lista para usar."""
    format_id: int
    title: str
    description: Optional[str] = None
    fields: List[IntegrationFieldDoc] = Field(
        default_factory=list,
        description="Campos top-level (fuera de repeaters) que se pueden integrar.",
    )
    repeaters: List[IntegrationRepeaterDoc] = Field(
        default_factory=list,
        description="Repeaters del formato, cada uno con sus campos hijos integrables.",
    )
    has_unsupported_questions: bool = Field(
        ...,
        description="True si el formato contiene preguntas tipo firm o regisfacial (no integrables).",
    )
    has_duplicate_labels: bool = Field(
        False,
        description="True si el formato tiene labels duplicados en el mismo scope (no integrable).",
    )
    duplicate_labels: List[str] = Field(
        default_factory=list,
        description="Lista plana de labels duplicados encontrados (si los hay).",
    )
    duplicate_labels_by_scope: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Labels duplicados agrupados por scope (top-level o repeater:<label>). Útil para diagnosticar dónde está el problema.",
    )


class MyIntegrationsResponse(BaseModel):
    formats: List[IntegrationFormatDoc]
