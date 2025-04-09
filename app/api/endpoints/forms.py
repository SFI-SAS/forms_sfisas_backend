from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.database import get_db
from app.models import Answer, Response, User, UserType
from app.crud import  check_form_data, create_form, add_questions_to_form, create_form_schedule, fetch_completed_forms_by_user, fetch_form_questions, fetch_form_users, get_all_forms, get_form, get_forms, get_forms_by_user, get_moderated_forms_by_answers, get_questions_and_answers_by_form_id, get_questions_and_answers_by_form_id_and_user, link_moderator_to_form, link_question_to_form, remove_moderator_from_form, remove_question_from_form, save_form_answers
from app.schemas import FormAnswerCreate, FormBaseUser, FormCreate, FormResponse, FormScheduleCreate, FormSchema, GetFormBase, QuestionAdd, FormBase
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

@router.get("/users/form_by_user")
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
      
# @router.get("/users/form_by_user")
# def get_user_forms( db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):

#     if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="User does not have permission to access responses"
#         )

#     stmt = (
#         select(Response)
#         .where(Response.user_id == current_user.id)
#         .options(
#             joinedload(Response.form),  # 🔥 Carga el Form asociado
#             joinedload(Response.answers).joinedload(Answer.question)
#         )
#     )

#     results = db.execute(stmt).unique().scalars().all()

#     # 🔥 Filtrar solo preguntas con default=True y sus respuestas
#     for response in results:
#         response.answers = [answer for answer in response.answers if answer.question.default]

#     if not results:
#         raise HTTPException(status_code=404, detail="No se encontraron respuestas")

#     return results  


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
    
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )

    return fetch_form_questions(form_id, db)



@router.post("/{form_id}/questions/{question_id}")
def add_question_to_form(form_id: int, question_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return link_question_to_form(form_id, question_id, db)

@router.get("/{form_id}/users_associated_and_unassociated")
def get_form_users(form_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user) ):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return fetch_form_users(form_id, db)

@router.post("/{form_id}/form_moderators/{user_id}")
def add_user_to_form_schedule(form_id: int, user_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return link_moderator_to_form(form_id, user_id, db)


@router.delete("/{form_id}/questions/{question_id}/delete")
def delete_question_from_form(form_id: int, question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return remove_question_from_form(form_id, question_id, db)

@router.delete("/{form_id}/moderators/{user_id}/delete")
def delete_moderator_from_form(form_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return remove_moderator_from_form(form_id, user_id, db)


@router.post("/form-answers/")
def create_form_answer(form_answer: FormAnswerCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    saved_form_answer = save_form_answers(db, form_answer.form_id, form_answer.answer_ids)

    return {"message": "Form answer saved successfully", "form_answer": saved_form_answer}


@router.post("/forms-by-answers/", response_model=List[FormResponse])
def get_forms_by_answers(
    answer_ids: List[int], 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """
    Endpoint que obtiene los formularios asociados a respuestas y verifica si el usuario es moderador de ellos.
    """
    forms = get_moderated_forms_by_answers(answer_ids, current_user.id, db)
    return forms

from io import BytesIO
import pandas as pd
from fastapi.responses import StreamingResponse


@router.get("/{form_id}/questions-answers/excel")
def download_questions_answers_excel(form_id: int, db: Session = Depends(get_db)):
    data = get_questions_and_answers_by_form_id(db, form_id)
    if not data:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    df = pd.DataFrame(data["data"])
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name="Respuestas")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Formulario_{form_id}_respuestas.xlsx"}
    )
                                                                                                         
@router.get("/{form_id}/questions-answers/excel/user")
def download_user_responses_excel(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = get_questions_and_answers_by_form_id_and_user(db, form_id, current_user.id)
    if not data or not data["data"]:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas para este usuario en el formulario")

    df = pd.DataFrame(data["data"])
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name="Respuestas del Usuario")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Respuestas_usuario_{current_user.id}_formulario_{form_id}.xlsx"}
    )
                                                                                                      
                                                                                                         
                                                                                                                                                                                 
                                                                                                    