"""
rut.py - Endpoints para solicitud y gestion de RUT por formato.
"""
import os
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FormRutConfig, RutSubmission, User
from app.core.security import get_current_user
from app.api.controllers.mail import (
    _base_email_html, _p, _callout, _new_msg, _send_msg,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["RUT"])

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploaded_files")


# ── Schemas ──────────────────────────────────────────────────
class RutConfigIn(BaseModel):
    email: str


class RutConfigOut(BaseModel):
    id: int
    form_id: int
    email: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class RutSubmissionOut(BaseModel):
    id: int
    form_id: int
    user_id: int
    file_path: str
    original_filename: str | None = None
    email_sent_to: str | None = None
    email_sent: bool
    submitted_at: datetime | None = None
    user_name: str | None = None

    class Config:
        from_attributes = True


# ── 1. Configuracion de correo RUT ──────────────────────────

@router.get("/config/{form_id}", response_model=RutConfigOut | None)
def get_rut_config(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = db.query(FormRutConfig).filter(FormRutConfig.form_id == form_id).first()
    if not config:
        return None
    return config


@router.put("/config/{form_id}", response_model=RutConfigOut)
def upsert_rut_config(
    form_id: int,
    body: RutConfigIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = db.query(FormRutConfig).filter(FormRutConfig.form_id == form_id).first()
    if config:
        config.email = body.email
    else:
        config = FormRutConfig(form_id=form_id, email=body.email)
        db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.delete("/config/{form_id}")
def delete_rut_config(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = db.query(FormRutConfig).filter(FormRutConfig.form_id == form_id).first()
    if config:
        db.delete(config)
        db.commit()
    return {"ok": True}


# ── 2. Subir RUT (desde diligenciamiento) ───────────────────

@router.post("/upload/{form_id}")
async def upload_rut(
    form_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Guardar archivo
    ext = os.path.splitext(file.filename or "")[1] or ".pdf"
    unique_name = f"rut_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_name)

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Archivo excede 25 MB")

    with open(file_path, "wb") as f:
        f.write(content)

    # Buscar config de correo
    config = db.query(FormRutConfig).filter(FormRutConfig.form_id == form_id).first()
    email_sent = False
    email_target = None

    if config and config.email:
        email_target = config.email
        try:
            body_html = _p(
                f'El usuario <strong>{current_user.name}</strong> '
                f'(Doc: {current_user.num_document}) ha subido su RUT '
                f'desde el formato <strong>ID {form_id}</strong>.'
            )
            body_html += _callout(
                f'Archivo adjunto: <strong>{file.filename}</strong>', 'info'
            )
            body_html += _p(
                f'<span style="color:#9CA3AF;font-size:12px;">'
                f'Fecha: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
                f'</span>'
            )
            html = _base_email_html("Solicitud de RUT", body_html)
            msg = _new_msg(
                f"RUT recibido - {current_user.name}",
                config.email,
                "Administrador",
            )
            msg.set_content(
                f"RUT recibido de {current_user.name} - Formato {form_id}"
            )
            msg.add_alternative(html, subtype="html")

            import mimetypes
            mt, _ = mimetypes.guess_type(file.filename or "")
            main, sub = ("application", "octet-stream") if not mt else mt.split("/")
            msg.add_attachment(
                content, maintype=main, subtype=sub,
                filename=file.filename or unique_name,
            )
            email_sent = _send_msg(msg)
        except Exception as e:
            logger.warning(f"Error enviando RUT por correo: {e}")
            email_sent = False

    # Guardar en historial
    submission = RutSubmission(
        form_id=form_id,
        user_id=current_user.id,
        file_path=unique_name,
        original_filename=(file.filename or "")[:500],
        email_sent_to=email_target,
        email_sent=email_sent,
    )
    db.add(submission)
    db.commit()

    return {
        "ok": True,
        "email_sent": email_sent,
        "email_target": email_target,
        "message": (
            f"RUT enviado al correo {email_target}"
            if email_sent
            else "RUT guardado. No hay correo configurado o fallo el envio."
            if not email_target
            else "RUT guardado pero fallo el envio del correo."
        ),
    }


# ── 3. Historial de RUTs enviados ───────────────────────────

@router.get("/history/{form_id}", response_model=list[RutSubmissionOut])
def get_rut_history(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(RutSubmission, User.name.label("user_name"))
        .join(User, User.id == RutSubmission.user_id)
        .filter(RutSubmission.form_id == form_id)
        .order_by(RutSubmission.submitted_at.desc())
        .limit(100)
        .all()
    )
    result = []
    for sub, uname in rows:
        d = {
            "id": sub.id,
            "form_id": sub.form_id,
            "user_id": sub.user_id,
            "file_path": sub.file_path,
            "original_filename": sub.original_filename,
            "email_sent_to": sub.email_sent_to,
            "email_sent": sub.email_sent,
            "submitted_at": sub.submitted_at,
            "user_name": uname,
        }
        result.append(d)
    return result
