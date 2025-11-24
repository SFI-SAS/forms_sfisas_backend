import logging
import os
import shutil
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from typing import Any, List, Optional
from app.database import get_db
from app.models import Answer, AnswerHistory, ApprovalStatus, Form, FormAnswer, FormApproval, FormApprovalNotification, FormCategory, FormCloseConfig, FormQuestion, FormSchedule, Question, Response, ResponseApproval, User, UserType
from app.crud import  analyze_form_relations, check_form_data, create_form, add_questions_to_form, create_form_category, create_form_schedule, create_response_approval, delete_form, delete_form_category, fetch_completed_forms_by_user, fetch_completed_forms_with_all_responses, fetch_form_questions, fetch_form_users, get_all_forms, get_all_user_responses_by_form_id, get_categories_by_parent, get_category_path, get_category_tree, get_form, get_form_responses_data, get_form_with_full_responses, get_forms, get_forms_by_approver, get_forms_by_user, get_forms_by_user_summary, get_forms_pending_approval_for_user, get_moderated_forms_by_answers, get_next_mandatory_approver, get_notifications_for_form, get_questions_and_answers_by_form_id, get_questions_and_answers_by_form_id_and_user, get_response_approval_status, get_response_details_logic, get_unanswered_forms_by_user, get_user_responses_data, link_moderator_to_form, link_question_to_form, move_category, remove_moderator_from_form, remove_question_from_form, save_form_approvals, send_rejection_email_to_all, toggle_form_status, update_form_category_1, update_form_design_service, update_notification_status, update_response_approval_status
from app.schemas import BulkUpdateFormApprovals, FormAnswerCreate, FormApprovalCreateSchema, FormBaseUser, FormCategoryCreate, FormCategoryMove, FormCategoryResponse, FormCategoryTreeResponse, FormCategoryUpdate, FormCategoryWithFormsResponse, FormCloseConfigCreate, FormCloseConfigOut, FormCreate, FormDesignUpdate, FormResponse, FormResponseBitacora, FormScheduleCreate, FormScheduleOut, FormSchema, FormStatusUpdate, FormWithApproversResponse, FormWithResponsesSchema, GetFormBase, NotificationCreate, NotificationsByFormResponse_schema, QuestionAdd, FormBase, QuestionIdsRequest, ResponseApprovalCreate, UpdateFormBasicInfo, UpdateFormCategory, UpdateNotifyOnSchema, UpdateResponseApprovalRequest
from app.core.security import get_current_user
from io import BytesIO
import pandas as pd
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse


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

@router.get("/all")
def get_all_forms_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):   
    """
    Obtener todos los formularios del usuario autenticado.

    Este endpoint recupera la información completa de todos los formularios 
    asociados al usuario autenticado, incluyendo preguntas, opciones y respuestas.

    Args:
        db (Session): Sesión activa de la base de datos, inyectada como dependencia.
        current_user (User): Usuario autenticado, obtenido desde el token JWT.

    Returns:
        list: Lista de objetos con los datos de todos los formularios del usuario.
    """
    # Obtener todos los form_ids del usuario
    user_forms = db.query(Form.id).filter(Form.user_id == current_user.id).all()
    
    if not user_forms:
        return []
    
    # Obtener los detalles completos de cada formulario
    forms_data = []
    for form_tuple in user_forms:
        form_id = form_tuple[0]
        form_detail = get_form(db, form_id, current_user.id)
        if form_detail:
            forms_data.append(form_detail)
    
    return forms_data

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
    
