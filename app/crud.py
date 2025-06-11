from collections import defaultdict
from io import BytesIO
import json
import os
import pytz
from sqlalchemy import exists, func, not_, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from app import models
from app.api.controllers.mail import send_email_aprovall_next, send_email_daily_forms, send_email_plain_approval_status, send_email_plain_approval_status_vencidos, send_email_with_attachment, send_rejection_email, send_welcome_email
from app.core.security import hash_password
from app.models import  AnswerFileSerial, ApprovalStatus, EmailConfig, FormAnswer, FormApproval, FormApprovalNotification, FormModerators, FormSchedule, Project, QuestionFilterCondition, QuestionTableRelation, QuestionType, ResponseApproval, User, Form, Question, Option, Response, Answer, FormQuestion
from app.schemas import EmailConfigCreate, FormApprovalCreateSchema, FormBaseUser, NotificationResponse, ProjectCreate, ResponseApprovalCreate, UpdateResponseApprovalRequest, UserBase, UserBaseCreate, UserCreate, FormCreate, QuestionCreate, OptionCreate, ResponseCreate, AnswerCreate, UserType, UserUpdate, QuestionUpdate, UserUpdateInfo
from fastapi import HTTPException, UploadFile, status
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from app.models import ApprovalStatus  # Asegúrate de importar esto

import os
import secrets
import string

import random

def generate_nickname(name: str) -> str:
    parts = name.split()
    if len(parts) == 1:
        return (parts[0][0] + parts[0][-1]).upper()  # Primera y última letra del único nombre en mayúsculas
    elif len(parts) >= 2:
        return (parts[0][0] + parts[0][-1] + parts[1][0] + parts[1][-1]).upper()  # Primer y última letra de los dos primeros nombres o palabras en mayúsculas
    return ""  # En caso de un string vacío (no debería pasar)

# User CRUD Operations
def create_user(db: Session, user: UserCreate):
    nickname = generate_nickname(user.name)
    db_user = User(
        num_document=user.num_document,
        name=user.name,
        email=user.email,
        telephone=user.telephone,
        password=user.password,
        nickname=nickname 
    )
    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )


def update_user(db: Session, user_id: int, user: UserUpdate):
    db_user = db.query(User).filter(User.id == user_id).first()
    try:
        if not db_user:
            return None
        for key, value in user.model_dump(exclude_unset=True).items():
            setattr(db_user, key, value)
        db.commit()
        db.refresh(db_user)
        return db_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error updating information")

def get_user(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_users(db: Session, skip: int = 0, limit: int = 10):
    return db.query(User).offset(skip).limit(limit).all()

def create_form(db: Session, form: FormBaseUser, user_id: int):
    try:
        # Verificar que los usuarios asignados existan en la base de datos
        existing_users = db.query(User.id).filter(User.id.in_(form.assign_user)).all()
        if len(existing_users) != len(form.assign_user):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uno o más usuarios asignados no existen"
            )

        # Crear el formulario base
        db_form = Form(
            user_id=user_id,
            title=form.title,
            description=form.description,
            format_type=form.format_type,  
            created_at=datetime.utcnow()
        )

        # Crear relaciones con FormModerators para los usuarios asignados
        for assigned_user_id in form.assign_user:
            db_form.form_moderators.append(FormModerators(user_id=assigned_user_id))

        db.add(db_form)
        db.commit()
        db.refresh(db_form)

        # Crear y devolver la respuesta con la estructura correcta
        response = {
            "id": db_form.id,
            "user_id": db_form.user_id,
            "title": db_form.title,
            "description": db_form.description,
            "format_type": db_form.format_type.value,  # ← Añadido
            "created_at": db_form.created_at,
            "assign_user": [moderator.user_id for moderator in db_form.form_moderators]
        }

        return response

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error al crear el formulario con la información proporcionada"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )
        
def get_form(db: Session, form_id: int, user_id: int):
    # Cargar el formulario con sus preguntas y respuestas
    form = db.query(Form).options(
        joinedload(Form.questions).joinedload(Question.options),
        joinedload(Form.responses).joinedload(Response.answers)
    ).filter(Form.id == form_id).first()

    if not form:
        return None

    # Filtrar las respuestas según el tipo de formato del formulario
    if form.format_type.name in ['abierto', 'semi_abierto']:
        form.responses = [resp for resp in form.responses if resp.user_id == user_id]
    else:
        form.responses = []  

    # Ahora agregamos is_repeated a cada pregunta
    for question in form.questions:
        # Buscar si hay algún registro de FormAnswer relacionado con esta pregunta
        form_answer = db.query(FormAnswer).filter(
            FormAnswer.form_id == form_id,
            FormAnswer.question_id == question.id
        ).first()

        # Si se encuentra un registro en form_answers, asignamos el valor de is_repeated
        if form_answer:
            question.is_repeated = form_answer.is_repeated
        else:
            question.is_repeated = False  # Si no se encuentra, asumimos que no es repetido

    # Ahora devolvemos el formulario con las preguntas y el valor de is_repeated
    form_data = {
        "id": form.id,
        "description": form.description,
        "created_at": form.created_at.isoformat(),
        "user_id": form.user_id,
        "title": form.title,
        "format_type": form.format_type.name,
        "form_design":form.form_design,
        "questions": [
            {
                "id": question.id,
                "required": question.required,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "root": question.root,
                "options": [
                    {"id": option.id, "option_text": option.option_text}
                    for option in question.options
                ],
                "is_repeated": getattr(question, 'is_repeated', False)  # Incluir is_repeated en la pregunta
            }
            for question in form.questions
        ],
        "responses": [
            {
                "id": response.id,
                "user_id": response.user_id,
                "answers": [
                    {
                        "id": answer.id,
                        "question_id": answer.question_id,
                        "answer_text": answer.answer_text,
                    }
                    for answer in response.answers
                ]
            }
            for response in form.responses
           
        ]
    }

    return form_data



def get_forms(db: Session, skip: int = 0, limit: int = 10):
    return db.query(Form).offset(skip).limit(limit).all()

# Question CRUD Operations
def create_question(db: Session, question: QuestionCreate):
    try:
        db_question = Question(
            question_text=question.question_text,
            question_type=question.question_type,
            required=question.required, 
            root=question.root
            
        )
        db.add(db_question)
        db.commit()
        db.refresh(db_question)
        return db_question        
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error to create a question with the provided information"
        )

def get_question_by_id(db: Session, question_id: int) -> Question:
    return db.query(Question).filter(Question.id == question_id).first()

def get_questions(db: Session):
    return db.query(Question).all()  # Trae todas las preguntas sin paginación

def update_question(db: Session, question_id: int, question: QuestionUpdate) -> Question:
    try:
        db_question = db.query(Question).filter(Question.id == question_id).first()
        if not db_question:
            return None
        
        for key, value in question.model_dump(exclude_unset=True).items():
            setattr(db_question, key, value)
        
        db.commit()
        db.refresh(db_question)
        return db_question
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error updating question with the provided information")

def add_questions_to_form(db: Session, form_id: int, question_ids: List[int]):
    try:
        print(f"🧩 Iniciando proceso para agregar preguntas al formulario ID {form_id}")
        print(f"🔍 Preguntas recibidas: {question_ids}")

        db_form = db.query(Form).filter(Form.id == form_id).first()
        if not db_form:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

        current_question_ids = {fq.id for fq in db_form.questions}

        print(f"📌 Preguntas ya asociadas al formulario: {current_question_ids}")

        new_question_ids = set(question_ids) - current_question_ids
        print(f"➕ Nuevas preguntas a asociar: {new_question_ids}")

        if not new_question_ids:
            print("⚠️ No hay nuevas preguntas para agregar.")
            return db_form

        new_questions = db.query(Question).filter(Question.id.in_(new_question_ids)).all()

        if len(new_questions) != len(new_question_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more questions not found"
            )

        form_questions = []
        for question in new_questions:
            fq = FormQuestion(form_id=form_id, question_id=question.id)
            form_questions.append(fq)
            print(f"✅ Asociando pregunta ID {question.id} al formulario ID {form_id}")

        db.bulk_save_objects(form_questions)
        db.commit()

        print(f"🎉 {len(form_questions)} preguntas asociadas correctamente al formulario.")
        db.refresh(db_form)
        return db_form

    except IntegrityError:
        db.rollback()
        print("❌ Error de integridad al asignar preguntas al formulario.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error assigning questions to the form")

# Option CRUD Operations
def create_options(db: Session, options: List[OptionCreate]):
    try:
        db_options = []
        for option in options:
            db_option = Option(question_id=option.question_id, option_text=option.option_text)
            db.add(db_option)
            db_options.append(db_option)
        db.commit()
        for db_option in db_options:
            db.refresh(db_option)
        return db_options
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error creating the options for the question")

def get_options_by_question_id(db: Session, question_id: int):
    return db.query(Option).filter(Option.question_id == question_id).all()

# Response CRUD Operations
def create_response(db: Session, response: ResponseCreate, form_id: int, user_id: int):
    db_response = Response(form_id=form_id, user_id=user_id, submitted_at=response.submitted_at)
    db.add(db_response)
    db.commit()
    db.refresh(db_response)
    return db_response

def get_responses(db: Session, form_id: int):
    return db.query(Response).filter(Response.form_id == form_id).all()

# Answer CRUD Operations
def create_answer(db: Session, answer: AnswerCreate, response_id: int, question_id: int):
    db_answer = Answer(response_id=response_id, question_id=question_id, answer_text=answer.answer_text, file_path=answer.file_path)
    db.add(db_answer)
    db.commit()
    db.refresh(db_answer)
    return db_answer

def get_answers(db: Session, response_id: int):
    return db.query(Answer).filter(Answer.response_id == response_id).all()

def create_project(db: Session, project_data: ProjectCreate):
    new_project = Project(**project_data.dict())
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return new_project

def get_all_projects(db: Session):
    return db.query(Project).all()

def delete_project_by_id(db: Session, project_id: int):
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    existing_forms = db.query(Form).filter(Form.project_id == project_id).first()
    if existing_forms:
        raise HTTPException(status_code=400, detail="No se puede eliminar el proyecto porque tiene formularios asociados.")

    db.delete(project)
    db.commit()

    return {"message": "Project deleted successfully"}


def get_forms_by_project(db: Session, project_id: int):
    """Consulta los formularios asociados a un proyecto específico"""
    forms = db.query(Form).filter(Form.project_id == project_id).all()

    if not forms:
        raise HTTPException(status_code=404, detail="No forms found for this project")

    return forms

