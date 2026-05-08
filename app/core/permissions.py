"""Helpers de autorización a nivel de fila (row-level access control).

Centraliza la lógica de "¿puede este usuario ver esta respuesta?" para evitar
que cada endpoint reimplemente reglas y se desincronicen.

Reglas para `can_user_view_response`:
  - admin / creator → siempre
  - dueño de la respuesta → sí
  - aprobador asignado a esa respuesta → sí
  - consultor con al menos una asignación que cubra esa respuesta → sí
  - cualquier otro caso → no
"""

from typing import List

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import (
    ConsultantAssignment,
    ConsultantScope,
    Form,
    Response,
    ResponseApproval,
    User,
    UserType,
)


def _consultant_visibility_conditions(consultant_id: int, db: Session) -> List:
    """Devuelve la lista de condiciones SQL (una por asignación activa).

    Devuelve [] si el usuario no tiene asignaciones activas.
    """
    assignments = (
        db.query(ConsultantAssignment)
        .filter(
            ConsultantAssignment.consultant_id == consultant_id,
            ConsultantAssignment.is_active.is_(True),
        )
        .all()
    )
    conditions = []
    for a in assignments:
        if a.scope == ConsultantScope.form and a.form_id:
            conditions.append(Response.form_id == a.form_id)
        elif a.scope == ConsultantScope.user and a.target_user_id:
            conditions.append(Response.user_id == a.target_user_id)
        elif a.scope == ConsultantScope.form_user and a.form_id and a.target_user_id:
            conditions.append(
                and_(Response.form_id == a.form_id, Response.user_id == a.target_user_id)
            )
        elif a.scope == ConsultantScope.category and a.category_id:
            form_ids_subq = (
                db.query(Form.id).filter(Form.id_category == a.category_id).subquery()
            )
            conditions.append(Response.form_id.in_(form_ids_subq))
    return conditions


def can_consultant_view_response(
    consultant_id: int, response_id: int, db: Session
) -> bool:
    """True si el consultor tiene al menos una asignación que cubra esta respuesta."""
    conditions = _consultant_visibility_conditions(consultant_id, db)
    if not conditions:
        return False
    exists = (
        db.query(Response.id)
        .filter(Response.id == response_id)
        .filter(or_(*conditions))
        .first()
    )
    return exists is not None


def can_user_view_response(user: User, response_id: int, db: Session) -> bool:
    """Combina todas las reglas de visibilidad sobre una respuesta."""
    if user is None:
        return False

    # admin / creator
    if user.user_type in (UserType.admin, UserType.creator):
        return True

    response = db.query(Response.user_id).filter(Response.id == response_id).first()
    if response is None:
        return False

    # dueño
    if response.user_id == user.id:
        return True

    # aprobador asignado a esta respuesta
    is_approver = (
        db.query(ResponseApproval.id)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.user_id == user.id,
        )
        .first()
        is not None
    )
    if is_approver:
        return True

    # consultor
    return can_consultant_view_response(user.id, response_id, db)