@router.put("/{form_id}/questions")
async def update_form_questions(
    form_id: int,
    request: QuestionIdsRequest,  # { "question_ids": [1, 2, 3] }
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualiza las relaciones de preguntas para un formulario (reemplaza las existentes)
    Útil para modo edición del formulario
    """
    try:
        # Verificar que el formulario existe
        form = db.query(Form).filter(Form.id == form_id).first()
        
        if not form:
            raise HTTPException(status_code=404, detail="Formulario no encontrado")
        
        # Eliminar todas las relaciones existentes
        db.query(FormQuestion).filter(FormQuestion.form_id == form_id).delete()
        
        # Filtrar solo las preguntas que existen
        valid_question_ids = []
        invalid_question_ids = []
        
        if request.question_ids and len(request.question_ids) > 0:
            for question_id in request.question_ids:
                # Verificar que la pregunta existe
                question = db.query(Question).filter(Question.id == question_id).first()
                
                if question:
                    # Crear la relación solo si la pregunta existe
                    form_question = FormQuestion(
                        form_id=form_id,
                        question_id=question_id
                    )
                    db.add(form_question)
                    valid_question_ids.append(question_id)
                else:
                    # Registrar las preguntas inválidas para informar al usuario
                    invalid_question_ids.append(question_id)
        
        db.commit()
        
        response = {
            "success": True,
            "message": "Preguntas actualizadas correctamente",
            "form_id": form_id,
            "valid_question_ids": valid_question_ids
        }
        
        # Informar si hubo preguntas que no se pudieron agregar
        if invalid_question_ids:
            response["warning"] = f"Las siguientes preguntas no existen y fueron omitidas: {invalid_question_ids}"
            response["invalid_question_ids"] = invalid_question_ids
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
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

import json

@router.get("/responses/")
def get_responses_with_answers(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene todas las respuestas completadas por el usuario autenticado para un formulario específico,
    incluyendo sus respuestas, aprobaciones y estado de revisión.
    Maneja el historial de respuestas para mostrar solo las más recientes.

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

    # Función auxiliar para procesar respuestas de reconocimiento facial
    def process_regisfacial_answer(answer_text, question_type):
        """
        Procesa las respuestas de tipo regisfacial para mostrar un texto descriptivo
        del registro facial guardado en lugar del JSON completo de faceData
        """
        if question_type != "regisfacial" or not answer_text:
            return answer_text
        
        try:
            # Intentar parsear el JSON
            face_data = json.loads(answer_text)
            
            # Buscar en diferentes estructuras posibles
            person_name = "Usuario"
            success = False
            
            # Estructura 1: {"faceData": {"success": true, "personName": "..."}}
            if isinstance(face_data, dict) and "faceData" in face_data:
                face_info = face_data["faceData"]
                if isinstance(face_info, dict):
                    success = face_info.get("success", False)
                    person_name = face_info.get("personName", "Usuario")
            
            # Estructura 2: directamente {"success": true, "personName": "..."}
            elif isinstance(face_data, dict):
                success = face_data.get("success", False)
                person_name = face_data.get("personName", face_data.get("person_name", "Usuario"))
            
            # Buscar también otras variantes de nombres
            if person_name == "Usuario":
                person_name = face_data.get("name", face_data.get("user_name", "Usuario"))
            
            if success:
                return f"Datos biométricos de {person_name} registrados"
            else:
                return f"Error en el registro de datos biométricos de {person_name}"
            
        except (json.JSONDecodeError, KeyError, TypeError):
            # Si hay error al parsear JSON, devolver un mensaje genérico
            return "Datos biométricos procesados"

    # Obtener todos los response_ids para buscar el historial
    response_ids = [response.id for response in responses]
    
    # Obtener historiales de respuestas
    histories = db.query(AnswerHistory).filter(AnswerHistory.response_id.in_(response_ids)).all()
    
    # Obtener todos los IDs de respuestas (previous y current) del historial
    all_answer_ids = set()
    for history in histories:
        if history.previous_answer_id:
            all_answer_ids.add(history.previous_answer_id)
        all_answer_ids.add(history.current_answer_id)
    
    # Obtener todas las respuestas del historial con sus preguntas
    historical_answers = {}
    if all_answer_ids:
        historical_answer_list = (
            db.query(Answer)
            .options(joinedload(Answer.question))
            .filter(Answer.id.in_(all_answer_ids))
            .all()
        )
        
        # Crear mapeo de answer_id -> Answer
        for answer in historical_answer_list:
            historical_answers[answer.id] = answer
    
    # Crear mapeo de current_answer_id -> history
    history_map = {}
    # Crear conjunto de previous_answer_ids para saber cuáles no mostrar individualmente
    previous_answer_ids = set()
    
    for history in histories:
        history_map[history.current_answer_id] = history
        if history.previous_answer_id:
            previous_answer_ids.add(history.previous_answer_id)

    result = []
    for r in responses:
        approval_result = get_response_approval_status(r.approvals)

        # Obtener respuestas actuales (excluyendo las que son previous_answer_ids)
        current_answers = []
        for answer in r.answers:
            # Solo incluir respuestas que no sean previous_answer_ids (es decir, las más recientes)
            if answer.id not in previous_answer_ids:
                current_answers.append(answer)

        result.append({
            "response_id": r.id,
            "status": r.status,
            "submitted_at": r.submitted_at,
            "approval_status": approval_result["status"],
            "message": approval_result["message"],
            "form": {
                "form_id": r.form.id,
                "title": r.form.title,
                "description": r.form.description,
                "format_type": r.form.format_type.value if r.form.format_type else None,
                "form_design": r.form.form_design
            },
            "answers": [
                {
                    "id_answer": a.id,
                    "repeated_id": r.repeated_id,
                    "question_id": a.question.id,
                    "question_text": a.question.question_text,
                    "question_type": a.question.question_type,
                    "answer_text": process_regisfacial_answer(a.answer_text, a.question.question_type),
                    "file_path": a.file_path,
                    # ✅ NUEVO: Incluir el UUID del elemento
                    "form_design_element_id": a.form_design_element_id
                }
                for a in current_answers
            ],
            "approvals": [
                {
                    "approval_id": ap.id,
                    "sequence_number": ap.sequence_number,
                    "is_mandatory": ap.is_mandatory,
                    "reconsideration_requested": ap.reconsideration_requested,
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


@router.get("/users/completed_forms_with_responses")
def get_completed_forms_with_responses(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Retorna los formularios completados por el usuario autenticado junto con 
    todas sus respuestas y aprobaciones en una sola llamada.
    
    Combina la información de:
    - Lista de formularios completados
    - Resumen de todas las respuestas de cada formulario con sus aprobaciones

    - **Autenticación requerida**
    - **Código 200**: Lista de formularios con sus respuestas y aprobaciones
    - **Código 403**: Usuario no autenticado o sin permisos
    - **Código 404**: No se encontraron formularios completados
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    completed_forms_data = fetch_completed_forms_with_all_responses(db, current_user.id)
    
    if not completed_forms_data:
        raise HTTPException(
            status_code=404, 
            detail="No completed forms found for this user"
        )
    
    return completed_forms_data

# Endpoint para las estadisticas resumidas de las respuestas
@router.get("/responses/summary")
def get_responses_summary(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene un resumen de las respuestas del usuario autenticado para un formulario específico.
    Solo devuelve campos básicos: información del formulario, estado de aprobación y datos mínimos.
    
    Ideal para listados rápidos donde no se necesitan las respuestas completas a las preguntas.

    Args:
        form_id (int): ID del formulario del cual se desean obtener las respuestas.
        db (Session): Sesión activa de la base de datos.
        current_user (User): Usuario autenticado.

    Returns:
        List[dict]: Lista resumida de respuestas con información básica de aprobación.

    Raises:
        HTTPException: 403 si no hay un usuario autenticado.
        HTTPException: 404 si no se encuentran respuestas.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access responses",
        )

    # Query optimizado: solo traemos lo necesario
    stmt = (
        select(Response)
        .where(Response.form_id == form_id, Response.user_id == current_user.id)
        .options(
            joinedload(Response.form).load_only(
                Form.id,
                Form.title,
                Form.description
            ),
            joinedload(Response.approvals).joinedload(ResponseApproval.user).load_only(
                User.id,
                User.name,
                User.email,
                User.nickname,
                User.num_document
            )
        )
    )

    responses = db.execute(stmt).unique().scalars().all()

    if not responses:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    result = []
    for r in responses:
        approval_result = get_response_approval_status(r.approvals)

        result.append({
            "form_id": r.form.id,
            "form_title": r.form.title,
            "form_description": r.form.description,
            "response_id": r.id,
            "submitted_at": r.submitted_at,
            "approvals": [
                {
                    "approval_id": ap.id,
                    "sequence_number": ap.sequence_number,
                    "is_mandatory": ap.is_mandatory,
                    "user": {
                        "id": ap.user.id,
                        "name": ap.user.name

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
def get_user_forms(
    page: int = 1,  # Número de página (empieza en 1)
    page_size: int = 30,  # Cantidad de registros por página
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Retorna los formularios asignados al usuario autenticado con paginación.

    - **page**: Número de página (por defecto 1)
    - **page_size**: Cantidad de registros por página (por defecto 30, máximo 100)
    - **Requiere autenticación.**
    - **Código 200**: Lista de formularios paginados.
    - **Código 403**: Usuario sin permisos.
    - **Código 404**: No se encontraron formularios.
    - **Código 500**: Error interno del servidor.
    """
    try:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get all questions"
            )
        
        # Validar page_size máximo
        if page_size > 100:
            page_size = 100
        
        # Obtener formularios paginados
        forms_data = get_forms_by_user(db, current_user.id, page, page_size)
        
        if not forms_data["items"]:
            raise HTTPException(
                status_code=404, 
                detail="No se encontraron formularios para este usuario"
            )
        
        return forms_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/form_by_user/summary")
