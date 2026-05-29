# app/api/endpoints/integrations.py
#
# Endpoint único para integraciones externas vía formatos.
#
# Modelo: cualquier usuario con ≥1 fila en `integrator_format_access` es un
# "integrador" de facto. Usa su JWT normal; el endpoint valida que tenga
# acceso al `format_id` que está intentando diligenciar.
#
# Payload simplificado: las llaves son los `label` del form_design del formato.
# Repeaters se mandan como lista de objetos cuyas llaves son los labels de
# los campos hijos. Archivos: primero subir con POST /responses/upload-file/,
# luego pasar el nombre devuelto como valor escalar.

import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.api.schemas.integrations import (
    IntegrationAnswerPayload,
    IntegrationAnswerResult,
    IntegrationFieldDoc,
    IntegrationFormatDoc,
    IntegrationRepeaterDoc,
    IntegratorAccessAssign,
    IntegratorAccessItem,
    IntegratorAccessList,
    MyIntegrationsResponse,
)
from app.core.security import get_current_user
from app.crud import post_create_response
from app.database import get_db
from app.models import (
    Answer,
    Form,
    FormatType,
    IntegratorFormatAccess,
    ResponseStatus,
    User,
)

router = APIRouter()


# ────────────────────────────────────────────────────────────────────────────
# Clasificación de tipos de form_design
# ────────────────────────────────────────────────────────────────────────────

# Contenedores que NO son repeaters: sus children pertenecen al mismo scope.
LAYOUT_TYPES = {"verticalLayout", "horizontalLayout"}

# Contenedor que abre un scope nuevo (cada iteración usa un form_design_element_id distinto).
REPEATER_TYPES = {"repeater"}

# Tipos de campo que NO se pueden integrar.
UNSUPPORTED_TYPES = {"firm", "regisfacial"}

# Tipos puramente visuales — se ignoran (no producen Answer ni cuentan como integrables).
DISPLAY_TYPES = {"label", "divider", "helpText", "image", "button", "headerTable"}


# ────────────────────────────────────────────────────────────────────────────
# Walker del form_design
# ────────────────────────────────────────────────────────────────────────────

class FieldInfo:
    """Info necesaria para crear el Answer correspondiente a un campo."""
    __slots__ = ("item_id", "id_question", "field_type", "required", "label")

    def __init__(self, item_id: str, id_question: Optional[int], field_type: str, required: bool, label: str):
        self.item_id = item_id
        self.id_question = id_question
        self.field_type = field_type
        self.required = required
        self.label = label


class RepeaterInfo:
    """Info de un repeater: su id (UUID en form_design), label, y el map de children."""
    __slots__ = ("item_id", "label", "required", "children_by_label")

    def __init__(self, item_id: str, label: str, required: bool, children_by_label: Dict[str, FieldInfo]):
        self.item_id = item_id
        self.label = label
        self.required = required
        self.children_by_label = children_by_label


class FormWalk:
    """Resultado de recorrer el form_design completo."""
    __slots__ = ("top_fields", "top_repeaters", "duplicate_labels_by_scope", "has_unsupported")

    def __init__(self) -> None:
        self.top_fields: Dict[str, FieldInfo] = {}
        self.top_repeaters: Dict[str, RepeaterInfo] = {}
        self.duplicate_labels_by_scope: Dict[str, List[str]] = {}  # scope_name → labels
        self.has_unsupported: bool = False


