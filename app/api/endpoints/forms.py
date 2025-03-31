from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.database import get_db
from app.models import Answer, Response, User, UserType
from app.crud import  check_form_data, create_form, add_questions_to_form, create_form_schedule, fetch_completed_forms_by_user, fetch_form_questions, get_all_forms, get_form, get_forms, get_forms_by_user, link_question_to_form
from app.schemas import FormBaseUser, FormCreate, FormResponse, FormScheduleCreate, FormSchema, GetFormBase, QuestionAdd, FormBase
from app.core.security import get_current_user
router = APIRouter()

@router.post("/", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
def create_form_endpoint(
    form: FormBaseUser,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Solo los usuarios tipo creator pueden crear formularios
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
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
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
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
def check_form_responses(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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


@router.post("/form_schedules/")
def register_form_schedule(schedule_data: FormScheduleCreate, db: Session = Depends(get_db)):
    return create_form_schedule(
        db=db,
        form_id=schedule_data.form_id,
        user_id=schedule_data.user_id,
        repeat_days=schedule_data.repeat_days,
        status=schedule_data.status
    )
    
@router.get("/responses/")
def get_responses_with_answers(
    form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Obtiene todas las Responses junto con sus Answers basado en form_id y user_id."""

    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access responses"
        )

    stmt = (
        select(Response)
        .where(Response.form_id == form_id, Response.user_id == current_user.id)
        .options(
            joinedload(Response.answers).joinedload(Answer.question)
        )
    )
    
    # Usar .unique() para eliminar duplicados en las relaciones cargadas
    results = db.execute(stmt).unique().scalars().all()

    if not results:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    return results


@router.get("/all/list", response_model=List[dict])
def get_forms_endpoint(db: Session = Depends(get_db)):
    try:
        forms = get_all_forms(db)
        if not forms:
            raise HTTPException(status_code=404, detail="No se encontraron formularios")
        return forms
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/users/form_by_user", response_model=List[FormSchema])
def get_user_forms( db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        if current_user == None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get all questions"
            )
        else: 
            forms = get_forms_by_user(db, current_user.id)
            if not forms:
                raise HTTPException(status_code=404, detail="No se encontraron formularios para este usuario")
            return forms
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/users/completed_forms", response_model=List[FormSchema])
def get_completed_forms_for_user(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    completed_forms = fetch_completed_forms_by_user(db, current_user.id)
    if not completed_forms:
        raise HTTPException(status_code=404, detail="No completed forms found for this user")
    
    return completed_forms


@router.get("/{form_id}/questions_associated_and_unassociated")
def get_form_questions(form_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    return fetch_form_questions(form_id, db)



@router.post("/{form_id}/questions/{question_id}")
def add_question_to_form(form_id: int, question_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    return link_question_to_form(form_id, question_id, db)