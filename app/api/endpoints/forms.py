from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.database import get_db
from app.models import Answer, ApprovalStatus, Form, FormAnswer, FormApproval, FormApprovalNotification, FormSchedule, Response, ResponseApproval, User, UserType
from app.crud import  check_form_data, create_form, add_questions_to_form, create_form_schedule, create_response_approval, delete_form, fetch_completed_forms_by_user, fetch_form_questions, fetch_form_users, get_all_forms, get_all_user_responses_by_form_id, get_form, get_form_responses_data, get_form_with_full_responses, get_forms, get_forms_by_user, get_forms_pending_approval_for_user, get_moderated_forms_by_answers, get_notifications_for_form, get_questions_and_answers_by_form_id, get_questions_and_answers_by_form_id_and_user, get_response_approval_status, get_unanswered_forms_by_user, get_user_responses_data, link_moderator_to_form, link_question_to_form, remove_moderator_from_form, remove_question_from_form, save_form_approvals, update_form_design_service, update_notification_status, update_response_approval_status
from app.schemas import BulkUpdateFormApprovals, FormAnswerCreate, FormApprovalCreateSchema, FormBaseUser, FormCreate, FormDesignUpdate, FormResponse, FormScheduleCreate, FormScheduleOut, FormSchema, FormWithApproversResponse, FormWithResponsesSchema, GetFormBase, NotificationCreate, NotificationsByFormResponse_schema, QuestionAdd, FormBase, ResponseApprovalCreate, UpdateNotifyOnSchema, UpdateResponseApprovalRequest
from app.core.security import get_current_user
from io import BytesIO
import pandas as pd
from fastapi.responses import StreamingResponse


router = APIRouter()

MAX_APPROVALS_PER_FORM = 15

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

@router.get("/{form_id}")
def get_form_endpoint(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):   
    form = get_form(db, form_id, current_user.id)
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
        frequency_type=schedule_data.frequency_type,
        repeat_days=schedule_data.repeat_days,
        interval_days=schedule_data.interval_days,
        specific_date=schedule_data.specific_date,
        status=schedule_data.status
    )
    
@router.get("/responses/")
def get_responses_with_answers(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    stmt = (
        select(Response)
        .where(Response.form_id == form_id, Response.user_id == current_user.id)
        .options(
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.approvals).joinedload(ResponseApproval.user)
        )
    )


    responses = db.execute(stmt).unique().scalars().all()

    if not responses:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    result = []
    for r in responses:
        approval_result = get_response_approval_status(r.approvals)

        result.append({
            "response_id": r.id,
            "submitted_at": r.submitted_at,
            "approval_status": approval_result["status"],
            "message": approval_result["message"],
            "answers": [
                {
                    "question_id": a.question.id,
                    "question_text": a.question.question_text,
                    "question_type": a.question.question_type,
                    "answer_text": a.answer_text,
                    "file_path": a.file_path
                }
                for a in r.answers
            ],
            "approvals": [
                {
                    "approval_id": ap.id,
                    "sequence_number": ap.sequence_number,
                    "is_mandatory": ap.is_mandatory,
                    "status": ap.status.value,
                    "reviewed_at": ap.reviewed_at,
                    "message": ap.message,
                    "user": {
                        "id": ap.user.id,
                        "name": ap.user.name,
                        "email": ap.user.email,
                        "nickname": ap.user.nickname,
                        "num_document": ap.user.num_document
                    }
                }
                for ap in r.approvals
            ]
        })

    return result



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
def create_form_answer(payload: FormAnswerCreate, db: Session = Depends(get_db)):
    form_answer = FormAnswer(
        form_id=payload.form_id,
        question_id=payload.question_id,
        is_repeated=payload.is_repeated
    )
    db.add(form_answer)
    db.commit()
    db.refresh(form_answer)
    return {
        "message": "FormAnswer created successfully",
        "data": {
            "id": form_answer.id,
            "form_id": form_answer.form_id,
            "question_id": form_answer.question_id,
            "is_repeated": form_answer.is_repeated
        }
    }

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
                                                                                                                                                                                                                                                                             
                      
@router.get("/{form_id}/responses_data_forms")
def get_form_responses(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    data = get_form_responses_data(form_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    return data                                                                              

@router.get("/{user_id}/responses_data_users")
def get_user_responses(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    data = get_user_responses_data(user_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="User or responses not found")
    return data


@router.get("/{form_id}/questions-answers/excel/user/{id_user}")
def download_user_responses_excel(
    form_id: int,
    id_user: int,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    data = get_questions_and_answers_by_form_id_and_user(db, form_id, id_user)
    
    if not data or not data["data"]:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron respuestas para este usuario en el formulario"
        )

    df = pd.DataFrame(data["data"])
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name="Respuestas del Usuario")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=Respuestas_usuario_{id_user}_formulario_{form_id}.xlsx"
        }
    )