def get_responses_by_project(db: Session, project_id: int):
    # Obtiene los formularios asociados al proyecto
    forms = db.query(Form).filter(Form.project_id == project_id).all()

    if not forms:
        raise HTTPException(status_code=404, detail="No forms found for this project")

    # Obtiene los IDs de los formularios
    form_ids = [form.id for form in forms]

    # Consulta las respuestas relacionadas con esos formularios
    responses = (
        db.query(Response)
        .filter(Response.form_id.in_(form_ids))
        .all()
    )

    # Combina los formularios y sus respuestas (solo si hay respuestas)
    result = []
    for form in forms:
        form_responses = []
        for response in responses:
            if response.form_id == form.id:
                # Obtiene las respuestas detalladas (answers) para cada response y su texto de pregunta
                answers = db.query(Answer).filter(Answer.response_id == response.id).all()
                detailed_answers = []
                for answer in answers:
                    question = db.query(Question).filter(Question.id == answer.question_id).first()
                    detailed_answers.append({
                        "id": answer.id,
                        "answer_text": answer.answer_text,
                        "response_id": answer.response_id,
                        "question_id": answer.question_id,
                        "file_path": answer.file_path,
                        "question_text": question.question_text if question else None
                    })
                form_responses.append({
                    "response": response,
                    "answers": detailed_answers
                })
        if form_responses:  # Solo añade formularios con respuestas
            result.append({"form": form, "responses": form_responses})

    if not result:
        raise HTTPException(status_code=404, detail="No responses found for this project's forms")

    return result



def delete_question_from_db(db: Session, question_id: int):
    # 1. Eliminar respuestas (answers)
    db.query(Answer).filter(Answer.question_id == question_id).delete()

    # 2. Eliminar respuestas de formulario (form_answers)
    db.query(FormAnswer).filter(FormAnswer.question_id == question_id).delete()

    # 3. Eliminar opciones (options)
    db.query(Option).filter(Option.question_id == question_id).delete()

    # 4. Eliminar relación en tabla intermedia form_questions
    db.query(FormQuestion).filter(FormQuestion.question_id == question_id).delete()

    # 5. Eliminar relaciones en question_table_relations
    db.query(QuestionTableRelation).filter(
        (QuestionTableRelation.question_id == question_id) |
        (QuestionTableRelation.related_question_id == question_id)
    ).delete()

    # 6. Eliminar filtros relacionados en question_filter_conditions
    db.query(QuestionFilterCondition).filter(
        (QuestionFilterCondition.filtered_question_id == question_id) |
        (QuestionFilterCondition.source_question_id == question_id) |
        (QuestionFilterCondition.condition_question_id == question_id)
    ).delete()

    # 7. Finalmente, eliminar la pregunta
    db.query(Question).filter(Question.id == question_id).delete()

    db.commit()
