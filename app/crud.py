import json
import os
from sqlalchemy import exists, func, not_, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from app import models
from app.api.controllers.mail import send_email_daily_forms, send_email_with_attachment, send_welcome_email
from app.core.security import hash_password
from app.models import  FormAnswer, FormModerators, FormSchedule, Project, QuestionTableRelation, QuestionType, User, Form, Question, Option, Response, Answer, FormQuestion
from app.schemas import FormBaseUser, ProjectCreate, UserBaseCreate, UserCreate, FormCreate, QuestionCreate, OptionCreate, ResponseCreate, AnswerCreate, UserType, UserUpdate, QuestionUpdate, UserUpdateInfo
from fastapi import HTTPException, UploadFile, status
from typing import List, Optional
from datetime import datetime

import os
import secrets
import string


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
    form = db.query(Form).options(
        joinedload(Form.questions).joinedload(Question.options),
        joinedload(Form.responses).joinedload(Response.answers)
    ).filter(Form.id == form_id).first()

    if not form:
        return None

    if form.format_type.name in ['abierto', 'semi_abierto']:
        form.responses = [resp for resp in form.responses if resp.user_id == user_id]
    else:
        form.responses = []  

    return form



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
        db_form = db.query(Form).filter(Form.id == form_id).first()
        if not db_form:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

        # Obtener los IDs de las preguntas actualmente asociadas
        current_question_ids = {fq.question_id for fq in db_form.questions}

        # Calcular las preguntas nuevas que se deben asociar
        new_question_ids = set(question_ids) - current_question_ids

        # Si no hay preguntas nuevas para añadir, salir
        if not new_question_ids:
            return db_form

        # Filtrar preguntas nuevas que existen en la base de datos
        new_questions = db.query(Question).filter(Question.id.in_(new_question_ids)).all()

        # Verificar que todas las preguntas nuevas existen
        if len(new_questions) != len(new_question_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more questions not found"
            )

        # Crear instancias de FormQuestion para añadir en masa
        form_questions = [FormQuestion(form_id=form_id, question_id=question.id) for question in new_questions]

        # Añadir todas las nuevas relaciones en una sola operación
        db.bulk_save_objects(form_questions)

        db.commit()
        db.refresh(db_form)
        return db_form
    except IntegrityError:
        db.rollback()
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



def delete_question_from_db(question_id: int, db: Session):
    """ Elimina una pregunta si no tiene relaciones con otras tablas. """
    question = db.query(Question).filter(Question.id == question_id).first()

    if not question:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")

    # Verificar si tiene relaciones con otras tablas
    if question.forms or question.options or question.answers:
        raise HTTPException(status_code=400, detail="No se puede eliminar porque está relacionada con otros datos")

    # Eliminar la pregunta
    db.delete(question)
    db.commit()
    return {"message": "Pregunta eliminada correctamente"}