def get_user_forms_summary(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Retorna un resumen de los formularios asignados al usuario autenticado.
    Solo devuelve campos básicos: id, title, description, created_at, user_id
    
    Ideal para listados rápidos donde no se necesita información completa.
    
    - **Requiere autenticación.**
    - **Código 200**: Lista resumida de formularios.
    - **Código 403**: Usuario sin permisos.
    - **Código 404**: No se encontraron formularios.
    - **Código 500**: Error interno del servidor.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get forms"
        )
    
    try:
        forms = get_forms_by_user_summary(db, current_user.id)
        if not forms:
            raise HTTPException(
                status_code=404, 
                detail="No se encontraron formularios para este usuario"
            )
        return forms
    except HTTPException:
        raise
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
    
    
@router.get("/{form_id}/answers/excel/all-users")
def download_questions_answers_excel_all_users(form_id: int, db: Session = Depends(get_db)):
    """
    Genera un archivo Excel con las preguntas y respuestas de un formulario específico.

    Este endpoint es idéntico al endpoint /{form_id}/questions-answers/excel
    pero con una ruta diferente para uso en emails automáticos.
    
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
        
                                                                                                                                                                                                                                                             
                      
@router.get("/{form_id}/responses_data_forms")
def get_form_responses(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Obtiene todas las respuestas asociadas a un formulario específico.

    - **form_id**: ID del formulario a consultar.
    - **current_user**: Usuario autenticado que realiza la solicitud.
    - **db**: Sesión de base de datos.

    Retorna los datos del formulario incluyendo:
    - Información del formulario.
    - Respuestas enviadas por los usuarios.
    - Información del usuario que respondió.
    - Preguntas y respuestas (texto y archivos si aplica).

    Requiere que el usuario tenga tipo `creator` o `admin`.
    """
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
    """
    Obtiene todas las respuestas asociadas a un usuario específico.

    - **user_id**: ID del usuario a consultar.
    - **current_user**: Usuario autenticado que realiza la solicitud.
    - **db**: Sesión de base de datos.

    Requiere permisos de tipo `creator` o `admin`.

    Retorna un diccionario con:
    - Información del usuario.
    - Todas las respuestas que ha enviado.
    - Información del formulario relacionado.
    - Preguntas y sus respectivas respuestas.
    """
    
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
    """
    Descarga en formato Excel las respuestas de un usuario para un formulario.

    - **form_id**: ID del formulario.
    - **id_user**: ID del usuario cuyas respuestas se desean consultar.
    - **current_user**: Usuario autenticado, debe ser tipo `creator` o `admin`.
    - **db**: Sesión de base de datos.

    Retorna un archivo Excel que contiene:
    - Información del usuario.
    - Preguntas del formulario.
    - Respuestas del usuario (incluyendo archivos si aplica).
    """
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
    """
    Devuelve las programaciones (`FormSchedule`) asociadas a un formulario y usuario específicos.

    - **form_id**: ID del formulario del cual se desea obtener las programaciones.
    - **user_id**: ID del usuario al que están asociadas las programaciones.
    - **current_user**: Usuario autenticado (verificado).
    - **db**: Sesión de base de datos proporcionada por la dependencia `get_db`.

    Retorna:
    - Lista de objetos `FormScheduleOut` que contienen la información de las programaciones.

    Errores posibles:
    - **403**: Si no hay usuario autenticado.
    - **404**: Si no se encuentran programaciones para ese formulario y usuario.
    """ 
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
    """
    Descarga un archivo Excel con las respuestas de todos los usuarios para un formulario dado.

    - **form_id**: ID del formulario.
    - **db**: Sesión de base de datos.

    Retorna un archivo Excel (`.xlsx`) con las respuestas de todos los usuarios, con columnas dinámicas según las preguntas del formulario.
    """
    data = get_all_user_responses_by_form_id(db, form_id)

    if not data or not data["data"]:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron respuestas para este formulario"
        )
    # Convertir a DataFrame
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


