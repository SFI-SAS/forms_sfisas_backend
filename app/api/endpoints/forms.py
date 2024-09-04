from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import User, UserType
from app.crud import create_form, add_questions_to_form, get_form
from app.schemas import FormCreate, FormResponse, QuestionAdd
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
def create_form_endpoint(
    form: FormCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Solo los usuarios tipo admin pueden crear formularios
    if current_user.user_type.name != UserType.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return create_form(db=db, form=form, user_id=current_user.id)

@router.post("/{form_id}/questions", response_model=FormResponse)
def add_questions_to_form_endpoint(
    form_id: int,
    questions: QuestionAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Solo los usuarios tipo admin pueden agregar preguntas a formularios
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to modify forms"
        )
    return add_questions_to_form(db, form_id, questions.question_ids)

@router.get("/{form_id}", response_model=FormResponse)
def get_form_endpoint(
    form_id: int,
    db: Session = Depends(get_db),
):
    form = get_form(db, form_id)
    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")
    return form