def post_create_response(db: Session, form_id: int, user_id: int, mode: str = "online", repeated_id: Optional[str] = None):

    """Crea una nueva respuesta en la base de datos y sus aprobaciones correspondientes."""

    form = db.query(Form).filter(Form.id == form_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Contador por modo
    last_mode_response = (
        db.query(Response)
        .filter(Response.mode == mode)
        .order_by(Response.mode_sequence.desc())
        .first()
    )

    new_mode_sequence = last_mode_response.mode_sequence + 1 if last_mode_response else 1

    # Crear nueva respuesta
    response = Response(
        form_id=form_id,
        user_id=user_id,
        mode=mode,
        mode_sequence=new_mode_sequence,
        submitted_at=func.now(),
        repeated_id=repeated_id  # Aquí se asigna
    )


    db.add(response)
    db.commit()
    db.refresh(response)

        # Obtener aprobadores desde FormApproval
    form_approvals = db.query(FormApproval).filter(FormApproval.form_id == form_id, FormApproval.is_active == True).all()

    # Crear entradas en ResponseApproval
    for approver in form_approvals:
        response_approval = ResponseApproval(
            response_id=response.id,
            user_id=approver.user_id,
            sequence_number=approver.sequence_number,
            is_mandatory=approver.is_mandatory,
            status=ApprovalStatus.pendiente,  # estado inicial
        )
        db.add(response_approval)

    db.commit()
    
    send_mails_to_next_supporters(response.id , db)

    return {
        "message": "Nueva respuesta guardada exitosamente",
        "response_id": response.id,
        "mode": mode,
        "mode_sequence": new_mode_sequence,
        "approvers_created": len(form_approvals)
    }


def create_answer_in_db(answer, db: Session):

    if isinstance(answer.question_id, str):
        try:
            parsed_answer = json.loads(answer.answer_text)
            if not isinstance(parsed_answer, dict):
                raise ValueError("answer_text debe ser un JSON de tipo dict para respuestas múltiples")
            
            created_answers = []
            for question_id_str, text in parsed_answer.items():
                question_id = int(question_id_str) 
                new_answer = Answer(
                    response_id=answer.response_id,
                    question_id=question_id,
                    answer_text=text,
                    file_path=answer.file_path
                )
                db.add(new_answer)
                db.flush()
                created_answers.append(new_answer)

            db.commit()
            for ans in created_answers:
                db.refresh(ans)

            return {
                "message": "Respuestas múltiples guardadas exitosamente",
                "answers": [{"id": a.id, "question_id": a.question_id} for a in created_answers]
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error procesando respuestas múltiples: {str(e)}")

    # Caso de una sola respuesta (question_id como int)
    elif isinstance(answer.question_id, int):
        return save_single_answer(answer, db)

    # Tipo de question_id no reconocido
    else:
        raise HTTPException(status_code=400, detail="Tipo de question_id no válido. Debe ser int o str.")
    
    
def save_single_answer(answer, db: Session):
    existing_answer = db.query(Answer).filter(
        Answer.response_id == answer.response_id,
        Answer.question_id == answer.question_id
    ).first()

    new_answer = Answer(
        response_id=answer.response_id,
        question_id=answer.question_id,
        answer_text=answer.answer_text,
        file_path=answer.file_path
    )
    db.add(new_answer)
    db.commit()
    db.refresh(new_answer)
    return {"message": "Respuesta guardada exitosamente", "answer_id": new_answer.id}

def check_form_data(db: Session, form_id: int):
    """
    Obtiene los datos completos de un formulario y sus respuestas.

    Esta función busca un formulario por su ID y construye una estructura detallada
    que incluye los siguientes elementos:
    - Información básica del formulario.
    - Datos del creador del formulario.
    - Datos del proyecto asociado (si existe).
    - Lista de respuestas, cada una con su usuario y respuestas a preguntas.
    - Información de cada pregunta respondida.

    Args:
        db (Session): Sesión de base de datos SQLAlchemy.
        form_id (int): ID del formulario que se desea consultar.

    Returns:
        dict: Estructura con toda la información del formulario y sus respuestas.

    Raises:
        HTTPException: 
            - 404 si el formulario con el ID especificado no existe.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    responses = db.query(Response).filter(Response.form_id == form_id).all()
    answers = db.query(Answer).join(Response).filter(Response.form_id == form_id).all()
    questions = db.query(Question).all()
    
    form_data = {
        "form_id": form.id,
        "title": form.title,
        "description": form.description,
        "created_at": form.created_at,
        "user": {
            "id": form.user.id,
            "name": form.user.name,
            "nickname": form.user.nickname  # Nuevo campo agregado
        } if form.user else None,
        "project": {"id": form.project.id, "name": form.project.name} if form.project else None,
        "has_responses": bool(responses),
        "responses": [
            {
                "response_id": response.id,
                "user": {
                    "id": response.user.id,
                    "name": response.user.name,
                    "nickname": response.user.nickname  # Nuevo campo agregado
                } if response.user else None,
                "submitted_at": response.submitted_at,
                "answers": [
                    {
                        "answer_id": answer.id,
                        "question_id": answer.question_id,
                        "answer_text": answer.answer_text,
                        "question": {
                            "id": question.id,
                            "question_text": question.question_text,
                            "question_type": question.question_type.name
                        } if (question := next((q for q in questions if q.id == answer.question_id), None)) else None
                    }
                    for answer in answers if answer.response_id == response.id
                ]
            } for response in responses
        ]
    }
    
    return form_data


import json

def create_form_schedule(
    db: Session, 
    form_id: int, 
    user_id: int, 
    frequency_type: str,
    repeat_days: list[str] | None, 
    interval_days: int | None, 
    specific_date: datetime | None,
    status: bool
):
    """
    Crea o actualiza un registro de programación de formulario en la base de datos.

    Si ya existe una programación con la combinación `form_id` y `user_id`, actualiza el registro. 
    En caso contrario, se crea uno nuevo. La programación permite establecer diferentes tipos 
    de frecuencia (diaria, semanal, específica, etc.).

    Args:
        db (Session): Sesión de la base de datos.
        form_id (int): ID del formulario a programar.
        user_id (int): ID del usuario al que está asignada la programación.
        frequency_type (str): Tipo de frecuencia ('daily', 'weekly', 'specific', etc.).
        repeat_days (list[str] | None): Días de la semana en los que se repite (si aplica).
        interval_days (int | None): Intervalo en días entre ejecuciones (si aplica).
        specific_date (datetime | None): Fecha específica para la programación (si aplica).
        status (bool): Estado de la programación (activa/inactiva).

    Returns:
        FormSchedule: Instancia del objeto programado.
    """
    # Verificar si ya existe un registro con esa combinación
    existing_schedule = db.query(FormSchedule).filter_by(form_id=form_id, user_id=user_id).first()

    if existing_schedule:
        # Si existe, actualiza el registro
        existing_schedule.frequency_type = frequency_type
        existing_schedule.repeat_days = json.dumps(repeat_days) if repeat_days else None
        existing_schedule.interval_days = interval_days
        existing_schedule.specific_date = specific_date
        existing_schedule.status = status
        db.commit()
        db.refresh(existing_schedule)
        return existing_schedule
    else:
        # Si no existe, crea uno nuevo
        new_schedule = FormSchedule(
            form_id=form_id,
            user_id=user_id,
            frequency_type=frequency_type,
            repeat_days=json.dumps(repeat_days) if repeat_days else None,
            interval_days=interval_days,
            specific_date=specific_date,
            status=status
        )
        db.add(new_schedule)
        db.commit()
        db.refresh(new_schedule)
        return new_schedule


def fetch_all_users(db: Session):
    """Función para obtener todos los usuarios de la base de datos."""
    stmt = select(User)
    result = db.execute(stmt)  # No usar `await`
    users = result.scalars().all()  # No usar `await`

    if not users:
        raise HTTPException(status_code=404, detail="No se encontraron usuarios")

    return users

def get_response_id(db: Session, form_id: int, user_id: int):
    """Obtiene el ID de Response basado en form_id y user_id."""
    stmt = select(Response.id).where(Response.form_id == form_id, Response.user_id == user_id)
    result = db.execute(stmt).scalar()  # `.scalar()` devuelve solo el ID si existe

    if result is None:
        raise HTTPException(status_code=404, detail="No se encontró la respuesta")

    return {"response_id": result}


def get_all_forms(db: Session):
    """
    Realiza una consulta para obtener todos los formularios.

    :param db: Sesión activa de la base de datos
    :return: Lista de formularios como diccionarios
    """
    forms = db.query(Form).all()
    return [
        {
            "id": form.id,
            "user_id": form.user_id,
            "title": form.title,
            "description": form.description,
            "created_at": form.created_at,
        }
        for form in forms
    ]
    
def get_forms_by_user(db: Session, user_id: int):
    """
    Obtiene los formularios asociados al usuario a través de la relación con la tabla `form_moderators`.

    :param db: Sesión de base de datos activa.
    :param user_id: ID del usuario autenticado.
    :return: Lista de objetos Form.
    """
    forms = db.query(Form).join(FormModerators).filter(FormModerators.user_id == user_id).all()
    return forms


def get_answers_by_question(db: Session, question_id: int):
    # Consulta todas las respuestas asociadas al question_id
    answers = db.query(Answer).filter(Answer.question_id == question_id).all()
    return answers



def get_unrelated_questions(db: Session, form_id: int):
    # Subconsulta para obtener todos los IDs de preguntas relacionadas con el form_id dado
    subquery = (
        select(FormQuestion.question_id)
        .where(FormQuestion.form_id == form_id)
    )

    # Consulta principal para obtener preguntas que no estén relacionadas con el form_id
    unrelated_questions = (
        db.query(Question)
        .filter(Question.id.not_in(subquery))
        .all()
    )

    return unrelated_questions


def fetch_completed_forms_by_user(db: Session, user_id: int):
    """
    Recupera los formularios que el usuario ha completado.

    :param db: Sesión de la base de datos.
    :param user_id: ID del usuario.
    :return: Lista de formularios completados.
    """
    completed_forms = (
        db.query(Form)
        .join(Response)  # Unión entre formularios y respuestas
        .filter(Response.user_id == user_id)  # Filtrar por el usuario
        .distinct()  # Evitar duplicados si hay múltiples respuestas a un mismo formulario
        .all()
    )
    return completed_forms


def fetch_form_questions(form_id: int, db: Session):
    """
    Obtiene las preguntas asociadas y no asociadas a un formulario específico, 
    incluyendo información sobre si las preguntas asociadas son repetidas (`is_repeated`).

    Args:
        form_id (int): ID del formulario a consultar.
        db (Session): Sesión de base de datos.

    Returns:
        dict: Diccionario con:
            - 'associated_questions': Lista de preguntas asociadas con campo `is_repeated`.
            - 'unassociated_questions': Lista de preguntas no asociadas.

    Raises:
        HTTPException: Si no se encuentra el formulario.
    """
    all_questions = db.query(Question).all()

    # Obtener el formulario
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    # Obtener IDs de las preguntas asociadas
    associated_questions_ids = {q.id for q in form.questions}

    # Obtener todos los form_answers relacionados a este form
    form_answers = db.query(FormAnswer).filter(FormAnswer.form_id == form_id).all()
    question_id_to_is_repeated = {
        fa.question_id: fa.is_repeated for fa in form_answers
    }

    # Separar preguntas asociadas y no asociadas
    associated_questions = [q for q in all_questions if q.id in associated_questions_ids]
    unassociated_questions = [q for q in all_questions if q.id not in associated_questions_ids]

    def serialize_question(q, is_associated=False):
        return {
            "id": q.id,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "required": q.required,
            "root": q.root,
            "is_repeated": question_id_to_is_repeated.get(q.id) if is_associated else None
        }

    return {
        "associated_questions": [serialize_question(q, is_associated=True) for q in associated_questions],
        "unassociated_questions": [serialize_question(q) for q in unassociated_questions],
    }


def link_question_to_form(form_id: int, question_id: int, db: Session):
    """
    Crea una relación entre un formulario y una pregunta en la tabla FormQuestion.

    Args:
        form_id (int): ID del formulario.
        question_id (int): ID de la pregunta.
        db (Session): Sesión de base de datos.

    Returns:
        dict: Mensaje indicando éxito y el ID de la relación creada.

    Raises:
        HTTPException:
            - 404: Si el formulario o la pregunta no existen.
            - 400: Si ya existe la relación entre el formulario y la pregunta.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    # Verificar si la pregunta existe
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")

    # Verificar si la relación ya existe
    existing_relation = db.query(FormQuestion).filter(
        FormQuestion.form_id == form_id,
        FormQuestion.question_id == question_id
    ).first()
    
    if existing_relation:
        raise HTTPException(status_code=400, detail="La pregunta ya está asociada a este formulario")

    # Crear la nueva relación
    new_relation = FormQuestion(form_id=form_id, question_id=question_id)
    db.add(new_relation)
    db.commit()
    db.refresh(new_relation)

    return {"message": "Pregunta agregada al formulario correctamente", "relation": new_relation.id}


def fetch_form_users(form_id: int, db: Session):
    """
    Recupera los usuarios asociados y no asociados a un formulario como moderadores.

    Args:
        form_id (int): ID del formulario.
        db (Session): Sesión de base de datos.

    Returns:
        dict: Diccionario con:
            - 'associated_users': Usuarios asociados como moderadores.
            - 'unassociated_users': Resto de usuarios del sistema.

    Raises:
        HTTPException: Si el formulario no existe.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    # Obtener todos los usuarios
    all_users = db.query(User).all()

    # Obtener IDs de usuarios asociados como moderadores
    associated_users_ids = {moderator.user_id for moderator in form.form_moderators}

    # Separar usuarios en asociados y no asociados
    associated_users = [user for user in all_users if user.id in associated_users_ids]
    unassociated_users = [user for user in all_users if user.id not in associated_users_ids]

    return {
        "associated_users": associated_users,
        "unassociated_users": unassociated_users
    }
    

def link_moderator_to_form(form_id: int, user_id: int, db: Session):
    """
    Crea una relación entre un usuario y un formulario como moderador.

    Args:
        form_id (int): ID del formulario.
        user_id (int): ID del usuario.
        db (Session): Sesión activa de base de datos.

    Returns:
        dict: Mensaje de éxito y ID de la nueva relación.

    Raises:
        HTTPException:
            - 404: Si el formulario o usuario no existen.
            - 400: Si el usuario ya es moderador del formulario.
            
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Verificar si la relación ya existe
    existing_relation = db.query(FormModerators).filter(
        FormModerators.form_id == form_id,
        FormModerators.user_id == user_id
    ).first()
    
    if existing_relation:
        raise HTTPException(status_code=400, detail="El usuario ya es moderador de este formulario")

    # Crear la nueva relación
    new_relation = FormModerators(form_id=form_id, user_id=user_id)
    db.add(new_relation)
    db.commit()
    db.refresh(new_relation)

    return {"message": "Moderador agregado al formulario correctamente", "relation": new_relation.id}


def remove_question_from_form(form_id: int, question_id: int, db: Session):
    """
    Elimina la relación entre una pregunta y un formulario desde la tabla FormQuestion.

    Args:
        form_id (int): ID del formulario.
        question_id (int): ID de la pregunta.
        db (Session): Sesión activa de base de datos.

    Returns:
        dict: Mensaje de confirmación.

    Raises:
        HTTPException:
            - 404: Si la relación no existe.
    """
    form_question = db.query(FormQuestion).filter(
        FormQuestion.form_id == form_id,
        FormQuestion.question_id == question_id
    ).first()
    
    if not form_question:
        raise HTTPException(status_code=404, detail="La pregunta no está asociada a este formulario")

    # Eliminar la relación
    db.delete(form_question)
    db.commit()

    return {"message": "Pregunta eliminada del formulario correctamente"}


def remove_moderator_from_form(form_id: int, user_id: int, db: Session):
    """Elimina la relación de un moderador con un formulario en FormModerators."""
    
    # Buscar la relación en FormModerators
    form_moderator = db.query(FormModerators).filter(
        FormModerators.form_id == form_id,
        FormModerators.user_id == user_id
    ).first()
    
    if not form_moderator:
        raise HTTPException(status_code=404, detail="El usuario no es moderador de este formulario")

    # Eliminar la relación
    db.delete(form_moderator)
    db.commit()

    return {"message": "Moderador eliminado del formulario correctamente"}

def get_filtered_questions(db: Session, id_user: int):
    """Obtiene preguntas con root=True, sus respuestas únicas con sus IDs y formularios asignados al usuario con is_root=False"""

    # Obtener preguntas con root=True
    root_questions = db.query(Question).filter(Question.root == True).all()

    # Obtener respuestas únicas para esas preguntas
    question_ids = [q.id for q in root_questions]

    if not question_ids:
        return {"default_questions": [], "answers": [], "non_root_forms": []}

    unique_answers = (
        db.query(Answer.id, Answer.answer_text, Answer.question_id)
        .filter(Answer.question_id.in_(question_ids))
        .group_by(Answer.id, Answer.answer_text, Answer.question_id)
        .all()
    )

    # Obtener formularios con is_root=False que están asignados al usuario
    non_root_forms = (
        db.query(Form)
        .join(FormModerators, Form.id == FormModerators.form_id)
        .filter(Form.is_root == False, FormModerators.user_id == id_user)
        .all()
    )

    # Formatear la salida
    answers_dict = {}
    for answer_id, answer_text, question_id in unique_answers:
        if question_id not in answers_dict:
            answers_dict[question_id] = []
        answers_dict[question_id].append({"id": answer_id, "text": answer_text})

    return {
        "default_questions": [{"id": q.id, "text": q.question_text} for q in root_questions],
        "answers": answers_dict,
        "non_root_forms": [
            {"id": f.id, "title": f.title, "description": f.description} for f in non_root_forms
        ],
    }

def save_form_answers(db: Session, form_id: int, answer_ids: List[int]):
    saved = []
    for answer_id in answer_ids:
        form_answer = FormAnswer(
            form_id=form_id,
            answer_id=answer_id
        )
        db.add(form_answer)
        saved.append(form_answer)

    db.commit()
    for answer in saved:
        db.refresh(answer)

    return saved



def get_moderated_forms_by_answers(answer_ids: List[int], user_id: int, db: Session):
    """
    Busca los formularios asociados a las respuestas y verifica si el usuario es moderador de ellos.
    """
    # Obtener los formularios relacionados con las respuestas
    form_ids = (
        db.query(FormAnswer.form_id)
        .filter(FormAnswer.answer_id.in_(answer_ids))
        .distinct()
        .all()
    )
    
    form_ids = [f[0] for f in form_ids]  # Extraer solo los IDs

    if not form_ids:
        return []

    # Verificar si el usuario es moderador de esos formularios
    user_moderated_forms = (
        db.query(Form)
        .join(FormModerators, Form.id == FormModerators.form_id)
        .filter(FormModerators.user_id == user_id, Form.id.in_(form_ids))
        .all()
    )

    return user_moderated_forms

DIAS_SEMANA = {
    "monday": "lunes",
    "tuesday": "martes",
    "wednesday": "miercoles",
    "thursday": "jueves",
    "friday": "viernes",
    "saturday": "sabado",
    "sunday": "domingo"
}


def get_schedules_by_frequency(db: Session) -> List[dict]:
    schedules = db.query(FormSchedule).filter(FormSchedule.status == True).all()
    users_forms = {}
    logs = []  # Lista para almacenar los registros de cumplimiento

    # Obtener la fecha actual
    today_english = datetime.today().strftime('%A').lower()
    today_spanish = DIAS_SEMANA.get(today_english, "lunes")  # Default a lunes si hay error
    today_date = datetime.today().date()

    for schedule in schedules:
        frequency_type = schedule.frequency_type
        repeat_days = json.loads(schedule.repeat_days) if schedule.repeat_days else []
        interval_days = schedule.interval_days
        specific_date = schedule.specific_date

        # Lógica según el tipo de frecuencia
        if frequency_type == "daily":
            # Enviar todos los días
            print("➡️  Es daily, se enviará.")
            user = db.query(User).filter(User.id == schedule.user_id).first()
            form = db.query(Form).filter(Form.id == schedule.form_id).first()
            if user and form:
                if user.email not in users_forms:
                    users_forms[user.email] = {"user_name": user.name, "forms": []}
                users_forms[user.email]["forms"].append({
                    "title": form.title,
                    "description": form.description or "Sin descripción"
                })
                logs.append(f"Frecuencia diaria: Correo enviado a {user.email}.")
            else:
                logs.append(f"Frecuencia diaria: No se pudo encontrar el usuario o el formulario para el ID de programación {schedule.id}.")

        elif frequency_type == "weekly":
            print(f"    Revisando si '{today_english}' está en {repeat_days}")
            if today_english in repeat_days:
                print("✅ El día coincide, se enviará correo.")
                user = db.query(User).filter(User.id == schedule.user_id).first()
                form = db.query(Form).filter(Form.id == schedule.form_id).first()
                if user and form:
                    if user.email not in users_forms:
                        users_forms[user.email] = {"user_name": user.name, "forms": []}
                    users_forms[user.email]["forms"].append({
                        "title": form.title,
                        "description": form.description or "Sin descripción"
                    })
                    logs.append(f"Frecuencia semanal: Correo enviado a {user.email} el día {today_english}.")
                else:
                    logs.append(f"Frecuencia semanal: No se pudo encontrar el usuario o el formulario para el ID de programación {schedule.id}.")
            else:
                print("❌ Hoy no está en repeat_days, no se enviará correo.")

        elif frequency_type == "monthly":
            if today_date.day == 1:
                print("➡️  Es el primer día del mes, se enviará.")
                user = db.query(User).filter(User.id == schedule.user_id).first()
                form = db.query(Form).filter(Form.id == schedule.form_id).first()
                if user and form:
                    if user.email not in users_forms:
                        users_forms[user.email] = {"user_name": user.name, "forms": []}
                    users_forms[user.email]["forms"].append({
                        "title": form.title,
                        "description": form.description or "Sin descripción"
                    })
                    logs.append(f"Frecuencia mensual: Correo enviado a {user.email}.")
                else:
                    logs.append(f"Frecuencia mensual: No se pudo encontrar el usuario o el formulario para el ID de programación {schedule.id}.")
            else:
                print("🛑 No es el primer día del mes, no se enviará.")

        elif frequency_type == "periodic":
            if interval_days and today_date.day % interval_days == 0:
                print("➡️  Cumpsle el intervalo, se enviará.")
                user = db.query(User).filter(User.id == schedule.user_id).first()
                form = db.query(Form).filter(Form.id == schedule.form_id).first()
                if user and form:
                    if user.email not in users_forms:
                        users_forms[user.email] = {"user_name": user.name, "forms": []}
                    users_forms[user.email]["forms"].append({
                        "title": form.title,
                        "description": form.description or "Sin descripción"
                    })
                    logs.append(f"Frecuencia periódica: Correo enviado a {user.email} (intervalo {interval_days} días).")
                else:
                    logs.append(f"Frecuencia periódica: No se pudo encontrar el usuario o el formulario para el ID de programación {schedule.id}.")
            else:
                print("🛑 No cumple el intervalo, no se enviará.")

        elif frequency_type == "specific_date" and specific_date.date() == today_date:
            print("➡️  Es la fecha específica, se enviará.")
            user = db.query(User).filter(User.id == schedule.user_id).first()
            form = db.query(Form).filter(Form.id == schedule.form_id).first()
            if user and form:
                if user.email not in users_forms:
                    users_forms[user.email] = {"user_name": user.name, "forms": []}
                users_forms[user.email]["forms"].append({
                    "title": form.title,
                    "description": form.description or "Sin descripción"
                })
                logs.append(f"Frecuencia por fecha específica: Correo enviado a {user.email}.")
            else:
                logs.append(f"Frecuencia por fecha específica: No se pudo encontrar el usuario o el formulario para el ID de programación {schedule.id}.")
        else:
            print("🛑 No cumple ninguna condición para enviar.")

    # Enviar correos a los usuarios
    for email, data in users_forms.items():
        send_email_daily_forms(
            user_email=email,
            user_name=data["user_name"],
            forms=data["forms"]
        )

    # Imprimir los logs para ver cuál frecuencia se cumplió
    print("\n🔍 Logs de cumplimiento de frecuencias:")
    for log in logs:
        print(log)

    return schedules


def prepare_and_send_file_to_emails(
    file: UploadFile,
    emails: List[str],
    name_form: str,
    id_user: int,
    db: Session  # Asegúrate de pasar la sesión desde el endpoint
) -> dict:
    success_emails = []
    failed_emails = []
    
    user = db.query(User).filter(User.id == id_user).first()
    user_name = user.name if user else "Usuario"

    for email in emails:
        result = send_email_with_attachment(
            to_email=email,
            name_form=name_form,
            to_name=user_name,
            upload_file=file,
        )
        if result:
            success_emails.append(email)
        else:
            failed_emails.append(email)

        file.file.seek(0)

    return {
        "success": success_emails,
        "failed": failed_emails
    }


def update_user_info_in_db(db: Session, user: User, update_data: UserUpdateInfo):
    # Validar email duplicado (si cambió)
    if update_data.email != user.email:
        if db.query(User).filter(User.email == update_data.email, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="Email ya está en uso por otro usuario")
        email_changed = True
    else:
        email_changed = False

    # Validar teléfono duplicado (si cambió)
    if update_data.telephone != user.telephone:
        if db.query(User).filter(User.telephone == update_data.telephone, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="Teléfono ya está en uso por otro usuario")

    # Actualizar campos
    user.email = update_data.email
    user.name = update_data.name
    user.num_document = update_data.num_document
    user.telephone = update_data.telephone

    db.commit()
    db.refresh(user)

    return {
        "message": "Información actualizada exitosamente",
        "email_changed": email_changed,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "num_document": user.num_document,
            "telephone": user.telephone,
            "nickname": user.nickname,
            "user_type": user.user_type
        }
    }



def create_question_table_relation_logic(
    db: Session,
    question_id: int,
    name_table: str,
    related_question_id: Optional[int] = None,
    field_name: Optional[str] = None  # <-- NUEVO
) -> QuestionTableRelation:
    
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if related_question_id:
        related_question = db.query(Question).filter(Question.id == related_question_id).first()
        if not related_question:
            raise HTTPException(status_code=404, detail="Related question not found")

    existing_relation = db.query(QuestionTableRelation).filter(
        QuestionTableRelation.question_id == question_id
    ).first()

    if existing_relation:
        raise HTTPException(status_code=400, detail="Relation already exists for this question")

    # Crear relación con field_name incluido
    new_relation = QuestionTableRelation(
        question_id=question_id,
        name_table=name_table,
        related_question_id=related_question_id,
        field_name=field_name  # <-- INCLUIDO
    )

    db.add(new_relation)
    db.commit()
    db.refresh(new_relation)

    return new_relation



def get_related_or_filtered_answers(db: Session, question_id: int):
    # Verificar si existe una condición de filtro
    condition = db.query(QuestionFilterCondition).filter_by(filtered_question_id=question_id).first()

    if condition:
        # Obtener todas las respuestas del formulario relacionado
        responses = db.query(Response).filter_by(form_id=condition.form_id).all()
        valid_answers = []

        for response in responses:
            answers_dict = {a.question_id: a.answer_text for a in response.answers}
            source_val = answers_dict.get(condition.source_question_id)
            condition_val = answers_dict.get(condition.condition_question_id)

            if source_val is None or condition_val is None:
                continue

            # Intentar convertir valores a número si es posible
            try:
                condition_val = float(condition_val)
                expected_val = float(condition.expected_value)
            except ValueError:
                condition_val = str(condition_val)
                expected_val = str(condition.expected_value)

            if condition.operator == '==':
                if condition_val == expected_val:
                    valid_answers.append(source_val)
            elif condition.operator == '!=':
                if condition_val != expected_val:
                    valid_answers.append(source_val)
            elif condition.operator == '>':
                if condition_val > expected_val:
                    valid_answers.append(source_val)
            elif condition.operator == '<':
                if condition_val < expected_val:
                    valid_answers.append(source_val)
            elif condition.operator == '>=':
                if condition_val >= expected_val:
                    valid_answers.append(source_val)
            elif condition.operator == '<=':
                if condition_val <= expected_val:
                    valid_answers.append(source_val)

        filtered = list(filter(None, set(valid_answers)))
        return {
            "source": "condicion_filtrada",
            "data": [{"name": val} for val in filtered]
        }

    # Si no hay condición, usar relación de tabla
    relation = db.query(QuestionTableRelation).filter_by(question_id=question_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="No se encontró relación para esta pregunta")

    if relation.related_question_id:
        answers = db.query(Answer).filter_by(question_id=relation.related_question_id).all()
        return {
            "source": "pregunta_relacionada",
            "data": [{"name": ans.answer_text} for ans in answers]
        }

    name_table = relation.name_table
    field_name = relation.field_name

    valid_tables = {
        "answers": Answer,
        "users": User,
        "forms": Form,
        "options": Option,
    }

    table_translations = {
        "users": "usuarios",
        "forms": "formularios",
        "answers": "respuestas",
        "options": "opciones"
    }

    Model = valid_tables.get(name_table)
    if not Model:
        raise HTTPException(status_code=400, detail=f"Tabla '{name_table}' no soportada")

    if not hasattr(Model, field_name):
        raise HTTPException(status_code=400, detail=f"Campo '{field_name}' no existe en el modelo '{name_table}'")

    results = db.query(Model).all()

    def serialize(instance):
        return {"name": getattr(instance, field_name, None)}

    return {
        "source": table_translations.get(name_table, name_table),
        "data": [serialize(r) for r in results if getattr(r, field_name, None)]
    }


def get_questions_and_answers_by_form_id(db: Session, form_id: int):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        return None

    # Traer preguntas relacionadas al formulario
    questions = db.query(Question).join(Form.questions).filter(Form.id == form_id).all()

    # Traer respuestas, con usuario y respuestas anidadas
    responses = db.query(Response).filter(Response.form_id == form_id)\
        .options(
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.user)
        ).all()

    # Preparar data para el Excel
    data = []
    for response in responses:
        row = {
            "Nombre": response.user.name,
            "Documento": response.user.num_document,
        }
        for question in questions:
            # Buscar respuesta de esta pregunta
            answer_text = ""
            for answer in response.answers:
                if answer.question_id == question.id:
                    answer_text = answer.answer_text or answer.file_path or ""
                    break
            row[question.question_text] = answer_text
        data.append(row)

    return {
        "form_id": form.id,
        "form_title": form.title,
        "questions": [q.question_text for q in questions],
        "data": data
    }


