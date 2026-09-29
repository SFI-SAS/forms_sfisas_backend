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

from sqlalchemy import and_, exists, func, or_, true
from sqlalchemy.orm import Session

from app.models import (
    Answer,
    ConsultantAssignment,
    ConsultantScope,
    Form,
    FormModerators,
    Response,
    ResponseApproval,
    User,
    UserType,
)


def can_user_manage_form(user: User, form_id: int, db: Session) -> bool:
    """True si el usuario puede gestionar (ver todo / editar) un formato.

    Reglas:
      - admin / creator → siempre (rol de gestión, igual que los endpoints
        protegidos con require_roles([admin, creator]))
      - dueño del formato (Form.user_id) → sí
      - moderador asignado (FormModerators) → sí
      - cualquier otro (incluido rol `user`) → no

    Centraliza el control de acceso a nivel de formato para no reimplementar la
    regla en cada endpoint (IDOR).
    """
    if user is None:
        return False

    if user.user_type in (UserType.admin, UserType.creator):
        return True

    form = db.query(Form.user_id).filter(Form.id == form_id).first()
    if form is None:
        return False

    if form.user_id == user.id:
        return True

    is_moderator = (
        db.query(FormModerators.id)
        .filter(
            FormModerators.form_id == form_id,
            FormModerators.user_id == user.id,
        )
        .first()
        is not None
    )
    return is_moderator


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
        cond = None
        if a.scope == ConsultantScope.form and a.form_id:
            cond = Response.form_id == a.form_id
        elif a.scope == ConsultantScope.user and a.target_user_id:
            cond = Response.user_id == a.target_user_id
        elif a.scope == ConsultantScope.form_user and a.form_id and a.target_user_id:
            cond = and_(Response.form_id == a.form_id, Response.user_id == a.target_user_id)
        elif a.scope == ConsultantScope.category and a.category_id:
            form_ids_subq = (
                db.query(Form.id).filter(Form.id_category == a.category_id).subquery()
            )
            cond = Response.form_id.in_(form_ids_subq)
        elif a.scope == ConsultantScope.answer and a.filter_value:
            # Por VALOR, venga del formato que venga: "todo lo que tenga
            # respondido PORCE III". No lleva pregunta: se mira en cualquier
            # campo. La condición la pone el bloque de abajo, que es el mismo
            # que usa el acotado por formato.
            cond = true()

        if cond is None:
            continue

        # Acotado por la respuesta de una pregunta tipo lista.
        #
        # Es un EXISTS y no un JOIN a propósito: un JOIN duplicaría la respuesta
        # cuando la pregunta está dentro de un repetidor y aparece en varias
        # filas. Con EXISTS basta con que UNA de sus respuestas valga.
        #
        # Se compara sin distinguir mayúsculas ni espacios de los bordes, que es
        # como se comparan las respuestas en el resto del sistema: el valor se
        # guardó al diligenciar y el que se escogió al configurar salió de esa
        # misma tabla, pero pueden diferir en un espacio.
        if a.filter_value:
            partes = [
                Answer.response_id == Response.id,
                # La MISMA expresión que indexa `ix_answers_valor_normalizado`.
                # Si se cambia aquí, hay que cambiar el índice o se vuelve a
                # recorrer la tabla entera.
                func.lower(func.trim(Answer.answer_text))
                == a.filter_value.strip().lower(),
            ]
            # Con alcance `answer` no hay pregunta: vale cualquier campo.
            if a.filter_question_id:
                partes.append(Answer.question_id == a.filter_question_id)
            cond = and_(cond, exists().where(and_(*partes)))

        conditions.append(cond)
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