@router.get("/form-schedules_table/", response_model=List[FormScheduleOut], )
def get_form_schedules(form_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    else:
        schedules = db.query(FormSchedule).filter(
            FormSchedule.form_id == form_id,
            FormSchedule.user_id == user_id
        ).all()

        if not schedules:
            raise HTTPException(status_code=404, detail="No se encontraron programaciones para ese formulario y usuario.")

        return schedules
    
@router.get("/{form_id}/questions-answers/excel/all-users")
def download_all_user_responses_excel(
    form_id: int,
    db: Session = Depends(get_db)
):
    data = get_all_user_responses_by_form_id(db, form_id)
    
    if not data or not data["data"]:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron respuestas para este formulario"
        )

    df = pd.DataFrame(data["data"])
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name="Respuestas de Usuarios")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=Respuestas_formulario_{form_id}_usuarios.xlsx"
        }
    )


@router.get("/users/unanswered_forms")
def get_unanswered_forms(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    try:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get forms"
            )

        forms = get_unanswered_forms_by_user(db, current_user.id)

        if not forms:
            raise HTTPException(status_code=404, detail="No hay formularios sin responder para este usuario")

        return forms

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.get("/responses/by-user/")
def get_responses_by_user_and_form(
    form_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene todas las Responses junto con sus Answers basado en form_id y user_id específicos.
    Requiere permisos de administrador o autorización adecuada.
    """
    # Verifica permisos si es necesario, por ejemplo, que sea admin
    if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get forms"
            )


    stmt = (
        select(Response)
        .where(Response.form_id == form_id, Response.user_id == user_id)
        .options(
            joinedload(Response.answers).joinedload(Answer.question)
        )
    )

    results = db.execute(stmt).unique().scalars().all()

    if not results:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    return results




@router.post("/form-approvals/create")
def create_form_approvals(
    data: FormApprovalCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )
    new_ids = save_form_approvals(data, db)
    return {"new_user_ids": new_ids}


@router.post("/create/response_approval_endpoint", status_code=status.HTTP_201_CREATED)
def create_response_approval_endpoint(
    data: ResponseApprovalCreate,
    db: Session = Depends(get_db)
):
    try:
        return create_response_approval(db, data)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    

@router.get("/user/assigned-forms-with-responses")
def get_forms_to_approve( db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_forms_pending_approval_for_user(current_user.id, db)



@router.post("/create_notification")
def create_notification(notification: NotificationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get forms"
        )
    # Verifica si ya existe una notificación similar (opcional)
    existing = db.query(FormApprovalNotification).filter_by(
        form_id=notification.form_id,
        user_id=notification.user_id,
        notify_on=notification.notify_on
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Esta notificación ya existe.")

    new_notification = FormApprovalNotification(
        form_id=notification.form_id,
        user_id=notification.user_id,
        notify_on=notification.notify_on
    )
    db.add(new_notification)
    db.commit()
    db.refresh(new_notification)
    return {"message": "Notificación creada correctamente", "id": new_notification.id}



@router.put("/update-response-approval/{response_id}")
def update_response_approval(
    response_id: int,
    update_data: UpdateResponseApprovalRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    try:
        print("Datos recibidos:", update_data)
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get options"
            )
        updated_response_approval = update_response_approval_status(
            response_id=response_id,
            user_id=current_user.id,
            update_data=update_data,
            db=db
        )
        return {"message": "ResponseApproval updated successfully", "response_approval": updated_response_approval}
    except HTTPException as e:
        raise e

    
@router.get("/form-details/{form_id}")
def get_form_details(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        result = get_form_with_full_responses(form_id, db)

        if not result:
            raise HTTPException(status_code=404, detail="Formulario no encontrado")

        return result
    
    
@router.put("/{form_id}/design", status_code=200)
def update_form_design(
    form_id: int,
    payload: FormDesignUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        updated_form = update_form_design_service(db, form_id, payload.form_design)
        return {
            "message": "Form design updated successfully",
            "form_id": updated_form.id
        }


@router.get("/get_form_with_approvers/{form_id}/with-approvers", response_model=FormWithApproversResponse)
def get_form_with_approvers(
    form_id: int,
    db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        form = db.query(Form).filter(Form.id == form_id).first()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found")

        # Solo autorizadores activos
        approvals = (
            db.query(FormApproval)
            .filter(FormApproval.form_id == form_id, FormApproval.is_active == True)
            .join(FormApproval.user)
            .all()
        )

        form_data = {
            "id": form.id,
            "title": form.title,
            "description": form.description,
            "format_type": form.format_type.value,
            "form_design": form.form_design,
            "approvers": approvals
        }

        return form_data



@router.put("/form-approvals/bulk-update")
def bulk_update_form_approvals(data: BulkUpdateFormApprovals, db: Session = Depends(get_db)):
    for update in data.updates:
        existing = db.query(FormApproval).filter(FormApproval.id == update.id, FormApproval.is_active == True).first()
        if not existing:
            raise HTTPException(status_code=404, detail=f"FormApproval with id {update.id} not found")

        user_changed = existing.user_id != update.user_id
        seq_changed = existing.sequence_number != update.sequence_number
        mandatory_changed = existing.is_mandatory != update.is_mandatory

        if user_changed or seq_changed or mandatory_changed:
            # Desactivar el actual
            existing.is_active = False

            # Crear el nuevo FormApproval
            new_approval = FormApproval(
                form_id=existing.form_id,
                user_id=update.user_id,
                sequence_number=update.sequence_number or existing.sequence_number,
                is_mandatory=update.is_mandatory if update.is_mandatory is not None else existing.is_mandatory,
                deadline_days=update.deadline_days if update.deadline_days is not None else existing.deadline_days,
                is_active=True
            )
            db.add(new_approval)

            # Actualizar ResponseApproval
            pending_responses = (
                db.query(ResponseApproval)
                .join(Response)
                .filter(
                    Response.form_id == existing.form_id,
                    ResponseApproval.user_id == existing.user_id,
                    ResponseApproval.sequence_number == existing.sequence_number,
                    ResponseApproval.status == ApprovalStatus.pendiente
                )
                .all()
            )

            for ra in pending_responses:
                ra.user_id = update.user_id
                ra.sequence_number = update.sequence_number
                ra.is_mandatory = update.is_mandatory

        else:
            # Si no hubo cambio crítico, solo actualiza campos simples
            if update.sequence_number is not None:
                existing.sequence_number = update.sequence_number
            if update.is_mandatory is not None:
                existing.is_mandatory = update.is_mandatory
            if update.deadline_days is not None:
                existing.deadline_days = update.deadline_days

    db.commit()
    return {"message": "FormApprovals updated successfully"}


@router.put("/form-approvals/{id}/set-not-is_active")
def set_is_active_false(id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Buscar el FormApproval por ID
    
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        form_approval = db.query(FormApproval).filter(FormApproval.id == id).first()
        
        if not form_approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FormApproval no encontrado")
        

        form_approval.is_active = False
        db.commit()  # Confirmar la transacción
        db.refresh(form_approval)  # Refrescar el objeto para obtener los datos actualizados
        
        return {"message": "is_mandatory actualizado a False", "form_approval": form_approval}


@router.get("/{form_id}/notifications", response_model=NotificationsByFormResponse_schema)
def get_notifications_by_form(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Llamamos a la función para obtener las notificaciones
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        notifications = get_notifications_for_form(form_id, db)

        # Preparamos la respuesta con las notificaciones
        return NotificationsByFormResponse_schema(
            form_id=form_id,
            notifications=notifications
        )
        
@router.put("/notifications/update-status/{notification_id}", response_model=UpdateNotifyOnSchema)
def update_notify_status_endpoint(notification_id: int, request: UpdateNotifyOnSchema, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Endpoint para actualizar el valor de 'notify_on' de una notificación.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        return update_notification_status(notification_id, request.notify_on, db)
    

@router.delete("/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: int, db: Session = Depends(get_db),  current_user: User = Depends(get_current_user)):
    # Buscar la notificación por ID
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        notification = db.query(FormApprovalNotification).filter(FormApprovalNotification.id == notification_id).first()

        if not notification:
            # Si no existe, lanzar un error 404
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificación no encontrada")
        
        # Eliminar la notificación
        db.delete(notification)
        db.commit()

        return {"message": "Notificación eliminada correctamente"}
    

@router.delete("/forms/{form_id}")
def delete_form_endpoint(form_id: int, db: Session = Depends(get_db)):
    """
    Endpoint para eliminar un formulario.
    """
    return delete_form(db, form_id)