def get_questions_and_answers_by_form_id_and_user(db: Session, form_id: int, user_id: int):
    """
    Obtiene todas las respuestas de un usuario para un formulario específico y las organiza en formato tabular.

    - **form_id**: ID del formulario.
    - **user_id**: ID del usuario.
    - **db**: Sesión de la base de datos.

    Retorna un diccionario con:
    - `total_responses`: Número total de registros generados.
    - `form_id`: ID del formulario.
    - `form_title`: Título del formulario.
    - `questions`: Lista de columnas ordenadas (preguntas más campos fijos).
    - `data`: Lista de filas con información del usuario y sus respuestas.

    Si el formulario no existe, retorna `None`.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        return None

    questions = db.query(Question).join(Form.questions).filter(Form.id == form_id).all()

    responses = db.query(Response).filter(Response.form_id == form_id, Response.user_id == user_id)\
        .options(
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.user)
        ).all()

    data = []
    counter = 1

    for response in responses:
        # Agrupar respuestas por pregunta
        grouped_answers = {}
        for answer in response.answers:
            q_text = answer.question.question_text
            grouped_answers.setdefault(q_text, []).append(answer.answer_text or answer.file_path or "")

        # Determinar máximo número de repeticiones para esa respuesta
        max_len = max(len(vals) for vals in grouped_answers.values()) if grouped_answers else 1

        # Por cada repetición, crear fila
        for i in range(max_len):
            row = {
                "Registro #": counter,
                "Nombre": response.user.name,
                "Documento": response.user.num_document,
                "ID Respuesta": response.id,
            }
            counter += 1

            # Rellenar respuestas para cada pregunta
            for q_text in [q.question_text for q in questions]:
                answers_list = grouped_answers.get(q_text, [])
                row[q_text] = answers_list[i] if i < len(answers_list) else ""

            # Fecha de envío como último campo
            row["Fecha de Envío"] = response.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if response.submitted_at else ""

            data.append(row)

    # Preparar columnas con orden fijo
    fixed_keys = ["Registro #", "Nombre", "Documento", "ID Respuesta"]
    question_keys = [q.question_text for q in questions]
    all_keys = fixed_keys + question_keys + ["Fecha de Envío"]

    # Asegurar que todas las filas tengan todas las columnas (vacías si no hay dato)
    for row in data:
        for key in all_keys:
            row.setdefault(key, "")

    return {
        "total_responses": len(data),
        "form_id": form.id,
        "form_title": form.title,
        "questions": all_keys,
        "data": data
    }

def generate_random_password(length=10):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(chars) for _ in range(length))

def create_user_with_random_password(db: Session, user: UserBaseCreate) -> User:
    password = generate_random_password()
    hashed = hash_password(password)

    user_data = UserCreate(
        num_document=user.num_document,
        name=user.name,
        email=user.email,
        telephone=user.telephone,
        password=hashed,
    )

    nickname = generate_nickname(user.name)

    db_user = User(
        num_document=user_data.num_document,
        name=user_data.name,
        email=user_data.email,
        telephone=user_data.telephone,
        password=user_data.password,
        nickname=nickname
    )

    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # Enviar correo con contraseña generada
        send_welcome_email(db_user.email, db_user.name, password)

        return db_user

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
        


def get_user_by_document(db: Session, num_document: str):
    return db.query(models.User).filter(models.User.num_document == num_document).first()


def generate_unique_serial(db: Session, length: int = 5) -> str:
    while True:
        serial = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        exists = db.query(AnswerFileSerial).filter(AnswerFileSerial.serial == serial).first()
        if not exists:
            return serial
        
def get_form_responses_data(form_id: int, db: Session):
    """
    Consulta y estructura las respuestas de un formulario específico.

    - **form_id**: ID del formulario.
    - **db**: Sesión de la base de datos.

    Retorna un diccionario con:
    - `form_id`: ID del formulario.
    - `form_title`: Título del formulario.
    - `responses`: Lista de respuestas, cada una con:
        - `response_id`
        - `mode` y `mode_sequence`
        - `user`: Datos del usuario que respondió.
        - `answers`: Lista de respuestas por pregunta, incluyendo texto y archivos.

    Devuelve `None` si el formulario no existe.
    """
    form = db.query(Form).options(
        joinedload(Form.responses)
        .joinedload(Response.user),  # ← Atributo de clase, no string
        joinedload(Form.responses)
        .joinedload(Response.answers)
        .joinedload(Answer.question),  # ← Encadenamiento correcto
    ).filter(Form.id == form_id).first()

    if not form:
        return None

    results = []
    for response in form.responses:
        user_info = {
            "user_id": response.user.id,
            "name": response.user.name,
            "email": response.user.email,
            "num_document": response.user.num_document,
            "submitted_at": response.submitted_at
        }

        answers_info = []
        for answer in response.answers:
            answers_info.append({
                "question_id": answer.question.id,
                "question_text": answer.question.question_text,
                "question_type": answer.question.question_type,
                "answer_text": answer.answer_text,
                "file_path": answer.file_path
            })

        results.append({
            "response_id": response.id,
            "mode": response.mode,
            "mode_sequence": response.mode_sequence,
            "user": user_info,
            "answers": answers_info
        })

    return {
        "form_id": form.id,
        "form_title": form.title,
        "responses": results
    }
    
def get_user_responses_data(user_id: int, db: Session):
    """
    Consulta y estructura las respuestas asociadas a un usuario específico.

    - **user_id**: ID del usuario.
    - **db**: Sesión de la base de datos.

    Retorna un diccionario con:
    - `user_id`: ID del usuario.
    - `user_name`: Nombre del usuario.
    - `email`: Correo del usuario.
    - `responses`: Lista de respuestas con:
        - `response_id`, `mode`, `mode_sequence`, `submitted_at`
        - `form`: Información del formulario.
        - `answers`: Lista de respuestas por pregunta (texto y archivo si aplica).

    Devuelve `None` si el usuario no existe.
    """
    user = db.query(User).options(
        joinedload(User.responses)
        .joinedload(Response.form),
        joinedload(User.responses)
        .joinedload(Response.answers)
        .joinedload(Answer.question)
    ).filter(User.id == user_id).first()

    if not user:
        return None

    results = []
    for response in user.responses:
        form_info = {
            "form_id": response.form.id,
            "form_title": response.form.title,
            "form_description": response.form.description
        }

        answers_info = []
        for answer in response.answers:
            answers_info.append({
                "question_id": answer.question.id,
                "question_text": answer.question.question_text,
                "question_type": answer.question.question_type,
                "answer_text": answer.answer_text,
                "file_path": answer.file_path
            })

        results.append({
            "response_id": response.id,
            "mode": response.mode,
            "mode_sequence": response.mode_sequence,
            "submitted_at": response.submitted_at,
            "form": form_info,
            "answers": answers_info
        })

    return {
        "user_id": user.id,
        "user_name": user.name,
        "email": user.email,
        "responses": results
    }
    
def get_all_user_responses_by_form_id(db: Session, form_id: int):
    """
    Recupera y estructura las respuestas de todos los usuarios para un formulario específico.

    - Agrupa respuestas por pregunta.
    - Soporta preguntas con múltiples respuestas (como repeticiones).
    - Devuelve filas planas donde cada fila representa una instancia única de respuestas de un usuario.

    Args:
        db (Session): Sesión activa de la base de datos.
        form_id (int): ID del formulario del que se quiere obtener la información.

    Returns:
        dict: Estructura con claves:
            - total_responses: número total de registros generados.
            - form_id: ID del formulario.
            - form_title: título del formulario.
            - questions: lista ordenada de columnas (preguntas).
            - data: lista de filas con respuestas por usuario.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        return None

    questions = db.query(Question).join(Form.questions).filter(Form.id == form_id).all()

    responses = db.query(Response).filter(Response.form_id == form_id)\
        .options(
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.user)
        ).all()

    data = []
    counter = 1  # Contador para el consecutivo

    for response in responses:
        # Agrupar respuestas por orden de aparición de repetidas
        grouped_answers = {}
        for answer in response.answers:
            q_text = answer.question.question_text
            grouped_answers.setdefault(q_text, []).append(answer.answer_text or answer.file_path or "")

        # Determinar el número máximo de repeticiones
        max_len = max(len(vals) for vals in grouped_answers.values()) if grouped_answers else 1

        # Crear una fila por cada repetición (registro)
        for i in range(max_len):
            row = {
                "Registro #": counter,
                "Nombre": response.user.name,
                "Documento": response.user.num_document,
                
            }
            counter += 1

            for q_text, answers_list in grouped_answers.items():
                row[q_text] = answers_list[i] if i < len(answers_list) else ""

            # Agregar la fecha como último campo
            row["Fecha de Envío"] = response.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if response.submitted_at else ""
            data.append(row)

    # Obtener todas las claves únicas para las columnas, con control del orden
    fixed_keys = ["Registro #", "Nombre", "Documento"]
    question_keys = sorted({key for row in data for key in row if key not in fixed_keys + ["Fecha de Envío"]})
    all_keys = fixed_keys + question_keys + ["Fecha de Envío"]

    # Asegurar que todas las filas tengan las mismas columnas y en el orden deseado
    for row in data:
        for key in all_keys:
            row.setdefault(key, "")
        # Reordenar explícitamente las claves
        row = {key: row[key] for key in all_keys}

    # Retornar el diccionario con total_responses como primer campo
    return {
        "total_responses": len(data),  # Primero
        "form_id": form.id,
        "form_title": form.title,
        "questions": all_keys,
        "data": data
    }


