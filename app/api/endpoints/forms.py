from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import User, UserType
from app.crud import  check_form_data, create_form, add_questions_to_form, get_form, get_forms
from app.schemas import FormCreate, FormResponse, GetFormBase, QuestionAdd, FormBase
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
def create_form_endpoint(
    form: FormCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Solo los usuarios tipo creator pueden crear formularios
    if current_user.user_type.name != UserType.creator.name:
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
    # Solo los usuarios tipo creator pueden agregar preguntas a formularios
    if current_user.user_type.name != UserType.creator.name:
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

@router.get("/{form_id}/has-responses")
def check_form_responses(form_id: int, db: Session = Depends(get_db),    current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get form"
        )
    else:    
        return check_form_data(db, form_id)
    
    
@router.get("/emails/all-emails")
def get_all_emails(db: Session = Depends(get_db)):
    emails = db.query(User.email).all()
    return {"emails": [email[0] for email in emails]}
