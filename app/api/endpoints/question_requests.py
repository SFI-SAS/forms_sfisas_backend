import unicodedata
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from app.database import get_db
from app.models import Form, Question, QuestionRequest, QuestionRequestField, User, UserType
from app.core.security import get_current_user

router = APIRouter()


# ── Utilidades ───────────────────────────────────────────────────────────────

def _generate_format_abbreviation(title: str) -> str:
    normalized = unicodedata.normalize('NFD', title)
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
    normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())
    normalized = normalized.strip().lower()
    words = normalized.split()
    if not words:
        return ''
    if len(words) == 1:
        return words[0][:5]
    return ''.join(w[0] for w in words)[:5]


def _build_final_question_text(original_text: str, form_id: int | None) -> str:
    """Construye el nombre final usando el ID del formato como prefijo unico."""
    if not form_id:
        return original_text
    return f"{form_id}_{original_text}"


def _find_duplicate_question(db: Session, text: str, exclude_id: int | None = None):
    def _norm(t: str) -> str:
        if not t:
            return ""
        t2 = unicodedata.normalize("NFKD", t)
        t2 = "".join(c for c in t2 if not unicodedata.combining(c))
        return " ".join(t2.lower().split())
    norm = _norm(text)
    if not norm:
        return None
    q = db.query(Question.id, Question.question_text)
    if exclude_id is not None:
        q = q.filter(Question.id != exclude_id)
    for qid, qtext in q.all():
        if _norm(qtext) == norm:
            return (qid, qtext)
    return None


# ── Schemas ──────────────────────────────────────────────────────────────────

class FieldCreate(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=255)
    question_type: str = "text"
    description: Optional[str] = None
    required: bool = True
    id_category: Optional[int] = None
    id_alias: Optional[int] = None


class BulkQuestionRequestCreate(BaseModel):
    form_id: int
    fields: List[FieldCreate] = Field(..., min_length=1)
    requester_message: Optional[str] = None


class FieldApproveOverrides(BaseModel):
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    description: Optional[str] = None
    required: Optional[bool] = None
    id_category: Optional[int] = None
    id_alias: Optional[int] = None


class FieldReject(BaseModel):
    rejection_reason: Optional[str] = None


class MarkApprovedPayload(BaseModel):
    created_question_id: int


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_question_request(
    payload: BulkQuestionRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crea solicitud con uno o mas campos."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")

    form = db.query(Form).filter(Form.id == payload.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    req = QuestionRequest(
        requester_id=current_user.id,
        form_id=payload.form_id,
        question_text=payload.fields[0].question_text,
        question_type=payload.fields[0].question_type,
        requester_message=payload.requester_message,
        status='pending',
    )
    db.add(req)
    db.flush()

    for f in payload.fields:
        field = QuestionRequestField(
            request_id=req.id,
            question_text=f.question_text,
            question_type=f.question_type,
            description=f.description,
            required=f.required,
            id_category=f.id_category,
            id_alias=f.id_alias,
            status='pending',
        )
        db.add(field)

    db.commit()
    db.refresh(req)

    return {
        "id": req.id,
        "status": req.status,
        "fields_count": len(payload.fields),
        "message": "Solicitud enviada correctamente",
    }


@router.get("/pending/count")
def get_pending_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cantidad de solicitudes con campos pendientes (para la campana)."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")

    count = (
        db.query(QuestionRequest.id)
        .join(QuestionRequestField)
        .filter(QuestionRequestField.status == 'pending')
        .distinct()
        .count()
    )
    return {"count": count}


@router.get("/pending")
def get_pending_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista de solicitudes con campos pendientes."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")
    if current_user.user_type not in (UserType.admin,):
        raise HTTPException(status_code=403, detail="Solo administradores")

    requests = (
        db.query(QuestionRequest)
        .options(
            joinedload(QuestionRequest.requester),
            joinedload(QuestionRequest.form),
            joinedload(QuestionRequest.fields).joinedload(QuestionRequestField.category),
        )
        .join(QuestionRequestField)
        .filter(QuestionRequestField.status == 'pending')
        .distinct()
        .order_by(QuestionRequest.created_at.desc())
        .all()
    )

    result = []
    for r in requests:
        pending_fields = [f for f in r.fields if f.status == 'pending']
        result.append({
            "id": r.id,
            "requester_message": r.requester_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "requester": {
                "id": r.requester.id,
                "name": r.requester.name,
                "email": r.requester.email,
                "user_type": r.requester.user_type.value if r.requester.user_type else None,
            } if r.requester else None,
            "form": {
                "id": r.form.id,
                "title": r.form.title,
            } if r.form else None,
            "fields_total": len(r.fields),
            "fields_pending": len(pending_fields),
            "fields": [
                {
                    "id": f.id,
                    "question_text": f.question_text,
                    "question_type": f.question_type,
                    "description": f.description,
                    "required": f.required,
                    "id_category": f.id_category,
                    "id_alias": f.id_alias,
                    "status": f.status,
                    "category": {"id": f.category.id, "name": f.category.name} if f.category else None,
                }
                for f in r.fields
            ],
        })

    return result