def get_unanswered_forms_by_user(db: Session, user_id: int):
    """
    Retorna los formularios asignados a un usuario que aún no ha respondido.

    Args:
        db (Session): Sesión activa de la base de datos.
        user_id (int): ID del usuario autenticado.

    Returns:
        List[Form]: Lista de formularios no respondidos por el usuario.
    """
    # Subconsulta: formularios que ya respondió el usuario
    subquery = db.query(Response.form_id).filter(Response.user_id == user_id)
    
    # Formularios asignados al usuario pero no respondidos
    forms = db.query(Form).join(FormModerators).filter(
        FormModerators.user_id == user_id,
        ~Form.id.in_(subquery)
    ).all()
    
    return forms
def save_form_approvals(data: FormApprovalCreateSchema, db: Session):
    """
    Guarda las aprobaciones asociadas a un formulario.

    - Verifica si el formulario existe.
    - Revisa si ya existen aprobaciones activas para los usuarios.
    - Crea nuevas aprobaciones si no hay duplicados o si el `sequence_number` es diferente.
    - Retorna una lista de IDs de usuarios cuyas aprobaciones fueron creadas.

    Args:
        data (FormApprovalCreateSchema): Datos del formulario y aprobadores a guardar.
        db (Session): Sesión de la base de datos.

    Returns:
        List[int]: Lista de IDs de usuarios aprobadores que fueron agregados.
    """
    # Verifica si el formulario existe
    form = db.query(Form).filter(Form.id == data.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")

    # Obtiene las aprobaciones existentes para este formulario
    existing_approvals = db.query(FormApproval).filter(FormApproval.form_id == data.form_id).all()

    # Lista para guardar los nuevos IDs insertados
    newly_created_user_ids = []

    # Solo agrega nuevos aprobadores (no duplicados) o crea un nuevo registro si el sequence_number es diferente
    for approver in data.approvers:
        # Filtra aprobaciones activas con el mismo user_id y form_id
        existing_active_approval = next(
            (fa for fa in existing_approvals if fa.user_id == approver.user_id and fa.is_active), None
        )

        if existing_active_approval:
            # Si ya existe un aprobador activo con el mismo user_id y form_id y el sequence_number es diferente
            if existing_active_approval.sequence_number != approver.sequence_number:
                # Crea una nueva entrada
                db.add(FormApproval(
                    form_id=data.form_id,
                    user_id=approver.user_id,
                    sequence_number=approver.sequence_number,
                    is_mandatory=approver.is_mandatory,
                    deadline_days=approver.deadline_days,
                    is_active=approver.is_active if approver.is_active is not None else True  # Si no se pasa, se asume True
                ))
                newly_created_user_ids.append(approver.user_id)
        else:
            # Si no existe un aprobador activo con el mismo user_id y form_id, se puede agregar el nuevo aprobador
            db.add(FormApproval(
                form_id=data.form_id,
                user_id=approver.user_id,
                sequence_number=approver.sequence_number,
                is_mandatory=approver.is_mandatory,
                deadline_days=approver.deadline_days,
                is_active=approver.is_active if approver.is_active is not None else True  # Si no se pasa, se asume True
            ))
            newly_created_user_ids.append(approver.user_id)

    db.commit()
    return newly_created_user_ids

def create_response_approval(db: Session, approval_data: ResponseApprovalCreate) -> ResponseApproval:
    new_approval = ResponseApproval(**approval_data.model_dump())
    db.add(new_approval)
    db.commit()
    db.refresh(new_approval)
    return new_approval


def get_forms_pending_approval_for_user(user_id: int, db: Session):
    results = []

    form_approvals = (
        db.query(FormApproval)
        .filter(FormApproval.user_id == user_id, FormApproval.is_active == True)
        .all()
    )

    for form_approval in form_approvals:
        form = form_approval.form

        # 📌 Mostrar plantilla de aprobadores para este formulario

        approval_template = db.query(FormApproval).filter(FormApproval.form_id == form.id).order_by(FormApproval.sequence_number).all()

        for approver in approval_template:
            approver_user = approver.user

        responses = db.query(Response).filter(Response.form_id == form.id).all()

        for response in responses:
# Filtramos todas las aprobaciones del usuario para esta respuesta
            response_approvals = db.query(ResponseApproval).filter(
                ResponseApproval.response_id == response.id,
                ResponseApproval.user_id == user_id
            ).order_by(ResponseApproval.sequence_number).all()

            # Identificamos cuál está pendiente o cuál está en el turno actual
            response_approval = next(
                (ra for ra in response_approvals if ra.status != ApprovalStatus.aprobado),
                response_approvals[-1] if response_approvals else None
            )


            if not response_approval:
                continue  # Este usuario no debe aprobar esta respuesta

            sequence = response_approval.sequence_number

            # Verificar si todos los aprobadores anteriores obligatorios ya aprobaron
            prev_approvers = db.query(ResponseApproval).filter(
                ResponseApproval.response_id == response.id,
                ResponseApproval.sequence_number < sequence,
                ResponseApproval.is_mandatory == True
            ).all()

            all_prev_approved = all(pa.status == ApprovalStatus.aprobado for pa in prev_approvers)

            if not all_prev_approved:
                continue  # Todavía no es el turno de este aprobador

            # 📌 Mostrar estado de cada aprobador de esta respuesta

            response_approvals = db.query(ResponseApproval).filter(
                ResponseApproval.response_id == response.id
            ).order_by(ResponseApproval.sequence_number).all()

            for ra in response_approvals:
                user_ra = ra.user


            answers = db.query(Answer, Question).join(Question).filter(
                Answer.response_id == response.id
            ).all()

            answers_data = [{
                "question_id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "answer_text": a.answer_text,
                "file_path": a.file_path
            } for a, q in answers]

            all_approvals = [{
                "user_id": ra.user_id,
                "sequence_number": ra.sequence_number,
                "is_mandatory": ra.is_mandatory,
                "status": ra.status.value,
                "reconsideration_requested": ra.reconsideration_requested,
                "reviewed_at": ra.reviewed_at.isoformat() if ra.reviewed_at else None,
                "message": ra.message,
                "user": {
                    "name": ra.user.name,
                    "email": ra.user.email,
                    "num_document": ra.user.num_document
                }
            } for ra in response_approvals]


            user_response = db.query(User).filter(User.id == response.user_id).first()

            results.append({
                "deadline_days": form_approval.deadline_days,
                "form_id": form.id,
                "form_title": form.title,
                "form_description": form.description,
                "form_design":form.form_design,
                "submitted_by": {
                    "user_id": user_response.id,
                    "name": user_response.name,
                    "email": user_response.email,
                    "num_document": user_response.num_document
                },
                "response_id": response.id,
                "submitted_at": response.submitted_at.isoformat(),
                "answers": answers_data,
                "your_approval_status": {
                    "status": response_approval.status.value,
                    "reviewed_at": response_approval.reviewed_at.isoformat() if response_approval.reviewed_at else None,
                    "message": response_approval.message,
                    "sequence_number": response_approval.sequence_number
                },
                "all_approvers": all_approvals
            })

    return results


def get_bogota_time() -> datetime:
    """Retorna la hora actual con la zona horaria de Bogotá."""
    return datetime.now(pytz.timezone("America/Bogota"))

def localize_to_bogota(dt: datetime) -> datetime:
    """
    Asegura que el datetime proporcionado tenga la zona horaria de Bogotá.
    Si 'dt' es naive (sin tzinfo), se asume que está en UTC y se convierte.
    Si ya tiene tzinfo, se convierte a Bogotá.
    """
    bogota_tz = pytz.timezone("America/Bogota")
    if dt is None:
        dt = datetime.utcnow()
    if dt.tzinfo is None:
        # Asumir que el datetime naive está en UTC
        dt = dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(bogota_tz)

def get_next_mandatory_approver(response_id: int, db: Session):
    # Obtener la respuesta
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")

    # Obtener el formulario y el usuario que respondió
    form = response.form
    usuario_respondio = response.user

    # Obtener la plantilla de aprobadores activa
    form_approval_template = (
        db.query(FormApproval)
        .filter(FormApproval.form_id == form.id, FormApproval.is_active == True)
        .order_by(FormApproval.sequence_number)
        .all()
    )

    # Obtener aprobaciones realizadas
    response_approvals = (
        db.query(ResponseApproval)
        .filter(ResponseApproval.response_id == response_id)
        .order_by(ResponseApproval.sequence_number)
        .all()
    )

    # Buscar la última persona que aprobó
    ultima_aprobacion = next(
        (ra for ra in reversed(response_approvals) if ra.status == ApprovalStatus.aprobado),
        None
    )

    siguientes_aprobadores = []
    encontrado_obligatorio = False

    for fa in form_approval_template:
        if not ultima_aprobacion or fa.sequence_number > ultima_aprobacion.sequence_number:
            siguientes_aprobadores.append({
                "nombre": fa.user.name,
                "email": fa.user.email,
                "telefono": fa.user.telephone,
                "secuencia": fa.sequence_number,
                "es_obligatorio": fa.is_mandatory
            })
            if not encontrado_obligatorio and fa.is_mandatory:
                encontrado_obligatorio = True
                break

    # Agregar todos los aprobadores del formato
    todos_los_aprobadores = []
    
    for fa in response_approvals:
        todos_los_aprobadores.append({
            "nombre": fa.user.name,
            "email": fa.user.email,
            "telefono": fa.user.telephone,
            "secuencia": fa.sequence_number,
            "es_obligatorio": fa.is_mandatory,
            "status": fa.status,
            "mensaje": fa.message,
            "reviewed_at": fa.reviewed_at,
        })

    return {
        "formato": {
            "id": form.id,
            "titulo": form.title,
            "descripcion": form.description,
            "tipo_formato": form.format_type.name if form.format_type else None,
            "creado_por": {
                "id": form.user.id,
                "nombre": form.user.name,
                "email": form.user.email
            },

        },
        "usuario_respondio": {
            "id": usuario_respondio.id,
            "nombre": usuario_respondio.name,
            "email": usuario_respondio.email,
            "telefono": usuario_respondio.telephone,
            "num_documento": usuario_respondio.num_document
        },
        "ultima_aprobacion": {
            "nombre": ultima_aprobacion.user.name,
            "email": ultima_aprobacion.user.email,
            "secuencia": ultima_aprobacion.sequence_number,
            "fecha_revision": ultima_aprobacion.reviewed_at,
            "mensaje": ultima_aprobacion.message
        } if ultima_aprobacion else None,
        "siguientes_aprobadores": siguientes_aprobadores,
        "obligatorio_encontrado": encontrado_obligatorio,
        "todos_los_aprobadores": todos_los_aprobadores
    }

def build_email_html_approvers(aprobacion_info: dict) -> str:
    nombre_formato = aprobacion_info["formato"]["titulo"]
    usuario_respondio = aprobacion_info["usuario_respondio"]
    ultima_aprobacion = aprobacion_info.get("ultima_aprobacion")
    todos_aprobadores = aprobacion_info.get("todos_los_aprobadores", [])

    ult_aprobador_html = ""
    if ultima_aprobacion:
        ult_aprobador_html = f"""
        <tr>
            <td colspan="2" style="padding: 15px; background-color: #f0f4f8; border-top: 1px solid #dce3ea;">
                <p style="margin: 0 0 5px;"><strong>Último aprobador:</strong> {ultima_aprobacion['nombre']} ({ultima_aprobacion['email']})</p>
                <p style="margin: 0 0 5px;"><strong>Fecha de revisión:</strong> {ultima_aprobacion['fecha_revision'].strftime('%Y-%m-%d %H:%M') if ultima_aprobacion['fecha_revision'] else 'No disponible'}</p>
                <p style="margin: 0;"><strong>Mensaje:</strong> {ultima_aprobacion['mensaje'] or 'Sin comentarios'}</p>
            </td>
        </tr>
        """

    # Tabla original
    aprobadores_html = ""
    for aprobador in sorted(todos_aprobadores, key=lambda x: x["secuencia"]):
        aprobadores_html += f"""
        <tr>
            <td style="padding: 10px; border: 1px solid #dce3ea;">{aprobador['secuencia']}</td>
            <td style="padding: 10px; border: 1px solid #dce3ea;">{aprobador['nombre']}</td>
            <td style="padding: 10px; border: 1px solid #dce3ea;">{aprobador['email']}</td>
            <td style="padding: 10px; border: 1px solid #dce3ea;">{"Obligatorio" if aprobador['es_obligatorio'] else "Opcional"}</td>
        </tr>
        """

    # Nueva tabla más detallada
    tabla_detallada_html = ""
    for aprobador in sorted(todos_aprobadores, key=lambda x: x["secuencia"]):
        aprobado = "Sí" if aprobador["es_obligatorio"] else "No"
        status = aprobador.get("status", "pendiente")
        estado = status.value.capitalize() if hasattr(status, "value") else str(status).capitalize()
        fecha_revision = aprobador["reviewed_at"]


        tabla_detallada_html += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #dce3ea; text-align: center;">{aprobador['secuencia']}</td>
            <td style="padding: 8px; border: 1px solid #dce3ea;">{aprobador['nombre']}</td>
            <td style="padding: 8px; border: 1px solid #dce3ea;">{aprobador['email']}</td>
            <td style="padding: 8px; border: 1px solid #dce3ea;">{aprobador.get('telefono', 'No disponible')}</td>
            <td style="padding: 8px; border: 1px solid #dce3ea; text-align: center;">{aprobado}</td>
            <td style="padding: 8px; border: 1px solid #dce3ea; text-align: center;">{estado}</td>

        </tr>
        """

    html = f"""
    <html>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7f9fc; padding: 30px; color: #2c3e50;">
        <table width="100%" style="max-width: 800px; margin: auto; background-color: #ffffff; border: 1px solid #dce3ea; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
            <tr>
                <td style="background-color: #002f6c; color: #ffffff; padding: 25px; text-align: center; border-radius: 8px 8px 0 0;">
                    <h2 style="margin: 0;">Proceso de Aprobación - Notificación</h2>
                </td>
            </tr>
            <tr>
                <td style="padding: 25px;">
                    <p style="font-size: 16px; line-height: 1.6;">Estimado/a,</p>

                    <p style="font-size: 16px; line-height: 1.6;">
                        Usted ha sido designado como el próximo <strong>aprobador</strong> en el proceso de revisión del siguiente formato:
                    </p>

                    <p style="font-size: 18px; font-weight: bold; color: #002f6c; margin-top: 10px;">{nombre_formato}</p>

                    <p style="font-size: 15px; margin-top: 20px;"><strong>Formulario completado por:</strong> {usuario_respondio['nombre']} ({usuario_respondio['email']})</p>
                </td>
            </tr>

            {ult_aprobador_html}

            <tr>
                <td style="padding: 25px;">

                    <p style="font-size: 16px;"><strong>Detalles del proceso de aprobación:</strong></p>
                    <table width="100%" style="border-collapse: collapse; font-size: 14px; margin-top: 10px;">
                        <thead>
                            <tr style="background-color: #eef2f7;">
                                <th style="padding: 10px; border: 1px solid #dce3ea;">Secuencia</th>
                                <th style="padding: 10px; border: 1px solid #dce3ea;">Nombre</th>
                                <th style="padding: 10px; border: 1px solid #dce3ea;">Correo</th>
                                <th style="padding: 10px; border: 1px solid #dce3ea;">Teléfono</th>
                                <th style="padding: 10px; border: 1px solid #dce3ea;">¿Obligatorio?</th>
                                <th style="padding: 10px; border: 1px solid #dce3ea;">Estado</th>
                                
                            </tr>
                        </thead>
                        <tbody>
                            {tabla_detallada_html}
                        </tbody>
                    </table>

                    <div style="text-align: center; margin: 30px 0;">
                        <a href="https://forms.sfisas.com.co/" style="display: inline-block; padding: 14px 28px; background-color: #002f6c; color: white; text-decoration: none; border-radius: 5px; font-size: 15px;">
                            Ingresar al Portal de Aprobaciones
                        </a>
                    </div>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    return html


def send_mails_to_next_supporters(response_id: int, db: Session):
    aprobacion_info = get_next_mandatory_approver(response_id=response_id, db=db)
    siguientes = aprobacion_info.get("siguientes_aprobadores", [])

    if not siguientes:
        print("⏳ No hay aprobadores siguientes.")
        return False

    html_content = build_email_html_approvers(aprobacion_info)
    asunto = f"Pendiente aprobación - {aprobacion_info['formato']['titulo']}"

    enviado_todos = True

    for aprobador in siguientes:
        nombre = aprobador["nombre"]
        email = aprobador["email"]
        obligatorio = "Obligatorio" if aprobador["es_obligatorio"] else "Opcional"

        exito = send_email_plain_approval_status_vencidos(
            to_email=email,
            name_form=aprobacion_info["formato"]["titulo"],
            to_name=nombre,
            body_html=html_content,
            subject=asunto
        )

        if not exito:
            enviado_todos = False
            print(f"❌ Falló el envío a {email}")

    return enviado_todos

def send_rejection_email_to_all(response_id: int, db: Session):
    aprobacion_info = get_next_mandatory_approver(response_id=response_id, db=db)
    formato = aprobacion_info["formato"]
    usuario = aprobacion_info["usuario_respondio"]
    aprobadores = aprobacion_info["todos_los_aprobadores"]

    # Encuentra quién lo rechazó
    aprobador_rechazo = next((a for a in aprobadores if a["status"] == ApprovalStatus.rechazado), None)

    if not aprobador_rechazo:
        print("❌ No se encontró aprobador que haya rechazado.")
        return False

    # Lista de correos destino
    correos_destino = []

    # Agregar usuario que respondió
    correos_destino.append({
        "nombre": usuario["nombre"],
        "email": usuario["email"]
    })

    # Agregar aprobadores que no son el que rechazó
    for aprobador in aprobadores:
        if aprobador["email"] != aprobador_rechazo["email"]:
            correos_destino.append({
                "nombre": aprobador["nombre"],
                "email": aprobador["email"]
            })

    # Enviar correo a cada uno
    for destinatario in correos_destino:
        send_rejection_email(
            to_email=destinatario["email"],
            to_name=destinatario["nombre"],
            formato=formato,
            usuario_respondio=usuario,
            aprobador_rechazo=aprobador_rechazo,
            todos_los_aprobadores=aprobadores  # Nuevo parámetro
        )


    return True


def update_response_approval_status(
    response_id: int,
    update_data: UpdateResponseApprovalRequest,
    user_id: int,
    db: Session
):
    # 1. Buscar el ResponseApproval correspondiente
    response_approval = db.query(ResponseApproval).filter(
        ResponseApproval.response_id == response_id,
        ResponseApproval.sequence_number == update_data.selectedSequence
    ).first()
    
    if not response_approval:
        raise HTTPException(status_code=404, detail="ResponseApproval not found")

    response_approval.status = update_data.status
    response_approval.reviewed_at = localize_to_bogota(update_data.reviewed_at or datetime.utcnow())
    response_approval.message = update_data.message
    
    db.commit()
    db.refresh(response_approval)


    if update_data.status == "aprobado":
        send_mails_to_next_supporters(response_id, db)
    elif update_data.status == "rechazado":
        send_rejection_email_to_all(response_id, db)
        
    # 3. Obtener información relacionada
    response = db.query(Response).filter(Response.id == response_id).first()
    form = db.query(Form).filter(Form.id == response.form_id).first()

    form_approval_template = (
        db.query(FormApproval)
        .filter(
            FormApproval.form_id == form.id,
            FormApproval.is_active == True  # Solo los que están activos
        )
        .order_by(FormApproval.sequence_number)
        .all()
    )

    response_approvals = db.query(ResponseApproval).filter(
        ResponseApproval.response_id == response_id
    ).all()

    detener_proceso = False

    for fa in form_approval_template:
        ra = next((r for r in response_approvals if r.user_id == fa.user_id), None)
        status = ra.status.value if ra else "pendiente"
        print(f"  [{fa.sequence_number}] {fa.user.name} - {status}")

        if ra and ra.status == ApprovalStatus.rechazado and fa.is_mandatory:
            print(f"\n⛔ El aprobador '{fa.user.name}' rechazó y su aprobación es obligatoria. El proceso se detiene.")
            detener_proceso = True
            break

    if not detener_proceso:
        faltantes = [fa.user.name for fa in form_approval_template 
                     if not any(ra.user_id == fa.user_id for ra in response_approvals)]
        if faltantes:
            print(f"\n🕓 Aún deben aprobar: {', '.join(faltantes)}")
        else:
            print("\n✅ Todos los aprobadores han completado su revisión.")

    # 5. Notificaciones por correo
    notifications = db.query(FormApprovalNotification).filter(
        FormApprovalNotification.form_id == form.id
    ).all()

    for notification in notifications:
        should_notify = False

        if notification.notify_on == "cada_aprobacion":
            should_notify = True
        elif notification.notify_on == "aprobacion_final":
            todos_aprobaron = all(
                ra.status == ApprovalStatus.aprobado
                for ra in response_approvals
                if any(fa.user_id == ra.user_id for fa in form_approval_template)
            )
            should_notify = todos_aprobaron

        if should_notify:
            user_notify = notification.user
            to_email = user_notify.email
            to_name = user_notify.name

            # ✉️ Cuerpo del correo
            contenido = f"""📄 --- Proceso de Aprobación ---
Formulario: {form.title} (Formato: {form.format_type.value})
Respondido por: {response.user.name} (ID: {response.user.id})
Aprobación por: {response_approval.user.name}
Secuencia: {response_approval.sequence_number}
Estado: {response_approval.status.value}
Fecha de revisión: {response_approval.reviewed_at.isoformat()}
Mensaje: {response_approval.message or '-'}

🧾 Estado de aprobadores:
"""

            for fa in form_approval_template:
                ra = next((r for r in response_approvals if r.user_id == fa.user_id), None)
                status = ra.status.value if ra else "pendiente"
                contenido += f"[{fa.sequence_number}] {fa.user.name} - {status}\n"

            
            send_email_plain_approval_status(
                to_email=to_email,
                name_form=form.title,
                to_name=user_notify.name,
                body_text=contenido,
                subject=f"Proceso de aprobación - {form.title}"  # Aquí pasas el subject
            )

    return response_approval


def get_response_approval_status(response_approvals: list) -> dict:
    """
    Determina el estado de aprobación de una respuesta de formulario basada en la lista de aprobaciones.

    Args:
        response_approvals (list): Lista de objetos de tipo `ResponseApproval`.

    Returns:
        dict: Diccionario con el estado (`status`) y mensaje (`message`) correspondiente.

    Lógica de evaluación:
    - Si hay alguna aprobación con estado `rechazado`, se devuelve ese estado y mensaje.
    - Si alguna aprobación obligatoria está pendiente, el estado será `pendiente`.
    - Si todas las aprobaciones necesarias están completadas, el estado será `aprobado`.
    """
    has_rejected = None
    pending_mandatory = False
    messages = []
    pending_users = []

    for approval in response_approvals:
        if approval.message:
            messages.append(approval.message)

        if approval.status == ApprovalStatus.rechazado:
            has_rejected = approval
            break

        if approval.is_mandatory and approval.status != ApprovalStatus.aprobado:
            pending_mandatory = True
            pending_users.append({
                "user_id": approval.user_id,
                "sequence_number": approval.sequence_number,
                "status": approval.status
            })

    if has_rejected:
        return {
            "status": "rechazado",
            "message": has_rejected.message or "Formulario rechazado"
        }

    if pending_mandatory:
        print("Faltan por aprobar los siguientes usuarios obligatorios:")
        for user in pending_users:
            print(f"- User ID: {user['user_id']}, Secuencia: {user['sequence_number']}, Estado: {user['status'].value}")
        return {
            "status": "pendiente",
            "message": "Faltan aprobaciones obligatorias"
        }

    return {
        "status": "aprobado",
        "message": " | ".join(filter(None, messages))
    }


def get_form_with_full_responses(form_id: int, db: Session):
    form = db.query(Form).options(
        joinedload(Form.questions),
        joinedload(Form.responses).joinedload(Response.user),
    ).filter(Form.id == form_id).first()

    if not form:
        return None

    results = {
        "form_id": form.id,
        "title": form.title,
        "description": form.description,
        "questions": [
            {
                "id": q.id,
                "text": q.question_text,
                "type": q.question_type.name,
            }
            for q in form.questions
        ],
        "responses": [],
    }

    for response in form.responses:
        response_data = {
            "response_id": response.id,
            "user": {
                "id": response.user.id,
                "name": response.user.name,
                "email": response.user.email,
                "num_document": response.user.num_document,
            },
            "submitted_at": response.submitted_at,
            "answers": [],
            "approval_status": None,  # Aquí se agregará
        }

        # Obtener respuestas
        answers = (
            db.query(Answer)
            .options(joinedload(Answer.question))
            .filter(Answer.response_id == response.id)
            .all()
        )

        for ans in answers:
            response_data["answers"].append({
                "question_id": ans.question.id,
                "question_text": ans.question.question_text,
                "answer_text": ans.answer_text,
                "file_path": ans.file_path,
            })

        # Obtener aprobaciones y calcular estado
        approvals = db.query(ResponseApproval).filter_by(response_id=response.id).all()
        approval_info = get_response_approval_status(approvals)
        response_data["approval_status"] = approval_info

        results["responses"].append(response_data)

    return results


def update_form_design_service(db: Session, form_id: int, design_data: List[Dict[str, Any]]):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    form.form_design = design_data  # guarda la lista completa
    db.commit()
    db.refresh(form)

    return form


def get_notifications_for_form(form_id: int, db: Session):
    # Verifica si el formulario existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")

    # Obtiene las notificaciones asociadas a este formulario
    notifications = (
        db.query(FormApprovalNotification)
        .filter(FormApprovalNotification.form_id == form_id)
        .options(joinedload(FormApprovalNotification.user))  # Cargar los usuarios relacionados
        .all()
    )

    # Prepara las notificaciones y usuarios para la respuesta
    return [
    NotificationResponse(
        id=notification.id,  # ← Aquí ahora incluimos el ID
        notify_on=notification.notify_on,
        user=UserBase(
            id=notification.user.id,
            name=notification.user.name,
            email=notification.user.email,
            num_document=notification.user.num_document,
            telephone=notification.user.telephone
        )
    )
    for notification in notifications
]


def update_notification_status(notification_id: int, notify_on: str, db: Session):
    """
    Actualiza el valor de 'notify_on' de una notificación específica.

    Args:
        notification_id (int): ID de la notificación.
        notify_on (str): Nuevo valor para el campo 'notify_on'.
        db (Session): Sesión de la base de datos.

    Returns:
        FormApprovalNotification: La notificación actualizada.
    """
    valid_options = ["cada_aprobacion", "aprobacion_final"]
    if notify_on not in valid_options:
        raise HTTPException(status_code=400, detail=f"Opción no válida. Las opciones válidas son: {valid_options}")

    notification = db.query(FormApprovalNotification).filter(FormApprovalNotification.id == notification_id).first()

    if not notification:
        raise HTTPException(status_code=404, detail="Notificación no encontrada.")

    notification.notify_on = notify_on
    db.commit()
    db.refresh(notification)

    return notification
def delete_form(db: Session, form_id: int):
    """
    Elimina un formulario y todos sus registros relacionados, incluyendo respuestas si existen.
    """
    form = db.query(Form).filter(Form.id == form_id).first()

    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Formulario no encontrado."
        )

    try:
        # Obtener todos los response_ids relacionados con el formulario
        response_ids = db.query(Response.id).filter(Response.form_id == form_id).all()
        response_ids = [r.id for r in response_ids]

        if response_ids:
            db.query(ResponseApproval).filter(ResponseApproval.response_id.in_(response_ids)).delete(synchronize_session=False)

            db.query(Answer).filter(Answer.response_id.in_(response_ids)).delete(synchronize_session=False)

            db.query(Response).filter(Response.id.in_(response_ids)).delete(synchronize_session=False)

        db.query(QuestionFilterCondition).filter(QuestionFilterCondition.form_id == form_id).delete(synchronize_session=False)

        db.query(FormAnswer).filter(FormAnswer.form_id == form_id).delete(synchronize_session=False)
        db.query(FormApproval).filter(FormApproval.form_id == form_id).delete(synchronize_session=False)
        db.query(FormApprovalNotification).filter(FormApprovalNotification.form_id == form_id).delete(synchronize_session=False)
        db.query(FormSchedule).filter(FormSchedule.form_id == form_id).delete(synchronize_session=False)
        db.query(FormModerators).filter(FormModerators.form_id == form_id).delete(synchronize_session=False)
        db.query(FormQuestion).filter(FormQuestion.form_id == form_id).delete(synchronize_session=False)

        db.delete(form)
        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ocurrió un error al eliminar el formulario: {str(e)}"
        )


    return {"message": "Formulario, respuestas y registros relacionados eliminados correctamente."}

