from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.database import get_db
from app.models import Answer, ApprovalStatus, Form, FormAnswer, FormApproval, FormApprovalNotification, FormSchedule, Response, ResponseApproval, User, UserType
from app.crud import  check_form_data, create_form, add_questions_to_form, create_form_schedule, create_response_approval, delete_form, fetch_completed_forms_by_user, fetch_form_questions, fetch_form_users, get_all_forms, get_all_user_responses_by_form_id, get_form, get_form_responses_data, get_form_with_full_responses, get_forms, get_forms_by_user, get_forms_pending_approval_for_user, get_moderated_forms_by_answers, get_next_mandatory_approver, get_notifications_for_form, get_questions_and_answers_by_form_id, get_questions_and_answers_by_form_id_and_user, get_response_approval_status, get_response_details_logic, get_unanswered_forms_by_user, get_user_responses_data, link_moderator_to_form, link_question_to_form, remove_moderator_from_form, remove_question_from_form, save_form_approvals, send_rejection_email_to_all, update_form_design_service, update_notification_status, update_response_approval_status
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
    """
    Crear un nuevo formulario.

    Este endpoint permite a los usuarios con el rol de `creator` o `admin` crear
    un nuevo formulario. Los usuarios que no tengan estos permisos recibirán
    un error HTTP 403 (Prohibido).

    Args:
        form (FormBaseUser): Los datos del formulario que se va a crear.
        db (Session): Sesión de base de datos proporcionada por la dependencia.
        current_user (User): Usuario autenticado extraído del token JWT.

    Returns:
        FormResponse: Objeto con la información del formulario creado.

    Raises:
        HTTPException: Si el usuario no tiene permisos adecuados para crear formularios.
    """
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
    """
    Agrega preguntas a un formulario existente.

    Este endpoint permite agregar una o más preguntas a un formulario específico.
    Solo los usuarios con rol `creator` o `admin` tienen permiso para realizar esta acción.

    Args:
        form_id (int): ID del formulario al cual se desean agregar las preguntas.
        questions (QuestionAdd): Objeto que contiene una lista de IDs de preguntas a agregar.
        db (Session): Sesión activa de la base de datos, inyectada por dependencia.
        current_user (User): Usuario autenticado actual, obtenido desde el token JWT.

    Returns:
        FormResponse: Objeto que representa el formulario actualizado con las nuevas preguntas.

    Raises:
        HTTPException: Error 403 si el usuario no tiene permisos suficientes para modificar el formulario.
    """
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
    """
    Obtener un formulario específico por su ID.

    Este endpoint recupera la información de un formulario asociado al usuario autenticado.
    Si el formulario no existe o no pertenece al usuario, se devuelve un error 404.

    Args:
        form_id (int): ID del formulario que se desea consultar.
        db (Session): Sesión activa de la base de datos, inyectada como dependencia.
        current_user (User): Usuario autenticado, obtenido desde el token JWT.

    Returns:
        dict: Objeto con los datos del formulario solicitado.

    Raises:
        HTTPException: Error 404 si el formulario no se encuentra o no pertenece al usuario.
    """
    form = get_form(db, form_id, current_user.id)
    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")
    return form

@router.get("/{form_id}/has-responses")
def check_form_responses(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Verifica si un formulario tiene respuestas asociadas y retorna sus datos completos.

    Este endpoint permite obtener información detallada sobre un formulario específico,
    incluyendo si tiene respuestas, las respuestas en sí, los usuarios que respondieron
    y las preguntas con sus respectivas respuestas. Solo los usuarios autenticados
    pueden acceder a esta información.

    Args:
        form_id (int): ID del formulario a consultar.
        db (Session): Sesión de la base de datos SQLAlchemy, proporcionada automáticamente.
        current_user (User): Usuario autenticado, inyectado desde el token de sesión.

    Returns:
        dict: Objeto con los datos del formulario, su creador, proyecto, preguntas y respuestas.

    Raises:
        HTTPException: 
            - 403 si el usuario no está autenticado.
            - 404 si el formulario no existe.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get form"
        )
    else:    
        return check_form_data(db, form_id)
    
    
