"""
Feature #55 — Avisos emergentes configurables por el disenador.
Endpoints CRUD para FormAlert + registro de confirmaciones.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Form, FormAlert, FormAlertConfirmation, User, UserType
from app.schemas import (
    FormAlertCreate,
    FormAlertUpdate,
    FormAlertOut,
    FormAlertConfirmationCreate,
    FormAlertConfirmationOut,
    FormAlertsBulkSave,
)
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_ALERTS_PER_FORM = 5


def _require_form_owner_or_admin(
    form_id: int, current_user: User, db: Session
) -> Form:
    """Valida que el usuario sea dueno del formato o admin."""
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")
    if form.user_id != current_user.id and current_user.user_type != UserType.admin:
        raise HTTPException(status_code=403, detail="Sin permiso para este formato")
    return form


# ─────────────────────────────────────────────────────────────────────────────
# LISTAR avisos de un formato
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/forms/{form_id}/alerts",
    response_model=List[FormAlertOut],
    tags=["Form Alerts"],
)
def list_form_alerts(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve todos los avisos activos de un formato, ordenados por sort_order."""
    alerts = (
        db.query(FormAlert)
        .filter(FormAlert.form_id == form_id)
        .order_by(FormAlert.sort_order, FormAlert.id)
        .all()
    )
    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# CREAR un aviso
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/forms/{form_id}/alerts",
    response_model=FormAlertOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Form Alerts"],
)
def create_form_alert(
    form_id: int,
    payload: FormAlertCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form = _require_form_owner_or_admin(form_id, current_user, db)

    count = db.query(FormAlert).filter(FormAlert.form_id == form_id).count()
    if count >= MAX_ALERTS_PER_FORM:
        raise HTTPException(
            status_code=400,
            detail=f"Un formato puede tener maximo {MAX_ALERTS_PER_FORM} avisos",
        )

    alert = FormAlert(form_id=form_id, **payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# ─────────────────────────────────────────────────────────────────────────────
# ACTUALIZAR un aviso
# ─────────────────────────────────────────────────────────────────────────────
@router.put(
    "/alerts/{alert_id}",
    response_model=FormAlertOut,
    tags=["Form Alerts"],
)
def update_form_alert(
    alert_id: int,
    payload: FormAlertUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.query(FormAlert).filter(FormAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")

    _require_form_owner_or_admin(alert.form_id, current_user, db)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)

    db.commit()
    db.refresh(alert)
    return alert


# ─────────────────────────────────────────────────────────────────────────────
# ELIMINAR un aviso
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Form Alerts"],
)
def delete_form_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.query(FormAlert).filter(FormAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")

    _require_form_owner_or_admin(alert.form_id, current_user, db)

    db.delete(alert)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# GUARDAR EN BLOQUE (reemplaza todos los avisos del formato)
# ─────────────────────────────────────────────────────────────────────────────
@router.put(
    "/forms/{form_id}/alerts/bulk",
    response_model=List[FormAlertOut],
    tags=["Form Alerts"],
)
def bulk_save_form_alerts(
    form_id: int,
    payload: FormAlertsBulkSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reemplaza todos los avisos del formato con los enviados."""
    form = _require_form_owner_or_admin(form_id, current_user, db)

    if len(payload.alerts) > MAX_ALERTS_PER_FORM:
        raise HTTPException(
            status_code=400,
            detail=f"Un formato puede tener maximo {MAX_ALERTS_PER_FORM} avisos",
        )

    # Borrar avisos existentes
    db.query(FormAlert).filter(FormAlert.form_id == form_id).delete()

    # Crear nuevos
    new_alerts = []
    for i, alert_data in enumerate(payload.alerts):
        alert = FormAlert(
            form_id=form_id,
            sort_order=i,
            **alert_data.model_dump(exclude={"sort_order"}),
        )
        db.add(alert)
        new_alerts.append(alert)

    db.commit()
    for a in new_alerts:
        db.refresh(a)

    return new_alerts


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRAR CONFIRMACION de lectura
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/alerts/{alert_id}/confirm",
    response_model=FormAlertConfirmationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Form Alerts"],
)
def confirm_alert(
    alert_id: int,
    payload: FormAlertConfirmationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registra que el usuario leyo y confirmo un aviso. Queda como evidencia."""
    alert = db.query(FormAlert).filter(FormAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")

    confirmation = FormAlertConfirmation(
        alert_id=alert_id,
        response_id=payload.response_id,
        user_id=current_user.id,
        user_name=current_user.name,
        user_email=current_user.email,
    )
    db.add(confirmation)
    db.commit()
    db.refresh(confirmation)
    return confirmation


# ─────────────────────────────────────────────────────────────────────────────
# LISTAR CONFIRMACIONES de un aviso (para auditoria)
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/alerts/{alert_id}/confirmations",
    response_model=List[FormAlertConfirmationOut],
    tags=["Form Alerts"],
)
def list_alert_confirmations(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista todas las confirmaciones de un aviso (auditoria)."""
    confirmations = (
        db.query(FormAlertConfirmation)
        .filter(FormAlertConfirmation.alert_id == alert_id)
        .order_by(FormAlertConfirmation.confirmed_at.desc())
        .all()
    )
    return confirmations
