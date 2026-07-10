"""
Endpoints para gestión de consultores y consulta de respuestas.

Un "consultor" es un usuario al que el administrador le asigna acceso de
solo-lectura a respuestas de otros, según uno de cuatro alcances:
  - form          → todas las respuestas de un formato
  - user          → todas las respuestas que diligencia un usuario
  - form_user     → respuestas de un formato específico hechas por un usuario
  - category      → respuestas de los formatos directos de una categoría
                    (no recursivo: subcategorías NO se incluyen)

Un mismo consultor puede tener múltiples asignaciones; el conjunto de respuestas
visibles es la unión de todas sus reglas activas.
"""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.core.security import get_current_user, require_roles
from app.core.permissions import (
    _consultant_visibility_conditions,
    can_consultant_view_response,
)
from app.models import (
    Answer,
    AnswerHistory,
    ConsultantAssignment,
    ConsultantScope,
    Form,
    FormCategory,
    Response,
    ResponseApproval,
    User,
    UserType,
)
from app.schemas import (
    ConsultantAssignmentBulkCreate,
    ConsultantAssignmentCreate,
    ConsultantAssignmentOut,
    ConsultantAssignmentUpdate,
    ConsultantResponseRow,
    ConsultantResponsesPage,
    ConsultantScopeStr,
    ConsultantUserOut,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _validate_scope_payload(
    scope: ConsultantScopeStr,
    form_id: Optional[int],
    target_user_id: Optional[int],
    category_id: Optional[int],
) -> None:
    """Garantiza que los campos requeridos por cada scope estén presentes."""
    if scope == ConsultantScopeStr.form:
        if not form_id or target_user_id or category_id:
            raise HTTPException(400, "scope=form requiere solo form_id")
    elif scope == ConsultantScopeStr.user:
        if not target_user_id or form_id or category_id:
            raise HTTPException(400, "scope=user requiere solo target_user_id")
    elif scope == ConsultantScopeStr.form_user:
        if not (form_id and target_user_id) or category_id:
            raise HTTPException(400, "scope=form_user requiere form_id y target_user_id")
    elif scope == ConsultantScopeStr.category:
        if not category_id or form_id or target_user_id:
            raise HTTPException(400, "scope=category requiere solo category_id")


def _serialize_assignment(a: ConsultantAssignment) -> ConsultantAssignmentOut:
    return ConsultantAssignmentOut(
        id=a.id,
        consultant_id=a.consultant_id,
        consultant_name=a.consultant.name if a.consultant else None,
        consultant_email=a.consultant.email if a.consultant else None,
        scope=ConsultantScopeStr(a.scope.value),
        form_id=a.form_id,
        form_title=a.form.title if a.form else None,
        target_user_id=a.target_user_id,
        target_user_name=a.target_user.name if a.target_user else None,
        category_id=a.category_id,
        category_name=a.category.name if a.category else None,
        is_active=a.is_active,
        created_at=a.created_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints ADMIN (admin / creator)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/assignments", response_model=ConsultantAssignmentOut)
def create_assignment(
    payload: ConsultantAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    _validate_scope_payload(
        payload.scope, payload.form_id, payload.target_user_id, payload.category_id
    )

    if not db.query(User.id).filter(User.id == payload.consultant_id).first():
        raise HTTPException(404, "Consultor no encontrado")
    if payload.form_id and not db.query(Form.id).filter(Form.id == payload.form_id).first():
        raise HTTPException(404, "Formato no encontrado")
    if payload.target_user_id and not db.query(User.id).filter(User.id == payload.target_user_id).first():
        raise HTTPException(404, "Usuario objetivo no encontrado")
    if payload.category_id and not db.query(FormCategory.id).filter(FormCategory.id == payload.category_id).first():
        raise HTTPException(404, "Categoría no encontrada")

    dup_q = db.query(ConsultantAssignment).filter(
        ConsultantAssignment.consultant_id == payload.consultant_id,
        ConsultantAssignment.scope == ConsultantScope(payload.scope.value),
        ConsultantAssignment.is_active.is_(True),
    )
    dup_q = dup_q.filter(
        ConsultantAssignment.form_id == payload.form_id
        if payload.form_id is not None
        else ConsultantAssignment.form_id.is_(None)
    )
    dup_q = dup_q.filter(
        ConsultantAssignment.target_user_id == payload.target_user_id
        if payload.target_user_id is not None
        else ConsultantAssignment.target_user_id.is_(None)
    )
    dup_q = dup_q.filter(
        ConsultantAssignment.category_id == payload.category_id
        if payload.category_id is not None
        else ConsultantAssignment.category_id.is_(None)
    )
    if dup_q.first():
        raise HTTPException(400, "Ya existe una asignación equivalente activa")

    new_a = ConsultantAssignment(
        consultant_id=payload.consultant_id,
        scope=ConsultantScope(payload.scope.value),
        form_id=payload.form_id,
        target_user_id=payload.target_user_id,
        category_id=payload.category_id,
        created_by=current_user.id,
        is_active=True,
    )
    db.add(new_a)
    db.commit()
    db.refresh(new_a)
    # cargar relaciones para serializar
    db.refresh(new_a)
    new_a = (
        db.query(ConsultantAssignment)
        .options(
            joinedload(ConsultantAssignment.consultant),
            joinedload(ConsultantAssignment.target_user),
            joinedload(ConsultantAssignment.form),
            joinedload(ConsultantAssignment.category),
        )
        .filter(ConsultantAssignment.id == new_a.id)
        .first()
    )
    return _serialize_assignment(new_a)


@router.post("/assignments/bulk", response_model=List[ConsultantAssignmentOut])
def bulk_create_assignments(
    payload: ConsultantAssignmentBulkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Crea varias reglas para un consultor en una transacción atómica.

    Valida todas las reglas antes de insertar; si una falla (FK inexistente,
    payload inconsistente con el scope, o duplicado activo), no se inserta
    ninguna y se devuelve 400 con el detalle del error.
    """
    if not payload.rules:
        raise HTTPException(400, "Debe enviar al menos una regla")

    if not db.query(User.id).filter(User.id == payload.consultant_id).first():
        raise HTTPException(404, "Consultor no encontrado")

    # ── Validación previa de TODAS las reglas (fail-fast antes de tocar DB) ──
    for idx, rule in enumerate(payload.rules, start=1):
        try:
            _validate_scope_payload(
                rule.scope, rule.form_id, rule.target_user_id, rule.category_id
            )
        except HTTPException as e:
            raise HTTPException(400, f"Regla #{idx}: {e.detail}")

        if rule.form_id and not db.query(Form.id).filter(Form.id == rule.form_id).first():
            raise HTTPException(404, f"Regla #{idx}: formato {rule.form_id} no encontrado")
        if rule.target_user_id and not db.query(User.id).filter(User.id == rule.target_user_id).first():
            raise HTTPException(404, f"Regla #{idx}: usuario {rule.target_user_id} no encontrado")
        if rule.category_id and not db.query(FormCategory.id).filter(FormCategory.id == rule.category_id).first():
            raise HTTPException(404, f"Regla #{idx}: categoría {rule.category_id} no encontrada")

        # Duplicado en BD
        dup_q = db.query(ConsultantAssignment).filter(
            ConsultantAssignment.consultant_id == payload.consultant_id,
            ConsultantAssignment.scope == ConsultantScope(rule.scope.value),
            ConsultantAssignment.is_active.is_(True),
        )
        dup_q = dup_q.filter(
            ConsultantAssignment.form_id == rule.form_id
            if rule.form_id is not None
            else ConsultantAssignment.form_id.is_(None)
        )
        dup_q = dup_q.filter(
            ConsultantAssignment.target_user_id == rule.target_user_id
            if rule.target_user_id is not None
            else ConsultantAssignment.target_user_id.is_(None)
        )
        dup_q = dup_q.filter(
            ConsultantAssignment.category_id == rule.category_id
            if rule.category_id is not None
            else ConsultantAssignment.category_id.is_(None)
        )
        if dup_q.first():
            raise HTTPException(
                400, f"Regla #{idx}: ya existe una asignación equivalente activa"
            )

    # Duplicados ENTRE las reglas del propio payload
    seen_keys = set()
    for idx, rule in enumerate(payload.rules, start=1):
        key = (rule.scope.value, rule.form_id, rule.target_user_id, rule.category_id)
        if key in seen_keys:
            raise HTTPException(
                400, f"Regla #{idx}: duplicada dentro del envío"
            )
        seen_keys.add(key)

    # ── Inserción atómica ──
    new_records: List[ConsultantAssignment] = []
    try:
        for rule in payload.rules:
            obj = ConsultantAssignment(
                consultant_id=payload.consultant_id,
                scope=ConsultantScope(rule.scope.value),
                form_id=rule.form_id,
                target_user_id=rule.target_user_id,
                category_id=rule.category_id,
                created_by=current_user.id,
                is_active=True,
            )
            db.add(obj)
            new_records.append(obj)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Error al crear asignaciones")

    # Recargar con relaciones para serializar
    ids = [r.id for r in new_records]
    rows = (
        db.query(ConsultantAssignment)
        .options(
            joinedload(ConsultantAssignment.consultant),
            joinedload(ConsultantAssignment.target_user),
            joinedload(ConsultantAssignment.form),
            joinedload(ConsultantAssignment.category),
        )
        .filter(ConsultantAssignment.id.in_(ids))
        .all()
    )
    return [_serialize_assignment(a) for a in rows]


@router.get("/assignments", response_model=List[ConsultantAssignmentOut])
def list_all_assignments(
    consultant_id: Optional[int] = None,
    only_active: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    q = db.query(ConsultantAssignment).options(
        joinedload(ConsultantAssignment.consultant),
        joinedload(ConsultantAssignment.target_user),
        joinedload(ConsultantAssignment.form),
        joinedload(ConsultantAssignment.category),
    )
    if consultant_id:
        q = q.filter(ConsultantAssignment.consultant_id == consultant_id)
    if only_active:
        q = q.filter(ConsultantAssignment.is_active.is_(True))
    rows = q.order_by(ConsultantAssignment.created_at.desc()).all()
    return [_serialize_assignment(a) for a in rows]


@router.get("/users", response_model=List[ConsultantUserOut])
def list_consultant_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Agrupa asignaciones por consultor. Útil para la pantalla admin."""
    assignments = (
        db.query(ConsultantAssignment)
        .options(
            joinedload(ConsultantAssignment.consultant),
            joinedload(ConsultantAssignment.target_user),
            joinedload(ConsultantAssignment.form),
            joinedload(ConsultantAssignment.category),
        )
        .filter(ConsultantAssignment.is_active.is_(True))
        .all()
    )
    grouped: dict[int, ConsultantUserOut] = {}
    for a in assignments:
        if not a.consultant:
            continue
        bucket = grouped.get(a.consultant_id)
        if bucket is None:
            bucket = ConsultantUserOut(
                consultant_id=a.consultant_id,
                consultant_name=a.consultant.name,
                consultant_email=a.consultant.email,
                assignments=[],
            )
            grouped[a.consultant_id] = bucket
        bucket.assignments.append(_serialize_assignment(a))
    return list(grouped.values())


@router.put("/assignments/{assignment_id}", response_model=ConsultantAssignmentOut)
def update_assignment(
    assignment_id: int,
    payload: ConsultantAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    a = db.query(ConsultantAssignment).filter(ConsultantAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(404, "Asignación no encontrada")

    if payload.scope is not None:
        a.scope = ConsultantScope(payload.scope.value)
    if payload.form_id is not None:
        a.form_id = payload.form_id or None
    if payload.target_user_id is not None:
        a.target_user_id = payload.target_user_id or None
    if payload.category_id is not None:
        a.category_id = payload.category_id or None
    if payload.is_active is not None:
        a.is_active = payload.is_active

    # Si cambia el scope, resetear campos que no aplican a la nueva combinación
    # para evitar dejar FKs huérfanas que no deberían existir según el scope.
    if a.scope == ConsultantScope.form:
        a.target_user_id = None
        a.category_id = None
    elif a.scope == ConsultantScope.user:
        a.form_id = None
        a.category_id = None
    elif a.scope == ConsultantScope.form_user:
        a.category_id = None
    elif a.scope == ConsultantScope.category:
        a.form_id = None
        a.target_user_id = None

    # validar la combinación final
    final_scope = ConsultantScopeStr(a.scope.value)
    _validate_scope_payload(final_scope, a.form_id, a.target_user_id, a.category_id)

    # Bloquear duplicados activos contra otras asignaciones del mismo consultor
    dup_q = db.query(ConsultantAssignment).filter(
        ConsultantAssignment.id != a.id,
        ConsultantAssignment.consultant_id == a.consultant_id,
        ConsultantAssignment.scope == a.scope,
        ConsultantAssignment.is_active.is_(True),
    )
    dup_q = dup_q.filter(
        ConsultantAssignment.form_id == a.form_id
        if a.form_id is not None
        else ConsultantAssignment.form_id.is_(None)
    )
    dup_q = dup_q.filter(
        ConsultantAssignment.target_user_id == a.target_user_id
        if a.target_user_id is not None
        else ConsultantAssignment.target_user_id.is_(None)
    )
    dup_q = dup_q.filter(
        ConsultantAssignment.category_id == a.category_id
        if a.category_id is not None
        else ConsultantAssignment.category_id.is_(None)
    )
    if dup_q.first():
        db.rollback()
        raise HTTPException(400, "Ya existe otra asignación equivalente activa")

    db.commit()
    a = (
        db.query(ConsultantAssignment)
        .options(
            joinedload(ConsultantAssignment.consultant),
            joinedload(ConsultantAssignment.target_user),
            joinedload(ConsultantAssignment.form),
            joinedload(ConsultantAssignment.category),
        )
        .filter(ConsultantAssignment.id == assignment_id)
        .first()
    )
    return _serialize_assignment(a)


@router.delete("/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    a = db.query(ConsultantAssignment).filter(ConsultantAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(404, "Asignación no encontrada")
    db.delete(a)
    db.commit()
    return {"deleted": True, "id": assignment_id}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints CONSULTOR (cualquier usuario autenticado, depende de sus asignaciones)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me/has-assignments")
def me_has_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """True si el usuario actual tiene al menos una asignación activa.

    Usado por el menú lateral para mostrar/ocultar el item 'Respuestas de otros'.
    """
    exists = (
        db.query(ConsultantAssignment.id)
        .filter(
            ConsultantAssignment.consultant_id == current_user.id,
            ConsultantAssignment.is_active.is_(True),
        )
        .first()
        is not None
    )
    return {"has_assignments": exists}


@router.get("/me/filter-options")
def me_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve formatos, usuarios y categorías que el consultor puede filtrar
    en su pantalla, derivados de sus asignaciones activas."""
    assignments = (
        db.query(ConsultantAssignment)
        .options(
            joinedload(ConsultantAssignment.form),
            joinedload(ConsultantAssignment.target_user),
            joinedload(ConsultantAssignment.category),
        )
        .filter(
            ConsultantAssignment.consultant_id == current_user.id,
            ConsultantAssignment.is_active.is_(True),
        )
        .all()
    )

    forms_dict: dict[int, dict] = {}
    users_dict: dict[int, dict] = {}
    categories_dict: dict[int, dict] = {}

    for a in assignments:
        if a.form:
            forms_dict[a.form.id] = {"id": a.form.id, "title": a.form.title}
        if a.target_user:
            users_dict[a.target_user.id] = {
                "id": a.target_user.id,
                "name": a.target_user.name,
                "email": a.target_user.email,
            }
        if a.category:
            categories_dict[a.category.id] = {
                "id": a.category.id,
                "name": a.category.name,
            }
            # Para una categoría, también listar sus formatos directos
            forms_in_cat = (
                db.query(Form.id, Form.title)
                .filter(Form.id_category == a.category.id)
                .all()
            )
            for fid, ftitle in forms_in_cat:
                forms_dict[fid] = {"id": fid, "title": ftitle}

    return {
        "forms": list(forms_dict.values()),
        "users": list(users_dict.values()),
        "categories": list(categories_dict.values()),
    }


def _query_responses_for_consultant(
    consultant_id: int,
    db: Session,
    form_id: Optional[int],
    target_user_id: Optional[int],
    category_id: Optional[int],
    date_from: Optional[str],
    date_to: Optional[str],
):
    conditions = _consultant_visibility_conditions(consultant_id, db)
    if not conditions:
        return None

    q = (
        db.query(Response)
        .options(
            joinedload(Response.form).joinedload(Form.category),
            joinedload(Response.user),
        )
        .filter(or_(*conditions))
    )

    if form_id:
        q = q.filter(Response.form_id == form_id)
    if target_user_id:
        q = q.filter(Response.user_id == target_user_id)
    if category_id:
        q = q.join(Form, Response.form_id == Form.id).filter(
            Form.id_category == category_id
        )
    if date_from:
        q = q.filter(Response.submitted_at >= date_from)
    if date_to:
        q = q.filter(Response.submitted_at <= date_to)

    return q


@router.get("/me/responses", response_model=ConsultantResponsesPage)
def me_list_responses(
    form_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    category_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = _query_responses_for_consultant(
        current_user.id, db, form_id, target_user_id, category_id, date_from, date_to
    )
    if q is None:
        raise HTTPException(403, "No tiene asignaciones de consultor")

    total = q.count()
    rows = (
        q.order_by(Response.submitted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        ConsultantResponseRow(
            response_id=r.id,
            form_id=r.form_id,
            form_title=r.form.title if r.form else "",
            submitted_by_id=r.user_id,
            submitted_by_name=r.user.name if r.user else "",
            submitted_at=r.submitted_at,
            status=r.status.value if r.status else None,
            category_name=r.form.category.name if (r.form and r.form.category) else None,
        )
        for r in rows
    ]
    return ConsultantResponsesPage(
        items=items, total=total, page=page, page_size=page_size
    )


@router.get("/me/responses/{response_id}/can-view")
def me_can_view(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verifica si el consultor puede ver una respuesta. Usado por el frontend
    antes de navegar al detalle."""
    return {"can_view": can_consultant_view_response(current_user.id, response_id, db)}


def _process_regisfacial(answer_text, question_type):
    """Replica el procesamiento de respuestas regisfacial de forms.py."""
    if question_type != "regisfacial" or not answer_text:
        return answer_text
    try:
        face_data = json.loads(answer_text)
        person_name = "Usuario"
        success = False
        if isinstance(face_data, dict) and "faceData" in face_data:
            face_info = face_data["faceData"]
            if isinstance(face_info, dict):
                success = face_info.get("success", False)
                person_name = face_info.get("personName", "Usuario")
        elif isinstance(face_data, dict):
            success = face_data.get("success", False)
            person_name = face_data.get(
                "personName", face_data.get("person_name", "Usuario")
            )
        if person_name == "Usuario":
            person_name = face_data.get("name", face_data.get("user_name", "Usuario"))
        if success:
            return f"Datos biométricos de {person_name} registrados"
        return f"Error en el registro de datos biométricos de {person_name}"
    except (json.JSONDecodeError, KeyError, TypeError):
        return "Datos biométricos procesados"


def _approval_status_summary(approvals):
    """Resume el estado de un grupo de aprobaciones — pendiente / aprobado / rechazado."""
    if not approvals:
        return {"status": "pendiente", "message": None}
    if any(a.status.value == "rechazado" for a in approvals):
        last_rejected = next(
            (a for a in approvals if a.status.value == "rechazado"), None
        )
        return {
            "status": "rechazado",
            "message": last_rejected.message if last_rejected else None,
        }
    if any(a.status.value == "pendiente" for a in approvals):
        return {"status": "pendiente", "message": None}
    return {"status": "aprobado", "message": None}


@router.get("/me/responses/{response_id}/full")
def me_response_full(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve la información completa de una respuesta para el modal del
    consultor: datos del formato, su form_design y la respuesta con sus
    answers/approvals (mismo shape que /forms/responses/?form_id=X usa para
    una respuesta individual).
    """
    if not can_consultant_view_response(current_user.id, response_id, db):
        raise HTTPException(403, "No tiene permiso para consultar esta respuesta")

    r = (
        db.query(Response)
        .options(
            joinedload(Response.form).joinedload(Form.category),
            joinedload(Response.user),
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.approvals).joinedload(ResponseApproval.user),
        )
        .filter(Response.id == response_id)
        .first()
    )
    if not r:
        raise HTTPException(404, "Respuesta no encontrada")

    # Filtrar answers que sean previous_answer_id (mostrar solo las más recientes)
    histories = (
        db.query(AnswerHistory)
        .filter(AnswerHistory.response_id == response_id)
        .all()
    )
    previous_answer_ids = {
        h.previous_answer_id for h in histories if h.previous_answer_id
    }

    answers_payload = [
        {
            "id_answer": a.id,
            "repeated_id": r.repeated_id,
            "question_id": a.question.id,
            "question_text": a.question.question_text,
            "question_type": a.question.question_type.value
            if hasattr(a.question.question_type, "value")
            else a.question.question_type,
            "answer_text": _process_regisfacial(
                a.answer_text,
                a.question.question_type.value
                if hasattr(a.question.question_type, "value")
                else a.question.question_type,
            ),
            "file_path": a.file_path,
            "form_design_element_id": a.form_design_element_id,
        }
        for a in r.answers
        if a.id not in previous_answer_ids
    ]

    approval_summary = _approval_status_summary(r.approvals)
    approvals_payload = [
        {
            "approval_id": ap.id,
            "sequence_number": ap.sequence_number,
            "is_mandatory": ap.is_mandatory,
            "reconsideration_requested": ap.reconsideration_requested,
            "status": ap.status.value,
            "reviewed_at": ap.reviewed_at.isoformat() if ap.reviewed_at else None,
            "message": ap.message,
            "user": {
                "id": ap.user.id,
                "name": ap.user.name,
                "email": ap.user.email,
                "nickname": ap.user.nickname,
                "num_document": ap.user.num_document,
            },
        }
        for ap in r.approvals
    ]

    form = r.form
    form_payload = {
        "id": form.id,
        "title": form.title,
        "description": form.description,
        "format_type": form.format_type.value if form.format_type else None,
        "created_at": form.created_at.isoformat() if form.created_at else None,
        "category": (
            {
                "id": form.category.id,
                "name": form.category.name,
                "description": form.category.description,
            }
            if form.category
            else None
        ),
    }

    return {
        "form": form_payload,
        "form_design": form.form_design,
        "response": {
            "response_id": r.id,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "status": r.status.value if r.status else None,
            "approval_status": approval_summary["status"],
            "message": approval_summary["message"],
            "submitted_by": {
                "id": r.user.id,
                "name": r.user.name,
                "email": r.user.email,
                "nickname": r.user.nickname,
                "num_document": r.user.num_document,
            }
            if r.user
            else None,
            "answers": answers_payload,
            "approvals": approvals_payload,
        },
    }