@router.get("/users/unanswered_forms",
    summary="Obtener formularios no respondidos",
    description="Retorna los formularios asignados al usuario autenticado que aún no han sido respondidos."
)
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

@router.post("/create/response_approval_endpoint", status_code=status.HTTP_201_CREATED)
def create_response_approval_endpoint(
    data: ResponseApprovalCreate,
    db: Session = Depends(get_db)
):
    """
    Crea un nuevo registro de aprobación de respuesta.

    Este endpoint recibe los datos necesarios para crear un registro en la tabla `ResponseApproval`
    y lo almacena en la base de datos.

    Parámetros:
    ----------
    data : ResponseApprovalCreate
        Objeto que contiene los datos requeridos para crear la aprobación.
    db : Session
        Sesión activa de la base de datos (inyectada automáticamente por FastAPI).

    Retorna:
    -------
    ResponseApproval
        Objeto creado de tipo ResponseApproval.

    Excepciones:
    -----------
    HTTPException (400):
        Si ocurre un error durante la creación del registro, se retorna una excepción con el mensaje de error.
    """
    try:
        return create_response_approval(db, data)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    

@router.get("/user/assigned-forms-with-responses")
def get_forms_to_approve( db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Obtiene los formularios asignados al usuario actual que tienen respuestas pendientes de aprobación.

    Este endpoint retorna una lista de formularios con sus respuestas correspondientes que requieren 
    la aprobación del usuario autenticado, respetando el orden de secuencia y verificando si es su turno 
    de aprobar según las reglas definidas.

    Parámetros:
    ----------
    db : Session
        Sesión activa de la base de datos (inyectada por FastAPI).
    current_user : User
        Usuario autenticado (inyectado por el sistema de autenticación).

    Retorna:
    -------
    List[Dict]
        Lista de formularios con información detallada de las respuestas, 
        aprobaciones y el estado de cada aprobador.
    """
    return get_forms_pending_approval_for_user(current_user.id, db)

@router.post("/create_notification")
def create_notification(notification: NotificationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Crea una notificación para eventos de aprobación de formularios.

    Este endpoint permite registrar una notificación que se activará cuando se cumpla la condición 
    especificada (por ejemplo, una nueva respuesta o aprobación).

    Parámetros:
    ----------
    notification : NotificationCreate
        Objeto con los datos necesarios para crear la notificación. Contiene:
        - form_id: ID del formulario al cual aplica la notificación.
        - user_id: ID del usuario que debe recibir la notificación.
        - notify_on: Evento que dispara la notificación (por ejemplo: "on_submit", "on_approval").

    db : Session
        Sesión de base de datos (inyectada por FastAPI).
    
    current_user : User
        Usuario autenticado. Se utiliza para validar si tiene permisos.

    Validaciones:
    ------------
    - Si el usuario no está autenticado, se retorna un error 403.
    - Si ya existe una notificación con los mismos datos (formulario, usuario y tipo de evento),
      se retorna un error 400 para evitar duplicados.

    Retorna:
    -------
    dict
        Mensaje de éxito con el ID de la notificación creada:
        {
            "message": "Notificación creada correctamente",
            "id": <id_notificación>
        }

    Errores:
    -------
    - 403 FORBIDDEN: Si el usuario no tiene permisos.
    - 400 BAD REQUEST: Si la notificación ya existe.
    """
    
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

 
@router.get("/form-details/{form_id}")
def get_form_details(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    """
    Retorna los detalles completos de un formulario, incluidas preguntas, respuestas y estado de aprobación.

    Este endpoint recupera:
    - Información básica del formulario (ID, título, descripción).
    - Preguntas asociadas al formulario.
    - Respuestas completas con información del usuario que respondió.
    - Historial de respuestas (si las respuestas fueron editadas).
    - Estado de aprobación por respuesta.

    Requiere autenticación.

    Parámetros:
    ----------
    form_id : int
        ID del formulario a consultar.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado (obligatorio).

    Retorna:
    -------
    dict
        Objeto con la estructura del formulario, preguntas, respuestas, aprobaciones e historial.

    Errores:
    -------
    - 403 FORBIDDEN: Si el usuario no está autenticado.
    - 404 NOT FOUND: Si el formulario no existe.
    """
    
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
    """
    Actualiza el diseño visual del formulario especificado.

    Este endpoint permite modificar el diseño personalizado de un formulario,
    reemplazando completamente su estructura `form_design` con la nueva proporcionada.

    Parámetros:
    -----------
    form_id : int
        ID del formulario a actualizar.

    payload : FormDesignUpdate
        Datos del nuevo diseño a aplicar. Contiene:
        - `form_design`: una lista de objetos/diccionarios con la estructura del diseño.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la acción.

    Retorna:
    --------
    list[dict]
        Lista con un mensaje de confirmación y el ID del formulario actualizado:
        ```json
        [
            {
                "message": "Form design updated successfully",
                "form_id": 123
            }
        ]
        ```

    Errores:
    --------
    - 403 FORBIDDEN: Si el usuario no está autenticado.
    - 404 NOT FOUND: Si el formulario no existe.
    """
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


@router.get("/{form_id}/notifications", response_model=NotificationsByFormResponse_schema)
def get_notifications_by_form(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Llamamos a la función para obtener las notificaciones
    """
    Obtiene todas las notificaciones configuradas para un formulario específico.

    Este endpoint devuelve una lista de notificaciones que han sido definidas para
    el formulario identificado por `form_id`. Cada notificación incluye información
    del tipo de notificación y del usuario al que se notificará.

    Solo usuarios autenticados pueden acceder a esta información.

    Parámetros:
    -----------
    form_id : int
        ID del formulario para el cual se desean obtener las notificaciones.

    db : Session
        Sesión activa de la base de datos proporcionada por FastAPI.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    NotificationsByFormResponse_schema
        Objeto con el ID del formulario y la lista de notificaciones asociadas.

    Lanza:
    ------
    HTTPException 403:
        Si el usuario no está autenticado o no tiene permisos para ver las notificaciones.
    
    HTTPException 404:
        Si el formulario no existe (lanzado desde la función auxiliar `get_notifications_for_form`).
    """
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
    Actualiza el tipo de notificación ('notify_on') de una notificación específica.

    Este endpoint permite cambiar el tipo de evento que desencadenará la notificación,
    como "cada_aprobacion" o "aprobacion_final", para una notificación ya existente
    asociada a un formulario.

    Requiere autenticación.

    Parámetros:
    -----------
    notification_id : int
        ID de la notificación a actualizar.

    request : UpdateNotifyOnSchema
        Objeto que contiene el nuevo valor del campo `notify_on`.

    db : Session
        Sesión activa de base de datos proporcionada por FastAPI.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    UpdateNotifyOnSchema:
        Datos actualizados de la notificación.

    Lanza:
    ------
    HTTPException 403:
        Si el usuario no está autenticado o no tiene permisos.

    HTTPException 400:
        Si el valor de `notify_on` no es válido.

    HTTPException 404:
        Si la notificación no existe.
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
    """
    Elimina una notificación específica de un formulario.

    Este endpoint permite eliminar una notificación creada previamente que
    está asociada a un formulario de aprobación. Solo usuarios autenticados
    con permisos pueden realizar esta acción.

    Parámetros:
    -----------
    notification_id : int
        ID de la notificación que se desea eliminar.

    db : Session
        Sesión activa de la base de datos proporcionada por FastAPI.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    dict:
        Mensaje de confirmación de eliminación (aunque el status sea 204).

    Lanza:
    ------
    HTTPException 403:
        Si el usuario no tiene permisos o no está autenticado.

    HTTPException 404:
        Si la notificación no existe.
    """
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

@router.get("/forms/{form_id}/relations")
def get_form_relations_endpoint(form_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Endpoint para obtener las relaciones de un formulario sin eliminarlo.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to view form relations"
        )
    
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Formulario no encontrado."
        )
    
    relations_info = analyze_form_relations(db, form_id)
    
    return relations_info


@router.post("/create_form_close_config", response_model=FormCloseConfigOut)
def create_form_close_config(config: FormCloseConfigCreate, db: Session = Depends(get_db)):
    """
    Crea una nueva configuración de cierre para un formulario
    """
    
    # Validar si ya existe una configuración para el form_id
    existing = db.query(FormCloseConfig).filter(FormCloseConfig.form_id == config.form_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe una configuración para este formulario.")
    
    # 🆕 Validar que si se selecciona una acción, haya al menos un email
    if config.send_download_link and (not config.download_link_recipients or len(config.download_link_recipients) == 0):
        raise HTTPException(status_code=400, detail="Se requiere al menos un destinatario para enviar enlace de descarga.")
    
    if config.send_pdf_attachment and (not config.email_recipients or len(config.email_recipients) == 0):
        raise HTTPException(status_code=400, detail="Se requiere al menos un destinatario para enviar PDF como adjunto.")
    
    if config.generate_report and (not config.report_recipients or len(config.report_recipients) == 0):
        raise HTTPException(status_code=400, detail="Se requiere al menos un destinatario para generar reporte.")
    
    # 🆕 Convertir listas a JSON para almacenar
    config_dict = config.dict()
    config_dict['download_link_recipients'] = json.dumps(config.download_link_recipients or [])
    config_dict['email_recipients'] = json.dumps(config.email_recipients or [])
    config_dict['report_recipients'] = json.dumps(config.report_recipients or [])
    
    new_config = FormCloseConfig(**config_dict)
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    
    return new_config


@router.get("/form_close_config/{form_id}", response_model=FormCloseConfigOut)
def get_form_close_config(form_id: int, db: Session = Depends(get_db)):
    """
    Obtiene la configuración de cierre de un formulario específico
    """
    config = db.query(FormCloseConfig).filter(FormCloseConfig.form_id == form_id).first()
    
    if not config:
        raise HTTPException(status_code=404, detail="No se encontró configuración de cierre para este formulario")
    
    return config


@router.put("/form_close_config/{form_id}", response_model=FormCloseConfigOut)
def update_form_close_config(
    form_id: int,
    config: FormCloseConfigCreate,
    db: Session = Depends(get_db)
):
    """
    Actualiza la configuración de cierre de un formulario
    """
    existing_config = db.query(FormCloseConfig).filter(FormCloseConfig.form_id == form_id).first()
    
    if not existing_config:
        raise HTTPException(status_code=404, detail="No existe configuración de cierre para este formulario")
    
    # 🆕 Validaciones con múltiples emails
    if config.send_download_link and (not config.download_link_recipients or len(config.download_link_recipients) == 0):
        raise HTTPException(status_code=400, detail="Se requiere al menos un destinatario para enviar enlace de descarga.")
    
    if config.send_pdf_attachment and (not config.email_recipients or len(config.email_recipients) == 0):
        raise HTTPException(status_code=400, detail="Se requiere al menos un destinatario para enviar PDF como adjunto.")
    
    if config.generate_report and (not config.report_recipients or len(config.report_recipients) == 0):
        raise HTTPException(status_code=400, detail="Se requiere al menos un destinatario para generar reporte.")
    
    # 🆕 Convertir listas a JSON
    config_dict = config.dict()
    config_dict['download_link_recipients'] = json.dumps(config.download_link_recipients or [])
    config_dict['email_recipients'] = json.dumps(config.email_recipients or [])
    config_dict['report_recipients'] = json.dumps(config.report_recipients or [])
    
    # Actualizar campos
    for key, value in config_dict.items():
        setattr(existing_config, key, value)
    
    db.commit()
    db.refresh(existing_config)
    
    return existing_config


@router.delete("/form_close_config/{form_id}")
def delete_form_close_config(form_id: int, db: Session = Depends(get_db)):
    """
    Elimina la configuración de cierre de un formulario
    """
    config = db.query(FormCloseConfig).filter(FormCloseConfig.form_id == form_id).first()
    
    if not config:
        raise HTTPException(status_code=404, detail="No existe configuración de cierre para este formulario")
    
    db.delete(config)
    db.commit()
    
    return {"message": "Configuración de cierre eliminada exitosamente"}

UPLOAD_FOLDER = "logo"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

# Asegurar que la carpeta exista
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@router.post("/upload-logo/")
async def upload_logo(file: UploadFile = File(...),current_user: User = Depends(get_current_user)):
    # Validar extensión
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    filename = file.filename
    extension = filename.split(".")[-1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido. Solo se permiten: png, jpg, jpeg.")

    # Elimina cualquier imagen anterior en la carpeta
    for f in os.listdir(UPLOAD_FOLDER):
        os.remove(os.path.join(UPLOAD_FOLDER, f))

    # Guardar la nueva imagen
    file_path = os.path.join(UPLOAD_FOLDER, f"logo.{extension}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return JSONResponse(content={"message": "Imagen subida correctamente", "path": file_path})


@router.get("/get-logo/")
def get_logo(current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    if not os.path.exists(UPLOAD_FOLDER):
        raise HTTPException(status_code=404, detail="No se encontró la carpeta de logo.")

    archivos = os.listdir(UPLOAD_FOLDER)
    if not archivos:
        raise HTTPException(status_code=404, detail="No hay imagen guardada.")

    # Tomar el primer archivo (solo debe haber uno)
    imagen_path = os.path.join(UPLOAD_FOLDER, archivos[0])
    return FileResponse(imagen_path, media_type="image/*", filename=archivos[0])



# Endpoint principal para obtener el logo
@router.get("/public-logo/")
def get_public_logo():
    if not os.path.exists(UPLOAD_FOLDER):
        raise HTTPException(status_code=404, detail="No se encontró la carpeta de logo.")
    
    archivos = os.listdir(UPLOAD_FOLDER)
    if not archivos:
        raise HTTPException(status_code=404, detail="No hay imagen guardada.")
    
    imagen_path = os.path.join(UPLOAD_FOLDER, archivos[0])
    
    # Verificar que el archivo realmente existe
    if not os.path.isfile(imagen_path):
        raise HTTPException(status_code=404, detail="Archivo de logo no encontrado.")
    
    extension = archivos[0].split(".")[-1].lower()
    
    # Mapeo más completo de tipos MIME
    media_type_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml"
    }
    
    media_type = media_type_map.get(extension, "image/*")
    
    # Headers para mejor manejo de cache y CORS
    headers = {
        "Cache-Control": "public, max-age=300",  # Cache por 5 minutos
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*"
    }
    
    return FileResponse(
        imagen_path, 
        media_type=media_type,
        headers=headers
    )

# Endpoint adicional para verificar existencia (opcional pero recomendado)
@router.get("/public-logo/exists")
def check_logo_exists():
    """Verifica si existe un logo sin descargar el archivo"""
    try:
        if not os.path.exists(UPLOAD_FOLDER):
            return {"exists": False, "reason": "Carpeta no existe"}
            
        archivos = os.listdir(UPLOAD_FOLDER)
        if not archivos:
            return {"exists": False, "reason": "No hay archivos"}
            
        imagen_path = os.path.join(UPLOAD_FOLDER, archivos[0])
        if not os.path.isfile(imagen_path):
            return {"exists": False, "reason": "Archivo no válido"}
            
        return {
            "exists": True, 
            "filename": archivos[0],
            "url": "/forms/public-logo/"
        }
    except Exception as e:
        return {"exists": False, "reason": f"Error: {str(e)}"}
    
# Soporte para HEAD requests
@router.head("/public-logo/")
def head_public_logo():
    """HEAD request para verificar existencia sin descargar"""
    if not os.path.exists(UPLOAD_FOLDER):
        raise HTTPException(status_code=404, detail="No se encontró la carpeta de logo.")
        
    archivos = os.listdir(UPLOAD_FOLDER)
    if not archivos:
        raise HTTPException(status_code=404, detail="No hay imagen guardada.")
        
    imagen_path = os.path.join(UPLOAD_FOLDER, archivos[0])
    if not os.path.isfile(imagen_path):
        raise HTTPException(status_code=404, detail="Archivo de logo no encontrado.")
    
    # SOLUCIÓN 1: Usar Response de FastAPI/Starlette (recomendado)
    from fastapi import Response
    return Response(status_code=200, headers={
        "Cache-Control": "public, max-age=300",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*"
    })



@router.put("/update_form_category/{form_id}/category")
def update_form_category(
    form_id: int,
    category_data: UpdateFormCategory,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar la categoría de un formulario"
        )

    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    if category_data.id_category is not None:
        category = db.query(FormCategory).filter(FormCategory.id == category_data.id_category).first()
        if not category:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")

    form.id_category = category_data.id_category
    db.commit()
    db.refresh(form)

    return {
        "message": "Categoría actualizada correctamente",
        "form_id": form.id,
        "new_category_id": form.id_category
    }
# Endpoints para categorías de formularios
@router.post("/categories/", response_model=FormCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category_endpoint(
    category: FormCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return create_form_category(db, category)

# Obtener árbol completo
@router.get("/categories/tree", response_model=List[FormCategoryTreeResponse])
def get_tree_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_category_tree(db)

# Obtener categorías de un nivel
@router.get("/categories/by-parent", response_model=List[FormCategoryResponse])
def get_by_parent_endpoint(
    parent_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    categories = get_categories_by_parent(db, parent_id)
    
    # Enriquecer con contadores
    result = []
    for cat in categories:
        forms_count = db.query(func.count(Form.id)).filter(Form.id_category == cat.id).scalar()
        cat_dict = FormCategoryResponse.from_orm(cat).dict()
        cat_dict['forms_count'] = forms_count
        cat_dict['children_count'] = len(cat.children)
        result.append(cat_dict)
    
    return result

# Obtener una categoría específica
@router.get("/categories/{category_id}", response_model=FormCategoryResponse)
def get_category_endpoint(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    category = db.query(FormCategory).filter(FormCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    forms_count = db.query(func.count(Form.id)).filter(Form.id_category == category_id).scalar()
    response = FormCategoryResponse.from_orm(category)
    response.forms_count = forms_count
    response.children_count = len(category.children)
    
    return response

# Obtener ruta/breadcrumb de una categoría
@router.get("/categories/{category_id}/path", response_model=List[FormCategoryResponse])
def get_path_endpoint(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_category_path(db, category_id)

# Actualizar categoría
@router.put("/categories/{category_id}", response_model=FormCategoryResponse)
def update_category_endpoint(
    category_id: int,
    category_update: FormCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return update_form_category_1(db, category_id, category_update)

# Mover categoría
@router.patch("/categories/{category_id}/move", response_model=FormCategoryResponse)
def move_category_endpoint(
    category_id: int,
    move_data: FormCategoryMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return move_category(db, category_id, move_data)

# Eliminar categoría
@router.delete("/categories/{category_id}")
def delete_category_endpoint(
    category_id: int,
    force: bool = Query(False, description="Eliminar incluyendo subcategorías"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return delete_form_category(db, category_id, force)

# Obtener formularios de una categoría
@router.get("/categories/{category_id}/forms", response_model=List[FormResponse])
def get_forms_by_category_endpoint(
    category_id: int,
    include_subcategories: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not include_subcategories:
        forms = db.query(Form).filter(Form.id_category == category_id).all()
    else:
        # Obtener todas las subcategorías recursivamente
        def get_all_descendant_ids(cat_id):
            ids = [cat_id]
            children = db.query(FormCategory).filter(FormCategory.parent_id == cat_id).all()
            for child in children:
                ids.extend(get_all_descendant_ids(child.id))
            return ids
        
        all_ids = get_all_descendant_ids(category_id)
        forms = db.query(Form).filter(Form.id_category.in_(all_ids)).all()
    
    return forms

@router.get("/api/forms/{form_id}/response/{response_id}/details")
async def get_response_details_json(
    form_id: int,
    response_id: int,
    db: Session = Depends(get_db)
):
    """
    Endpoint API que devuelve los detalles de una respuesta en formato JSON.
    Para ser consumido por el frontend Astro.
    No requiere autenticación.
    """
    try:
        # Obtener la respuesta específica
        stmt = (
            select(Response)
            .where(
                Response.id == response_id,
                Response.form_id == form_id
            )
            .options(
                joinedload(Response.answers).joinedload(Answer.question),
                joinedload(Response.approvals).joinedload(ResponseApproval.user),
                joinedload(Response.form),
                joinedload(Response.user)  # ✅ AGREGAR ESTA LÍNEA
            )
        )
        
        response = db.execute(stmt).unique().scalar_one_or_none()
        
        if not response:
            raise HTTPException(status_code=404, detail="Respuesta no encontrada")
        
        # Obtener el estado de aprobación
        approval_result = get_response_approval_status(response.approvals)
        
        # Procesar las aprobaciones
        processed_approvals = []
        for approval in response.approvals:
            user_info = approval.user
            processed_approvals.append({
                'approval_id': approval.id,
                'sequence_number': approval.sequence_number,
                'is_mandatory': approval.is_mandatory,
                'reconsideration_requested': approval.reconsideration_requested,
                'status': approval.status.value,
                'reviewed_at': approval.reviewed_at.isoformat() if approval.reviewed_at else None,
                'message': approval.message,
                'user': {
                    'name': user_info.name,
                    'email': user_info.email,
                    'nickname': user_info.nickname,
                    'num_document': user_info.num_document
                }
            })
        
        # Ordenar aprobaciones por sequence_number
        processed_approvals.sort(key=lambda x: x.get('sequence_number', 0))
        
        # Procesar respuestas del formulario
        form_answers = []
        for answer in response.answers:
            form_answers.append({
                'question_text': answer.question.question_text,
                'answer_text': answer.answer_text,
                'question_type': answer.question.question_type,
                'file_path': answer.file_path
            })
        
        # ✅ NUEVA SECCIÓN: Procesar información del usuario que respondió
        responded_by = None
        if response.user:
            responded_by = {
                'id': response.user.id,
                'name': response.user.name,
                'email': response.user.email,
                'nickname': response.user.nickname,
                'num_document': response.user.num_document
            }
        
        # Preparar respuesta JSON
        response_data = {
            'response_id': response.id,
            'submitted_at': response.submitted_at.isoformat() if response.submitted_at else None,
            'approval_status': approval_result["status"],
            'message': approval_result["message"],
            'responded_by': responded_by,  # ✅ AGREGAR ESTA LÍNEA
            'form': {
                'id': response.form.id,
                'title': response.form.title,
                'description': response.form.description
            },
            'approvals': processed_approvals,
            'answers': form_answers
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error al obtener detalles de respuesta: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error interno del servidor"
        )


@router.put("/forms/{form_id}/basic-info")
def update_form_basic_info(
    form_id: int,
    form_data: UpdateFormBasicInfo,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza el título, descripción y/o tipo de formato de un formulario.
    Solo el propietario del formulario puede realizar esta acción.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar este formulario"
        )

    # Buscar el formulario
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Formulario no encontrado"
        )

    # Validar que al menos un campo esté presente
    if form_data.title is None and form_data.description is None and form_data.format_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar al menos un campo para actualizar"
        )

    # Actualizar los campos proporcionados
    if form_data.title is not None:
        form.title = form_data.title
    
    if form_data.description is not None:
        form.description = form_data.description
    
    if form_data.format_type is not None:
        form.format_type = form_data.format_type

    db.commit()
    db.refresh(form)

    return {
        "message": "Información del formulario actualizada correctamente",
        "form_id": form.id,
        "title": form.title,
        "description": form.description,
        "format_type": form.format_type.value
    }


@router.patch("/forms/{form_id}/status")
def update_form_status(
    form_id: int,
    status_update: FormStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint para habilitar o deshabilitar un formulario.
    Solo usuarios con rol ADMIN pueden usar este endpoint.
    """
    # Validar que el usuario sea administrador
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can enable or disable forms"
        )
    
    return toggle_form_status(db, form_id, status_update.is_enabled)

@router.get("/by-question/{question_id}", response_model=List[FormResponseBitacora])
def get_forms_by_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Devuelve todos los formularios que contienen la pregunta con el ID especificado.
    """
    if str(current_user.user_type.value) not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para acceder a las palabras clave."
        )

    # Buscar la pregunta
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada.")

    # Acceder a los formularios relacionados (gracias a la relación many-to-many)
    forms = question.forms

    if not forms:
        raise HTTPException(status_code=404, detail="Esta pregunta no pertenece a ningún formulario.")

    return forms