@router.get("/emails/all-emails")
def get_all_emails(db: Session = Depends(get_db)):
    """
    Obtiene todos los correos electrónicos de los usuarios registrados.

    Este endpoint recupera todos los correos electrónicos de los usuarios en la base de datos
    y los devuelve como una lista. No requiere autenticación, pero dependiendo del caso de uso
    se recomienda proteger este endpoint para evitar exposición de datos sensibles.

    Args:
        db (Session): Sesión de la base de datos, inyectada automáticamente por FastAPI.

    Returns:
        dict: Un diccionario con la clave `"emails"` que contiene una lista de correos electrónicos.

    Ejemplo de respuesta:
    {
        "emails": [
            "usuario1@example.com",
            "usuario2@example.com",
            ...
        ]
    }
    """
    emails = db.query(User.email).all()
    return {"emails": [email[0] for email in emails]}




@router.post("/form_schedules/")
def register_form_schedule(schedule_data: FormScheduleCreate, db: Session = Depends(get_db)):
    """
    Registra o actualiza la programación de un formulario.

    Este endpoint permite crear o actualizar la programación automática de envío o visualización 
    de un formulario para un usuario específico. Si ya existe una programación con la misma 
    combinación de `form_id` y `user_id`, se actualizará con los nuevos valores. De lo contrario, 
    se creará un nuevo registro.

    Args:
        schedule_data (FormScheduleCreate): Datos para registrar o actualizar la programación del formulario.
        db (Session): Sesión de base de datos proporcionada por FastAPI.

    Returns:
        FormSchedule: Objeto de programación recién creado o actualizado.

    """
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
    """
    Obtiene todas las respuestas completadas por el usuario autenticado para un formulario específico,
    incluyendo sus respuestas, aprobaciones y estado de revisión.

    Args:
        form_id (int): ID del formulario del cual se desean obtener las respuestas.
        db (Session): Sesión activa de la base de datos.
        current_user (User): Usuario autenticado.

    Returns:
        List[dict]: Lista de respuestas con sus respectivos detalles de aprobación y respuestas a preguntas.

    Raises:
        HTTPException: 403 si no hay un usuario autenticado.
        HTTPException: 404 si no se encuentran respuestas.
    """
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
    """
    Retorna una lista de todos los formularios registrados en la base de datos.

    - **Retorna**: Lista de diccionarios con la información de cada formulario.
    - **Código 200**: Éxito, formularios encontrados.
    - **Código 404**: No se encontraron formularios.
    - **Código 500**: Error interno del servidor.
    """
    try:
        forms = get_all_forms(db)
        if not forms:
            raise HTTPException(status_code=404, detail="No se encontraron formularios")
        return forms
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/form_by_user")
def get_user_forms( db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Retorna los formularios asignados al usuario autenticado.

    - **Requiere autenticación.**
    - **Código 200**: Lista de formularios.
    - **Código 403**: Usuario sin permisos (no autenticado).
    - **Código 404**: No se encontraron formularios asignados.
    - **Código 500**: Error interno del servidor.
    """
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
    """
    Retorna los formularios que han sido completados por el usuario autenticado.

    - **Autenticación requerida**
    - **Código 200**: Lista de formularios completados
    - **Código 403**: Usuario no autenticado o sin permisos
    - **Código 404**: No se encontraron formularios completados
    """
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
    """
    Endpoint para obtener las preguntas asociadas y no asociadas a un formulario dado su ID.

    Solo los usuarios con tipo 'creator' o 'admin' pueden acceder a esta funcionalidad.

    Args:
        form_id (int): ID del formulario.
        db (Session): Sesión de base de datos proporcionada por FastAPI.
        current_user (User): Usuario autenticado obtenido a través del sistema de dependencias.

    Returns:
        dict: Diccionario con dos listas: 'associated_questions' y 'unassociated_questions'.

    Raises:
        HTTPException: Si el usuario no tiene permisos o si el formulario no existe.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )

    return fetch_form_questions(form_id, db)