def get_response_details_logic(db: Session):
    responses = db.query(Response).all()

    if not responses:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontraron respuestas pendientes."
        )

    fecha_actual = datetime.now()
    resultados = []

    # Diccionario para acumular aprobaciones vencidas por formulario
    aprobaciones_globales = defaultdict(list)

    for response in responses:
        dias_transcurridos = (fecha_actual - response.submitted_at).days

        response_approvals = (
            db.query(ResponseApproval)
            .filter(ResponseApproval.response_id == response.id)
            .order_by(ResponseApproval.sequence_number)
            .all()
        )

        result = {
            "response_id": response.id,
            "dias_transcurridos": dias_transcurridos,
            "formato": {
                "nombre": response.form.title if response.form else None,
                "descripcion": response.form.description if response.form else None
            },
            "aprobaciones": []
        }

        acumulado_deadline = 0
        rechazo_encontrado = False

        # Obtener info del usuario creador
        user_creator_info = db.query(User).filter(User.id == response.user_id).first()

        for approval in response_approvals:
            if approval.status == ApprovalStatus.rechazado:
                rechazo_encontrado = True

            form_approval = (
                db.query(FormApproval)
                .filter(
                    FormApproval.form_id == response.form_id,
                    FormApproval.user_id == approval.user_id,
                    FormApproval.sequence_number == approval.sequence_number,
                    FormApproval.is_active == True
                )
                .first()
            )

            if form_approval:
                acumulado_deadline += form_approval.deadline_days

            if rechazo_encontrado or approval.status != ApprovalStatus.pendiente:
                continue

            # Info del aprobador
            user_approver_info = db.query(User).filter(User.id == approval.user_id).first()

            plazo_vencido = dias_transcurridos > acumulado_deadline
            
            # Solo añadir si venció ayer (exactamente un día)
            if plazo_vencido and (dias_transcurridos - acumulado_deadline) == 1:
                data = {
                    "id": approval.id,
                    "sequence_number": approval.sequence_number,
                    "status": approval.status,
                    "reviewed_at": approval.reviewed_at,
                    "is_mandatory": approval.is_mandatory,
                    "message": approval.message,
                    "deadline_days": form_approval.deadline_days if form_approval else None,
                    "deadline_acumulado": acumulado_deadline,
                    "plazo_vencido": plazo_vencido,
                    "creador": {
                        "id": user_creator_info.id,
                        "num_document": user_creator_info.num_document,
                        "name": user_creator_info.name,
                        "email": user_creator_info.email,
                        "telephone": user_creator_info.telephone,
                        "nickname": user_creator_info.nickname
                    } if user_creator_info else None,
                    "aprobador": {
                        "id": user_approver_info.id,
                        "num_document": user_approver_info.num_document,
                        "name": user_approver_info.name,
                        "email": user_approver_info.email,
                        "telephone": user_approver_info.telephone,
                        "nickname": user_approver_info.nickname
                    } if user_approver_info else None
                }
                result["aprobaciones"].append(data)
                aprobaciones_globales[response.form.title].append(data)

        resultados.append(result)

    if aprobaciones_globales:
        enviar_correo_aprobaciones_vencidas_consolidado(aprobaciones_globales, db)

    return resultados