def post_create_response(db: Session, form_id: int, user_id: int, mode: str = "online"):
    """Función para crear una nueva respuesta en la base de datos si la encuesta y el usuario existen."""

    form = db.query(Form).filter(Form.id == form_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Contador separado por modo
    last_mode_response = (
        db.query(Response)
        .filter(Response.mode == mode)
        .order_by(Response.mode_sequence.desc())
        .first()
    )

    new_mode_sequence = last_mode_response.mode_sequence + 1 if last_mode_response else 1

    response = Response(
        form_id=form_id,
        user_id=user_id,
        mode=mode,
        mode_sequence=new_mode_sequence,
        submitted_at=func.now()
    )

    db.add(response)
    db.commit()
    db.refresh(response)

    return {
        "message": "Nueva respuesta guardada exitosamente",
        "response_id": response.id,
        "mode": mode,
        "mode_sequence": new_mode_sequence
    }

def create_answer_in_db(answer, db: Session):
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
    print(new_answer.response_id)
    db.add(new_answer)
    existing_answer = new_answer
    message = "Respuesta guardada exitosamente"

    db.commit()
    db.refresh(existing_answer)

    return {"message": message, "answer_id": existing_answer.id}

def check_form_data(db: Session, form_id: int):
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


def create_form_schedule(db: Session, form_id: int, user_id: int, repeat_days: list | None, status: bool):
    # Verificar si ya existe un registro con esa combinación
    existing_schedule = db.query(FormSchedule).filter_by(form_id=form_id, user_id=user_id).first()

    if existing_schedule:
        # Si existe, actualiza el registro
        existing_schedule.repeat_days = json.dumps(repeat_days) if repeat_days else None
        existing_schedule.status = status
        db.commit()
        db.refresh(existing_schedule)
        return existing_schedule
    else:
        # Si no existe, crea uno nuevo
        new_schedule = FormSchedule(
            form_id=form_id,
            user_id=user_id,
            repeat_days=json.dumps(repeat_days) if repeat_days else None,
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
    # Realiza la consulta a la base de datos y devuelve los registros como diccionarios
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
    # Consulta todos los formularios relacionados con el user_id a través de la tabla form_moderators
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
    # Obtener los formularios que ya han sido completados por el usuario
    completed_forms = (
        db.query(Form)
        .join(Response)  # Unión entre formularios y respuestas
        .filter(Response.user_id == user_id)  # Filtrar por el usuario
        .distinct()  # Evitar duplicados si hay múltiples respuestas a un mismo formulario
        .all()
    )
    return completed_forms


def fetch_form_questions(form_id: int, db: Session):
    """Obtiene las preguntas asociadas y no asociadas a un formulario."""
    # Obtener todas las preguntas del sistema
    all_questions = db.query(Question).all()

    # Obtener el formulario y verificar si existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    # Obtener IDs de las preguntas asociadas al formulario
    associated_questions_ids = {q.id for q in form.questions}

    # Separar preguntas en asociadas y no asociadas
    associated_questions = [q for q in all_questions if q.id in associated_questions_ids]
    unassociated_questions = [q for q in all_questions if q.id not in associated_questions_ids]

    return {
        "associated_questions": associated_questions,
        "unassociated_questions": unassociated_questions
    }
    

def link_question_to_form(form_id: int, question_id: int, db: Session):
    """Asocia una pregunta a un formulario en la tabla FormQuestion."""
    
    # Verificar si el formulario existe
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
    """Obtiene los usuarios asociados y no asociados a un formulario."""
    
    # Verificar si el formulario existe
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
    """Asocia un usuario como moderador de un formulario en la tabla FormModerators."""
    
    # Verificar si el formulario existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    # Verificar si el usuario existe
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
    """Elimina una pregunta de un formulario en la tabla FormQuestion."""
    
    # Buscar la relación en FormQuestion
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


def get_schedules_by_day(db: Session, day: str) -> List[dict]:
    schedules = db.query(FormSchedule).filter(FormSchedule.status == True).all()
    users_forms = {}

    for schedule in schedules:
        if schedule.repeat_days and day in json.loads(schedule.repeat_days):
            user = db.query(User).filter(User.id == schedule.user_id).first()
            form = db.query(Form).filter(Form.id == schedule.form_id).first()

            if user and form:
                if user.email not in users_forms:
                    users_forms[user.email] = {
                        "user_name": user.name,
                        "forms": []
                    }

                users_forms[user.email]["forms"].append({
                    "title": form.title,
                    "description": form.description or "Sin descripción"
                })

    # Enviar un email a cada usuario con sus formularios
    for email, data in users_forms.items():
        send_email_daily_forms(
            user_email=email,
            user_name=data["user_name"],
            forms=data["forms"]
        )

    return [
        {
            "id": schedule.id,
            "form": {
                "id": form.id,
                "title": form.title,
                "description": form.description
            } if form else None,
            "user": {
                "id": user.id,
                "num_document": user.num_document,
                "name": user.name,
                "email": user.email,
                "telephone": user.telephone,
                "nickname": user.nickname
            } if user else None,
            "repeat_days": json.loads(schedule.repeat_days),
            "status": schedule.status
        }
        for schedule in schedules
        if schedule.repeat_days and day in json.loads(schedule.repeat_days)
    ]

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



def get_related_answers_logic(db: Session, question_id: int):
    # Verificar si existe una relación para la pregunta
    relation = db.query(QuestionTableRelation).filter_by(question_id=question_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="No relation found for this question")

    # Si tiene related_question_id, buscar answers relacionadas
    if relation.related_question_id:
        answers = db.query(Answer).filter_by(question_id=relation.related_question_id).all()
        return {
            "source": "pregunta_relacionada",
            "related_question_id": relation.related_question_id,
            "respuestas": [
                {
    
                    "respuesta": ans.answer_text
                }
                for ans in answers
            ]
        }

    # Si no tiene related_question_id, usar tabla y campo especificados
    name_table = relation.name_table
    field_name = relation.field_name  # Nuevo: nombre del campo a traer

    # Modelos válidos
    valid_tables = {
        "answers": Answer,
        "users": User,
        "forms": Form,
        "options": Option,
        # Agrega más modelos si es necesario
    }

    # Traducciones de nombre de tabla
    table_translations = {
        "users": "usuarios",
        "forms": "formularios",
        "answers": "respuestas",
        "options": "opciones"
    }

    Model = valid_tables.get(name_table)
    if not Model:
        raise HTTPException(status_code=400, detail=f"Table '{name_table}' is not supported")

    # Validar que el campo exista en el modelo
    if not hasattr(Model, field_name):
        raise HTTPException(status_code=400, detail=f"Field '{field_name}' does not exist in model '{name_table}'")

    results = db.query(Model).all()

    # Serialización con id y campo específico
    def serialize(instance):
        return {
            field_name: getattr(instance, field_name, None)
        }

    return {
        "source": table_translations.get(name_table, name_table),
        "data": [serialize(r) for r in results]
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
            "Fecha de Envío": response.submitted_at.strftime("%Y-%m-%d %H:%M:%S")
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
    for response in responses:
        row = {
            "Nombre": response.user.name,
            "Documento": response.user.num_document,
            "Fecha de Envío": response.submitted_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for question in questions:
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