def _parse_form_design(raw) -> List[dict]:
    """form_design puede venir como list, dict (algunas formas), str JSON, o None."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # Algunos formatos guardan { "items": [...] } o { "fields": [...] }
        for key in ("items", "fields", "design", "elements"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return _parse_form_design(parsed)
        except json.JSONDecodeError:
            return []
    return []


def _extract_label(item: dict) -> Optional[str]:
    """El label visible está en props.label. Algunos elementos pueden no tener uno."""
    props = item.get("props") or {}
    label = props.get("label")
    if isinstance(label, str):
        label = label.strip()
        return label or None
    return None


def _is_required(item: dict) -> bool:
    props = item.get("props") or {}
    return bool(props.get("required", False))


def _walk(items: List[dict], walk: FormWalk) -> None:
    """Recorre items top-level, llenando walk.top_fields y walk.top_repeaters."""
    _walk_scope(items, walk.top_fields, walk.top_repeaters, walk, scope_name="top-level")


def _walk_scope(
    items: List[dict],
    fields_out: Dict[str, FieldInfo],
    repeaters_out: Dict[str, RepeaterInfo],
    walk: FormWalk,
    scope_name: str,
) -> None:
    """
    Recorre los items dentro de un scope. Layouts se aplanan (su children va al mismo scope).
    Repeaters abren un scope nuevo (sus children van a un map separado).
    """
    duplicates: List[str] = []

    def add_field(label: str, info: FieldInfo) -> None:
        if label in fields_out or label in repeaters_out:
            duplicates.append(label)
            return
        fields_out[label] = info

    def add_repeater(label: str, info: RepeaterInfo) -> None:
        if label in fields_out or label in repeaters_out:
            duplicates.append(label)
            return
        repeaters_out[label] = info

    for item in items:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        label = _extract_label(item)

        if itype in DISPLAY_TYPES:
            continue

        if itype in UNSUPPORTED_TYPES:
            walk.has_unsupported = True
            continue

        if itype in LAYOUT_TYPES:
            # Mismo scope: recursar pasando los mismos out maps
            children = item.get("children") or []
            _walk_scope(children, fields_out, repeaters_out, walk, scope_name)
            continue

        if itype in REPEATER_TYPES:
            if not label:
                # Sin label no es accesible vía integración — ignorar
                continue
            children = item.get("children") or []
            child_fields: Dict[str, FieldInfo] = {}
            child_repeaters_unused: Dict[str, RepeaterInfo] = {}  # no permitimos repeater dentro de repeater por ahora
            _walk_scope(
                children,
                child_fields,
                child_repeaters_unused,
                walk,
                scope_name=f"repeater:{label}",
            )
            add_repeater(
                label,
                RepeaterInfo(
                    item_id=str(item.get("id") or ""),
                    label=label,
                    required=_is_required(item),
                    children_by_label=child_fields,
                ),
            )
            continue

        # Campo respondible normal
        if not label:
            continue
        id_question = item.get("id_question")
        try:
            id_question = int(id_question) if id_question is not None else None
        except (TypeError, ValueError):
            id_question = None
        if id_question is None:
            # Sin id_question no podemos crear Answer
            continue
        add_field(
            label,
            FieldInfo(
                item_id=str(item.get("id") or ""),
                id_question=id_question,
                field_type=str(itype or ""),
                required=_is_required(item),
                label=label,
            ),
        )

    if duplicates:
        walk.duplicate_labels_by_scope.setdefault(scope_name, []).extend(duplicates)


def walk_form_design(form_design_raw) -> FormWalk:
    items = _parse_form_design(form_design_raw)
    walk = FormWalk()
    _walk(items, walk)
    return walk


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _ensure_admin(current_user: User) -> None:
    if current_user.user_type.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden gestionar accesos de integración",
        )


def _get_form_or_404(db: Session, format_id: int) -> Form:
    form = db.query(Form).filter(Form.id == format_id).first()
    if not form:
        raise HTTPException(status_code=404, detail=f"Formato {format_id} no encontrado")
    return form


def verify_integrator_access(
    format_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    access = (
        db.query(IntegratorFormatAccess)
        .filter(
            IntegratorFormatAccess.user_id == current_user.id,
            IntegratorFormatAccess.format_id == format_id,
        )
        .first()
    )
    if not access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes acceso de integración al formato {format_id}",
        )
    return current_user


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_answer(response_id: int, field: FieldInfo, value, element_id: Optional[str]) -> Answer:
    """Construye un Answer ORM para un campo respondible."""
    # file: el valor es el nombre devuelto por /upload-file/
    if field.field_type == "file" and isinstance(value, str):
        return Answer(
            response_id=response_id,
            question_id=field.id_question,
            answer_text=None,
            file_path=value,
            form_design_element_id=element_id,
        )

    if isinstance(value, dict):
        return Answer(
            response_id=response_id,
            question_id=field.id_question,
            answer_text=json.dumps(value, ensure_ascii=False, default=str),
            file_path=None,
            form_design_element_id=element_id,
        )

    return Answer(
        response_id=response_id,
        question_id=field.id_question,
        answer_text=_to_text(value),
        file_path=None,
        form_design_element_id=element_id,
    )


# ────────────────────────────────────────────────────────────────────────────
# POST /integrations/answers  — el endpoint principal
# ────────────────────────────────────────────────────────────────────────────

@router.post("/answers", response_model=IntegrationAnswerResult)
async def submit_integration_answer(
    payload: IntegrationAnswerPayload = Body(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Recibe una respuesta diligenciada de un sistema externo y la guarda como
    si fuera una respuesta normal (genera aprobaciones, dispara emails, etc.).

    Cada llave del map `answers` es el `label` (props.label) de un campo del
    form_design del formato. Para repeaters, el valor es una lista de objetos
    cuyas llaves son los labels de los campos hijos.
    """
    verify_integrator_access(payload.format_id, db, current_user)

    form = _get_form_or_404(db, payload.format_id)

    # 1. Parsear y validar form_design
    walk = walk_form_design(form.form_design)

    if walk.has_unsupported:
        raise HTTPException(
            status_code=400,
            detail="Este formato contiene preguntas de firma o reconocimiento facial y no puede diligenciarse por integraciones.",
        )

    if walk.duplicate_labels_by_scope:
        details = "; ".join(
            f"{scope}: {', '.join(sorted(set(labels)))}"
            for scope, labels in walk.duplicate_labels_by_scope.items()
        )
        raise HTTPException(
            status_code=400,
            detail=f"Este formato tiene labels duplicados en el mismo scope y no es integrable. Duplicados → {details}",
        )

    # 2. Validar que TODAS las llaves del payload existen
    unknown = [
        k for k in payload.answers.keys()
        if k not in walk.top_fields and k not in walk.top_repeaters
    ]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Labels desconocidos en este formato: {', '.join(unknown)}",
        )

    # 3. Determinar estado y aprobaciones
    if form.format_type == FormatType.cerrado:
        response_status = ResponseStatus.submitted
        create_approvals = True
    else:
        if payload.action == "send_and_close":
            response_status = ResponseStatus.submitted
            create_approvals = True
        else:
            response_status = ResponseStatus.draft
            create_approvals = False

    # 4. Si el payload incluye al menos un repeater, propagamos su UUID a
    #    Response.repeated_id. El endpoint /forms/responses/?form_id=... copia
    #    Response.repeated_id en TODAS las answers al leer (forms.py:1112), y la
    #    UI de ResponsesModal lo usa como "hasValidRepeatedId" para distinguir
    #    answers de repeaters de las flat. Si lo dejamos en NULL, los valores
    #    de repeater quedan invisibles aunque estén guardados en BD.
    payload_repeater_uuid: Optional[str] = None
    for key in payload.answers.keys():
        if key in walk.top_repeaters:
            payload_repeater_uuid = walk.top_repeaters[key].item_id or None
            if payload_repeater_uuid:
                break

    # 5. Crear el Response (reusa toda la lógica existente: aprobaciones + emails)
    result = await post_create_response(
        db=db,
        form_id=payload.format_id,
        user_id=current_user.id,
        current_user=current_user,
        request=request,
        mode="online",
        repeated_id=payload_repeater_uuid,
        create_approvals=create_approvals,
        status=response_status,
    )
    response_id = result.get("response_id") if isinstance(result, dict) else getattr(result, "id", None)
    if response_id is None:
        raise HTTPException(status_code=500, detail="No se pudo obtener response_id tras crear el Response")

    # 6. Crear Answer rows
    #
    # ⚠️ Sobre `form_design_element_id` para repeaters:
    #   El sistema reconstruye `repeated_id` al leer mapeando
    #   form_design_element_id (el `id` del child en form_design) → repeater
    #   (ver crud.py:_reconstruct_repeated_ids). Por eso TODAS las filas de un
    #   repeater para un mismo child usan el MISMO form_design_element_id
    #   (el `id` estático del child). El diferenciador entre filas es la
    #   posición de inserción de los Answer rows. Esto es exactamente lo que
    #   hace la UI al diligenciar manualmente (ver ListForms.tsx:processFormItemInsideRepeater).
    for key, value in payload.answers.items():
        if key in walk.top_fields:
            field = walk.top_fields[key]
            db.add(_build_answer(response_id, field, value, field.item_id or None))
        else:
            # Es un repeater
            rep = walk.top_repeaters[key]
            if not isinstance(value, list):
                raise HTTPException(
                    status_code=400,
                    detail=f"El campo '{key}' es un repeater. El valor debe ser una lista de objetos.",
                )
            for iteration in value:
                if not isinstance(iteration, dict):
                    raise HTTPException(
                        status_code=400,
                        detail=f"En el repeater '{key}' cada item debe ser un objeto.",
                    )
                for child_label, child_value in iteration.items():
                    if child_label not in rep.children_by_label:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Label hijo desconocido en repeater '{key}': {child_label}",
                        )
                    child = rep.children_by_label[child_label]
                    db.add(_build_answer(response_id, child, child_value, child.item_id or None))

    db.commit()

    return IntegrationAnswerResult(
        response_id=response_id,
        status=response_status.value,
        message="Respuesta de integración registrada correctamente",
    )