def enviar_correo_aprobaciones_vencidas_consolidado(aprobaciones_globales: dict, db: Session):
    """
    Envía un único correo con todas las aprobaciones vencidas del día, agrupadas por formulario.
    """
    # Consultar correos activos de la base de datos
    correos_activos = db.query(EmailConfig.email_address).filter(EmailConfig.is_active == True).all()
    lista_correos = [correo[0] for correo in correos_activos]

    # Contenido del HTML
    html_content = """
    <html>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f4; margin: 0; padding: 30px;">
        <div style="background-color: #ffffff; border-radius: 6px; padding: 25px; max-width: 850px; margin: auto; 
                    box-shadow: 0 3px 15px rgba(0, 0, 0, 0.1);">
            <h2 style="color: #2c3e50; margin-bottom: 25px; text-align: center; font-weight: 700;">Alerta de Aprobaciones Vencidas</h2>
            <p style="font-size: 16px; color: #34495e; text-align: center; margin-bottom: 35px;">
                Las siguientes aprobaciones han vencido.
            </p>
    """

    for form_name, aprobaciones in aprobaciones_globales.items():
        html_content += f"""
        <h3 style="color: #2c3e50; margin-top: 40px; border-bottom: 2px solid #00498C; padding-bottom: 8px;">Formulario: {form_name}</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px;">
            <thead>
                <tr style="background-color: #00498C; color: white; text-align: left;">
                    <th style="padding: 12px; border: 1px solid #ddd;">Persona que llenó el formulario</th>
                    <th style="padding: 12px; border: 1px solid #ddd;">Persona que aprueba</th>
                    <th style="padding: 12px; border: 1px solid #ddd;">Correo del aprobador</th>
                    <th style="padding: 12px; border: 1px solid #ddd;">Días de plazo</th>
                    <th style="padding: 12px; border: 1px solid #ddd;">Fecha límite</th>
                </tr>
            </thead>
            <tbody>
        """

        for index, approval in enumerate(aprobaciones):
            creador = approval.get("creador") or {}
            aprobador = approval.get("aprobador") or {}
            fecha_limite = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
            background = "#ecf0f1" if index % 2 == 0 else "#ffffff"

            html_content += f"""
            <tr style="background-color: {background};">
                <td style="padding: 12px; border: 1px solid #ddd;">{creador.get('name', 'N/A')}</td>
                <td style="padding: 12px; border: 1px solid #ddd;">{aprobador.get('name', 'N/A')}</td>
                <td style="padding: 12px; border: 1px solid #ddd;"><a href="mailto:{aprobador.get('email', '')}" style="color: #00498C; text-decoration: none;">{aprobador.get('email', 'N/A')}</a></td>
                <td style="padding: 12px; border: 1px solid #ddd; text-align: center;">{approval['deadline_days']}</td>
                <td style="padding: 12px; border: 1px solid #ddd; text-align: center;">{fecha_limite}</td>
            </tr>
            """

        html_content += """
            </tbody>
        </table>
        """

    html_content += """

        </div>
    </body>
    </html>
    """

    # Asunto del correo
    asunto = "Alerta de Aprobaciones Vencidas"

    # Enviar el correo a cada uno de los correos activos
    for email in lista_correos:
        send_email_plain_approval_status_vencidos(email, "Consolidado", "Admin", html_content, asunto)
        
def create_email_config(db: Session, email_config: EmailConfigCreate):
    db_email = EmailConfig(
        email_address=email_config.email_address,
        is_active=email_config.is_active
    )
    db.add(db_email)
    db.commit()
    db.refresh(db_email)
    return db_email

def get_all_email_configs(db: Session):
    return db.query(EmailConfig).all()