@router.post("/{form_id}/questions/{question_id}")
def add_question_to_form(form_id: int, question_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    """
    Asocia una pregunta existente a un formulario específico.
    Solo los usuarios con rol 'creator' o 'admin' pueden realizar esta acción.
    Args:
        form_id (int): ID del formulario.
        question_id (int): ID de la pregunta a asociar.
        db (Session): Sesión de base de datos proporcionada por FastAPI.
        current_user (User): Usuario autenticado.

    Returns:
        dict: Mensaje de éxito y ID de la relación creada.

    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return link_question_to_form(form_id, question_id, db)

@router.get("/{form_id}/users_associated_and_unassociated")
def get_form_users(form_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user) ):
    """
    Obtiene los usuarios asociados y no asociados como moderadores a un formulario.

    Solo los usuarios con rol 'creator' o 'admin' pueden acceder.

    Args:
        form_id (int): ID del formulario.
        db (Session): Sesión de base de datos proporcionada por FastAPI.
        current_user (User): Usuario autenticado.

    Returns:
        dict: Diccionario con dos listas: 'associated_users' y 'unassociated_users'.

    Raises:
        HTTPException:
            - 403: Si el usuario no tiene permisos.
            - 404: Si el formulario no existe.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return fetch_form_users(form_id, db)

@router.post("/{form_id}/form_moderators/{user_id}")
def add_user_to_form_schedule(form_id: int, user_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    """
    Asocia un usuario como moderador de un formulario.
    Solo los usuarios con rol 'creator' o 'admin' pueden acceder.
    Args:
        form_id (int): ID del formulario.
        user_id (int): ID del usuario a asociar como moderador.
        db (Session): Sesión de base de datos proporcionada por FastAPI.
        current_user (USer): Usuario autenticado.

    Returns:
        dict: Mensaje de éxito con el ID de la relación creada.
    Raises:
        HTTPException:
            - 403: Si el usuario no tiene permisos.
            - 404: Si el formulario o el usuario no existen.
            - 400: Si ya existe la relación.
    """ 
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return link_moderator_to_form(form_id, user_id, db)


@router.delete("/{form_id}/questions/{question_id}/delete")
def delete_question_from_form(form_id: int, question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Elimina la relación entre una pregunta y un formulario.

    Solo accesible para usuarios con rol 'creator' o 'admin'.

    Args:
        form_id (int): ID del formulario.
        question_id (int): ID de la pregunta a desvincular.
        db (Session): Sesión de base de datos proporcionada por FastAPI.
        current_user (User): Usuario autenticado.

    Returns:
        dict: Mensaje de éxito.
    """ 
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return remove_question_from_form(form_id, question_id, db)

@router.delete("/{form_id}/moderators/{user_id}/delete")
def delete_moderator_from_form(form_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Elimina la relación entre una pregunta y un formulario.
    Solo accesible para usuarios con rol 'creator' o 'admin'.
    Args:
        form_id (int): ID del formulario.
        question_id (int): ID de la pregunta a desvincular.
        db (Session): Sesión de base de datos proporcionada por FastAPI.
        current_user (User): Usuario autenticado.

    Returns:
        dict: Mensaje de éxito.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return remove_moderator_from_form(form_id, user_id, db)

@router.post("/form-answers/")
def create_form_answer(payload: FormAnswerCreate, db: Session = Depends(get_db)):
    """
    Crea una nueva relación entre un formulario y una pregunta en la tabla FormAnswer.
    Esta relación se usa para definir si una pregunta está repetida en un formulario.
    Args:
        payload (FormAnswerCreate): Datos requeridos para crear la relación, incluyendo:
            - form_id (int): ID del formulario.
            - question_id (int): ID de la pregunta.
            - is_repeated (bool): Indicador si la pregunta se repite.

        db (Session): Sesión de base de datos proporcionada por FastAPI.

    Returns:
        dict: Mensaje de confirmación y datos de la relación creada.
    """
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
    """
    Genera un archivo Excel con las preguntas y respuestas de un formulario específico.

    Este endpoint consulta todas las preguntas y sus respectivas respuestas
    asociadas a un formulario dado y devuelve un archivo Excel para su descarga.

    Args:
        form_id (int): ID del formulario del cual se desean exportar los datos.
        db (Session): Sesión de base de datos proporcionada por FastAPI.

    Returns:
        StreamingResponse: Archivo Excel (.xlsx) con los datos de preguntas y respuestas.
        Si el formulario no existe, retorna un error 404.
    """
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
    """
    Exporta las respuestas de un usuario a un formulario en un archivo Excel.

    Este endpoint recupera todas las respuestas dadas por el usuario autenticado
    a un formulario específico y genera un archivo Excel con la información.

    Args:
        form_id (int): ID del formulario.
        db (Session): Sesión de base de datos.
        current_user (User): Usuario autenticado (inyectado con Depends).

    Returns:
        StreamingResponse: Archivo Excel descargable con las respuestas del usuario.
    """
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
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update form design"
        )

    updated_forms = []
    updated_form = update_form_design_service(db, form_id, payload.form_design)
    return [{
        "message": "Form design updated successfully",
        "form_id": updated_form.id
    }]

    

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
def delete_form_endpoint(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Endpoint para eliminar un formulario.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return delete_form(db, form_id)