@router.get("/my-requests")
def get_my_requests(
    form_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Solicitudes del usuario con campos y estados."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")

    q = (
        db.query(QuestionRequest)
        .options(
            joinedload(QuestionRequest.form),
            joinedload(QuestionRequest.fields),
        )
        .filter(QuestionRequest.requester_id == current_user.id)
    )
    if form_id is not None:
        q = q.filter(QuestionRequest.form_id == form_id)

    requests = q.order_by(QuestionRequest.created_at.desc()).all()

    return [
        {
            "id": r.id,
            "requester_message": r.requester_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "form": {"id": r.form.id, "title": r.form.title} if r.form else None,
            "fields": [
                {
                    "id": f.id,
                    "question_text": f.question_text,
                    "question_type": f.question_type,
                    "status": f.status,
                    "rejection_reason": f.rejection_reason,
                    "created_question_id": f.created_question_id,
                }
                for f in r.fields
            ],
        }
        for r in requests
    ]


@router.post("/fields/{field_id}/approve")
def approve_field(
    field_id: int,
    overrides: FieldApproveOverrides = FieldApproveOverrides(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin aprueba un campo individual y crea la Question."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")
    if current_user.user_type not in (UserType.admin,):
        raise HTTPException(status_code=403, detail="Solo administradores")

    field = (
        db.query(QuestionRequestField)
        .options(joinedload(QuestionRequestField.request))
        .filter(QuestionRequestField.id == field_id)
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    if field.status != 'pending':
        raise HTTPException(status_code=400, detail=f"Este campo ya fue {field.status}")

    final_text = overrides.question_text or field.question_text
    final_type = overrides.question_type or field.question_type
    final_desc = overrides.description if overrides.description is not None else field.description
    final_required = overrides.required if overrides.required is not None else field.required
    final_category = overrides.id_category if overrides.id_category is not None else field.id_category
    final_alias = overrides.id_alias if overrides.id_alias is not None else field.id_alias

    form = db.query(Form).filter(Form.id == field.request.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    final_question_text = _build_final_question_text(final_text, form.id)

    dup = _find_duplicate_question(db, final_question_text)
    if dup:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una pregunta con el nombre '{final_question_text}' (#{dup[0]}).",
        )

    new_question = Question(
        question_text=final_question_text,
        description=final_desc,
        question_type=final_type,
        required=final_required,
        root=False,
        id_category=final_category,
        id_alias=final_alias,
        id_form=field.request.form_id,
    )
    db.add(new_question)
    db.flush()

    field.status = 'approved'
    field.created_question_id = new_question.id
    field.reviewed_by = current_user.id
    field.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(new_question)

    return {
        "message": "Campo aprobado y pregunta creada",
        "field_id": field.id,
        "question": {
            "id": new_question.id,
            "question_text": new_question.question_text,
            "question_type": new_question.question_type,
            "id_form": new_question.id_form,
        },
    }


@router.post("/fields/{field_id}/reject")
def reject_field(
    field_id: int,
    payload: FieldReject = FieldReject(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin rechaza un campo individual."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")
    if current_user.user_type not in (UserType.admin,):
        raise HTTPException(status_code=403, detail="Solo administradores")

    field = db.query(QuestionRequestField).filter(QuestionRequestField.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    if field.status != 'pending':
        raise HTTPException(status_code=400, detail=f"Este campo ya fue {field.status}")

    field.status = 'rejected'
    field.rejection_reason = payload.rejection_reason
    field.reviewed_by = current_user.id
    field.reviewed_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "message": "Campo rechazado",
        "field_id": field.id,
        "status": field.status,
    }


@router.post("/fields/{field_id}/mark-approved")
def mark_field_as_approved(
    field_id: int,
    payload: MarkApprovedPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca un campo como aprobado despues de que el admin creo la pregunta manualmente."""
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autenticado")

    field = db.query(QuestionRequestField).filter(QuestionRequestField.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Campo de solicitud no encontrado")
    if field.status != 'pending':
        raise HTTPException(status_code=400, detail=f"Este campo ya fue procesado ({field.status})")

    question = db.query(Question).filter(Question.id == payload.created_question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="La pregunta creada no existe")

    field.status = 'approved'
    field.created_question_id = payload.created_question_id
    field.reviewed_by = current_user.id
    field.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(field)

    return {
        "message": "Campo marcado como aprobado",
        "field_id": field.id,
        "created_question_id": field.created_question_id,
        "status": field.status,
    }
