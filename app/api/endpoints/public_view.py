"""
Endpoint publico para ver respuestas via QR del PDF.
No requiere autenticacion. Usa tokens HMAC firmados.
"""

import hashlib
import hmac
import time
import base64
import struct
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.models import Response, Form, Answer, Question
from app.core.security import SECRET_KEY

router = APIRouter()
logger = logging.getLogger(__name__)

QR_SECRET = hashlib.sha256(f"qr-view-{SECRET_KEY}".encode()).digest()
QR_TOKEN_TTL = 365 * 24 * 3600


def generate_qr_token(response_id: int) -> str:
    ts = int(time.time())
    payload = struct.pack(">II", response_id, ts)
    sig = hmac.new(QR_SECRET, payload, hashlib.sha256).digest()[:16]
    raw = payload + sig
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def verify_qr_token(token: str) -> Optional[int]:
    try:
        padded = token + "=" * (4 - len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
        if len(raw) != 24:
            return None
        payload = raw[:8]
        sig_received = raw[8:]
        sig_expected = hmac.new(QR_SECRET, payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig_received, sig_expected):
            return None
        response_id, ts = struct.unpack(">II", payload)
        if time.time() - ts > QR_TOKEN_TTL:
            return None
        return response_id
    except Exception:
        return None


@router.get("/view/{token}")
def public_view_response(token: str, db: Session = Depends(get_db)):
    response_id = verify_qr_token(token)
    if response_id is None:
        raise HTTPException(status_code=404, detail="Enlace invalido o expirado")

    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")

    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    answers = db.query(Answer).filter(Answer.response_id == response_id).all()

    answers_data = []
    for answer in answers:
        question = db.query(Question).filter(Question.id == answer.question_id).first()
        answers_data.append({
            "id": answer.id,
            "question_id": answer.question_id,
            "question_text": question.question_text if question else "Campo desconocido",
            "question_type": question.question_type.value if question and question.question_type else "text",
            "answer_value": answer.answer_text,
            "repeater_id": answer.repeated_id,
            "repeater_row": answer.repeater_row_index,
        })

    return {
        "response_id": response.id,
        "document_number": response.id,
        "submitted_at": response.submitted_at.isoformat() if response.submitted_at else None,
        "form": {
            "id": form.id,
            "title": form.title,
            "description": form.description,
        },
        "answers": answers_data,
    }


@router.get("/generate-token/{response_id}")
def generate_token_for_response(response_id: int, db: Session = Depends(get_db)):
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    token = generate_qr_token(response_id)
    return {"token": token, "response_id": response_id}