# ────────────────────────────────────────────────────────────────────────────
# GET /integrations/my-formats
# ────────────────────────────────────────────────────────────────────────────

@router.get("/my-formats", response_model=MyIntegrationsResponse)
def my_integration_formats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista los formatos a los que el usuario actual tiene acceso de integración."""
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    accesses = (
        db.query(IntegratorFormatAccess)
        .filter(IntegratorFormatAccess.user_id == current_user.id)
        .options(joinedload(IntegratorFormatAccess.form))
        .all()
    )

    formats_out: List[IntegrationFormatDoc] = []
    for access in accesses:
        form = access.form
        if form is None or not form.is_enabled:
            continue

        walk = walk_form_design(form.form_design)

        duplicates_flat: List[str] = []
        for labels in walk.duplicate_labels_by_scope.values():
            duplicates_flat.extend(labels)

        fields_docs = [
            IntegrationFieldDoc(label=f.label, field_type=f.field_type, required=f.required)
            for f in walk.top_fields.values()
        ]

        repeaters_docs = [
            IntegrationRepeaterDoc(
                label=r.label,
                required=r.required,
                children=[
                    IntegrationFieldDoc(label=c.label, field_type=c.field_type, required=c.required)
                    for c in r.children_by_label.values()
                ],
            )
            for r in walk.top_repeaters.values()
        ]

        # Dedupe por scope para que la UI no repita
        duplicates_by_scope = {
            scope: sorted(set(labels))
            for scope, labels in walk.duplicate_labels_by_scope.items()
        }

        formats_out.append(
            IntegrationFormatDoc(
                format_id=form.id,
                title=form.title,
                description=form.description,
                fields=fields_docs,
                repeaters=repeaters_docs,
                has_unsupported_questions=walk.has_unsupported,
                has_duplicate_labels=bool(duplicates_flat),
                duplicate_labels=sorted(set(duplicates_flat)),
                duplicate_labels_by_scope=duplicates_by_scope,
            )
        )

    return MyIntegrationsResponse(formats=formats_out)


# ────────────────────────────────────────────────────────────────────────────
# Admin: listar / asignar / revocar accesos
# ────────────────────────────────────────────────────────────────────────────

@router.get("/access", response_model=IntegratorAccessList)
def list_integrator_access(
    user_id: Optional[int] = Query(None, description="Filtrar por usuario integrador"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)

    q = db.query(IntegratorFormatAccess).options(joinedload(IntegratorFormatAccess.form))
    if user_id is not None:
        q = q.filter(IntegratorFormatAccess.user_id == user_id)

    rows = q.order_by(IntegratorFormatAccess.assigned_at.desc()).all()

    return IntegratorAccessList(
        items=[
            IntegratorAccessItem(
                id=r.id,
                user_id=r.user_id,
                format_id=r.format_id,
                format_title=(r.form.title if r.form else f"#{r.format_id}"),
                assigned_by=r.assigned_by,
                assigned_at=r.assigned_at,
            )
            for r in rows
        ]
    )


@router.post("/access", response_model=IntegratorAccessList, status_code=status.HTTP_201_CREATED)
def assign_integrator_access(
    payload: IntegratorAccessAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)

    target_user = db.query(User).filter(User.id == payload.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    existing_format_ids = {
        r.format_id
        for r in db.query(IntegratorFormatAccess.format_id)
        .filter(IntegratorFormatAccess.user_id == payload.user_id)
        .all()
    }

    created: List[IntegratorFormatAccess] = []
    for fid in payload.format_ids:
        if fid in existing_format_ids:
            continue
        form = db.query(Form).filter(Form.id == fid).first()
        if not form:
            raise HTTPException(status_code=404, detail=f"Formato {fid} no existe")
        row = IntegratorFormatAccess(
            user_id=payload.user_id,
            format_id=fid,
            assigned_by=current_user.id,
        )
        db.add(row)
        created.append(row)

    db.commit()
    for r in created:
        db.refresh(r)

    return list_integrator_access(user_id=payload.user_id, db=db, current_user=current_user)


@router.delete("/access/{user_id}/{format_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_integrator_access(
    user_id: int,
    format_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)

    row = (
        db.query(IntegratorFormatAccess)
        .filter(
            IntegratorFormatAccess.user_id == user_id,
            IntegratorFormatAccess.format_id == format_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    db.delete(row)
    db.commit()
    return None
