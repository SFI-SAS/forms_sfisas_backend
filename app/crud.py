import asyncio
import base64
from collections import defaultdict
from io import BytesIO
import json
import os
import threading
import pytz
from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import Session, joinedload, defer
from sqlalchemy.exc import IntegrityError
from app import models
from app.api.controllers.mail import send_action_notification_email, send_email_aprovall_next, send_email_daily_forms, send_email_plain_approval_status, send_email_plain_approval_status_vencidos, send_email_with_attachment, send_rejection_email, send_welcome_email
from app.api.endpoints.pdf_router import generate_pdf_from_form_id
from app.core.security import hash_password
from app.models import  AnswerFileSerial, AnswerHistory, ApprovalRequirement, ApprovalStatus, BitacoraLogsSimple, EmailConfig, EstadoEvento, FormAnswer, FormApproval, FormApprovalNotification, FormCategory, FormCloseConfig, FormModerators, FormSchedule, PalabrasClave, Project, QuestionAndAnswerBitacora, QuestionFilterCondition, QuestionLocationRelation, QuestionTableRelation, QuestionType, RelationBitacora, ResponseApproval, ResponseApprovalRequirement, ResponseStatus, User, Form, Question, Option, Response, Answer, FormQuestion, UserCategory
from app.schemas import BitacoraLogsSimpleCreate, EmailConfigCreate, FormApprovalCreateSchema, FormBaseUser, FormCategoryCreate, FormCategoryMove, FormCategoryResponse, FormCategoryTreeResponse, FormCategoryUpdate, NotificationResponse, PalabrasClaveCreate, PostCreate, ProjectCreate, ResponseApprovalCreate, UpdateResponseApprovalRequest, UserBase, UserBaseCreate, UserCategoryCreate, UserCreate, FormCreate, QuestionCreate, OptionCreate, ResponseCreate, AnswerCreate, UserType, UserUpdate, QuestionUpdate, UserUpdateInfo
from fastapi import HTTPException, UploadFile, status
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from app.models import ApprovalStatus  # Asegúrate de importar esto
from cryptography.fernet import Fernet

import os
import secrets
import string

import random


ENCRYPTION_KEY = 'OugiYqGaXdQElq1G5UtKD/jVwk4r/J041p9J7dHOFGo='
# ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
cipher_suite = Fernet(ENCRYPTION_KEY)

def encrypt_object(data: Any) -> str:
    """
    Encripta cualquier objeto serializable (dict, list, etc.) y retorna un string.
    """
    try:
        json_string = json.dumps(data, ensure_ascii=False)
        json_bytes = json_string.encode('utf-8')
        encrypted_data = cipher_suite.encrypt(json_bytes)
        encrypted_string = base64.b64encode(encrypted_data).decode('utf-8')
        return encrypted_string
        
    except json.JSONEncodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: Los datos no se pueden serializar a JSON - {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error encriptando datos: {str(e)}"
        )

        
def decrypt_object(encrypted_string: str) -> Any:
    """
    Desencripta un string y retorna el objeto original.
    
    Proceso paso a paso (inverso a la encriptación):
    1. Decodifica el string base64 a bytes
    2. Desencripta los bytes usando Fernet
    3. Convierte los bytes a string JSON
    4. Deserializa el JSON al objeto Python original
    
    Parámetros:
    -----------
    encrypted_string : str
        String encriptado en base64 (resultado de encrypt_object)
        
    Retorna:
    --------
    Any
        El objeto Python original exactamente como era antes de encriptar
        

    """
    try:
        # PASO 1: Decodificar base64 a bytes
        encrypted_data = base64.b64decode(encrypted_string.encode('utf-8'))
        
        # PASO 2: Desencriptar usando Fernet
        decrypted_bytes = cipher_suite.decrypt(encrypted_data)
        
        # PASO 3: Convertir bytes a string JSON
        json_string = decrypted_bytes.decode('utf-8')
        
        # PASO 4: Deserializar JSON al objeto Python original
        original_data = json.loads(json_string)
        
        return original_data
        
    except base64.binascii.Error as e:
        # Error al decodificar base64
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: Datos base64 inválidos - {str(e)}"
        )
    except Exception as e:
        # Error de desencriptación (clave incorrecta, datos corruptos, etc.)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error desencriptando datos: {str(e)}"
        )

def generate_nickname(name: str) -> str:
    parts = name.split()
    if len(parts) == 1:
        return (parts[0][0] + parts[0][-1]).upper()  # Primera y última letra del único nombre en mayúsculas
    elif len(parts) >= 2:
        return (parts[0][0] + parts[0][-1] + parts[1][0] + parts[1][-1]).upper()  # Primer y última letra de los dos primeros nombres o palabras en mayúsculas
    return ""  # En caso de un string vacío (no debería pasar)

# User CRUD Operations
def create_user(db: Session, user: UserCreate):
    """
    Crea un nuevo usuario en la base de datos.

    Esta función genera un nickname a partir del nombre, encripta la contraseña 
    (ya debe estar encriptada antes de llamar a esta función), y almacena el nuevo
    usuario en la base de datos.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    user : UserCreate
        Datos del usuario a registrar.

    Retorna:
    --------
    User
        Objeto del usuario recién creado.

    Lanza:
    ------
    HTTPException 400:
        Si el correo electrónico ya está registrado (conflicto de integridad).
    """
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

        # Crear el formulario base, incluyendo la categoría
        db_form = Form(
            user_id=user_id,
            title=form.title,
            description=form.description,
            format_type=form.format_type,
            id_category=form.id_category,  # ← Añadido aquí
            created_at=datetime.utcnow()
        )

        # Crear relaciones con FormModerators para los usuarios asignados
        for assigned_user_id in form.assign_user:
            db_form.form_moderators.append(FormModerators(user_id=assigned_user_id))

        db.add(db_form)
        db.commit()
        db.refresh(db_form)

        # Crear y devolver la respuesta
        response = {
            "id": db_form.id,
            "user_id": db_form.user_id,
            "title": db_form.title,
            "description": db_form.description,
            "format_type": db_form.format_type.value,
            "created_at": db_form.created_at,
            "id_category": db_form.id_category,  # ← Incluir en la respuesta
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
    # Cargar el formulario con preguntas y respuestas
    form = db.query(Form).options(
        joinedload(Form.questions).joinedload(Question.options),
        joinedload(Form.responses).joinedload(Response.answers)
    ).filter(Form.id == form_id).first()

    if not form:
        return None

    # Filtrar respuestas según el tipo de formato
    if form.format_type.name in ['abierto', 'semi_abierto']:
        form.responses = [resp for resp in form.responses if resp.user_id == user_id]
    else:
        form.responses = []

    questions_data = []

    for question in form.questions:
        form_answer = db.query(FormAnswer).filter(
            FormAnswer.form_id == form_id,
            FormAnswer.question_id == question.id
        ).first()
        is_repeated = form_answer.is_repeated if form_answer else False

        question_dict = {
            "id": question.id,
            "required": question.required,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "root": question.root,
            "options": [
                {"id": option.id, "option_text": option.option_text}
                for option in question.options
            ],
            "is_repeated": is_repeated
        }

        # Si es tipo location, aplicar lógica extendida
        if question.question_type == "location":
            relation = db.query(QuestionLocationRelation).filter_by(
                form_id=form_id,
                origin_question_id=question.id
            ).first()

            if relation:
                target_question_id = relation.target_question_id

                # Buscar todas las respuestas al target_question_id
                target_answers = db.query(Answer).filter(
                    Answer.question_id == target_question_id
                ).all()

                # Agrupar por response_id y buscar todas las respuestas asociadas a ese formulario
                related_data = []
                seen_response_ids = set()

                for ans in target_answers:
                    response = db.query(Response).filter(Response.id == ans.response_id).first()
                    if not response or response.id in seen_response_ids:
                        continue  # evitar duplicados
                    seen_response_ids.add(response.id)

                    # Buscar todas las preguntas de ese formulario
                    form_question_ids = db.query(FormQuestion.question_id).filter(
                        FormQuestion.form_id == response.form_id
                    ).all()
                    form_question_ids = [fq[0] for fq in form_question_ids]

                    # Obtener todas las respuestas del response actual
                    all_answers = db.query(Answer).filter(
                        Answer.response_id == response.id,
                        Answer.question_id.in_(form_question_ids)
                    ).all()

                    related_data.append({
                        "response_id": response.id,
                        "form_id": response.form_id,
                        "answers": [
                            {
                                "question_id": a.question_id,
                                "answer_text": a.answer_text
                            } for a in all_answers
                        ]
                    })

                question_dict["related_answers"] = related_data

        questions_data.append(question_dict)

    # Función auxiliar para procesar respuestas de reconocimiento facial
    def process_regisfacial_answer(answer_text, question_type):
        """
        Procesa las respuestas de tipo regisfacial para mostrar un texto descriptivo
        del registro facial guardado en lugar del JSON completo de faceData
        """
        if question_type != "regisfacial" or not answer_text:
            return answer_text
        
        try:
            # Debug: imprimir el contenido original
            print(f"DEBUG - Processing regisfacial answer: {answer_text}")
            print(f"DEBUG - Question type: {question_type}")
            
            # Intentar parsear el JSON
            face_data = json.loads(answer_text)
            print(f"DEBUG - Parsed JSON: {face_data}")
            
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
            
            print(f"DEBUG - Extracted - success: {success}, person_name: {person_name}")
            
            if success:
                result = f"Datos biométricos de {person_name} registrados"
            else:
                result = f"Error en el registro de datos biométricos de {person_name}"
            
            print(f"DEBUG - Final result: {result}")
            return result
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"DEBUG - Exception: {e}")
            # Si hay error al parsear JSON, devolver un mensaje genérico
            return "Datos biométricos procesados"

    # Crear un diccionario de tipos de pregunta por question_id para referencia rápida
    question_types_map = {q.id: q.question_type for q in form.questions}

    # Respuestas del usuario (si corresponde)
    responses_data = []
    for response in form.responses:
        response_dict = {
            "id": response.id,
            "user_id": response.user_id,
            "answers": []
        }
        
        for answer in response.answers:
            # Obtener el tipo de pregunta para esta respuesta
            question_type = question_types_map.get(answer.question_id, "text")
            
            # Procesar la respuesta según el tipo de pregunta
            processed_answer_text = process_regisfacial_answer(answer.answer_text, question_type)
            
            response_dict["answers"].append({
                "id": answer.id,
                "question_id": answer.question_id,
                "answer_text": processed_answer_text
            })
        
        responses_data.append(response_dict)

    return {
        "id": form.id,
        "description": form.description,
        "created_at": form.created_at.isoformat(),
        "user_id": form.user_id,
        "title": form.title,
        "format_type": form.format_type.name,
        "form_design": form.form_design,
        "questions": questions_data,
        "responses": responses_data
    }
    
    
    
def get_forms(db: Session, skip: int = 0, limit: int = 10):
    return db.query(Form).offset(skip).limit(limit).all()

# Question CRUD Operations
def create_question(db: Session, question: QuestionCreate):
    try:
        db_question = Question(
            question_text=question.question_text,
            question_type=question.question_type,
            required=question.required, 
            root=question.root,
            id_category=question.id_category  # <-- Aquí lo agregas
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

def get_question_by_id_with_category(db: Session, question_id: int):
    """
    Obtiene una pregunta específica por su ID con su categoría relacionada.
    """
    return db.query(Question).options(joinedload(Question.category)).filter(Question.id == question_id).first()

def get_questions(db: Session):
    return db.query(Question).options(joinedload(Question.category)).all()

def get_questions_by_category_id(db: Session, category_id: Optional[int]):
    """
    Obtiene preguntas filtradas por categoría desde la base de datos.
    
    Parámetros:
    -----------
    db : Session
        Sesión de base de datos.
    category_id : Optional[int]
        ID de la categoría. Si es None, filtra por preguntas sin categoría.
    
    Retorna:
    --------
    List[Question]:
        Lista de preguntas filtradas.
    """
    query = db.query(Question).options(joinedload(Question.category))
    
    if category_id is None:
        # Traer preguntas sin categoría (id_category es null)
        questions = query.filter(Question.id_category == None).all()
    else:
        # Traer preguntas de la categoría específica
        questions = query.filter(Question.id_category == category_id).all()
    
    return questions

def update_question(db: Session, question_id: int, question: QuestionUpdate) -> Question:
    """
    Actualiza los campos de una pregunta en la base de datos.

    Solo se modifican los campos que están presentes en el objeto `question`.

    Parámetros:
    -----------
    db : Session
        Sesión de base de datos activa.

    question_id : int
        ID de la pregunta que se desea modificar.

    question : QuestionUpdate
        Datos nuevos para la pregunta (pueden ser parciales).

    Retorna:
    --------
    Question:
        Instancia actualizada de la pregunta.

    Lanza:
    ------
    HTTPException:
        - 400: Si ocurre un error de integridad al intentar actualizar.
    """
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
    """
    Crea varias opciones de respuesta en la base de datos.

    Parámetros:
    -----------
    db : Session
        Sesión activa de base de datos.

    options : List[OptionCreate]
        Lista de opciones con datos para ser insertadas en la tabla de opciones.

    Retorna:
    --------
    List[Option]:
        Lista de objetos `Option` creados en la base de datos.

    Lanza:
    ------
    HTTPException:
        - 400: Si ocurre un error al insertar las opciones.
    """
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
    """
    Crea un nuevo proyecto en la base de datos.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    project_data : ProjectCreate
        Datos del proyecto que se desean crear.

    Retorna:
    --------
    Project:
        Objeto del proyecto recién creado.
    """
    new_project = Project(**project_data.dict())
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return new_project

def get_all_projects(db: Session):
    """
    Consulta todos los proyectos registrados en la base de datos.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    Retorna:
    --------
    List[Project]:
        Lista de instancias del modelo `Project`.
    """
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

async def post_create_response(
    db,
    form_id: int,
    user_id: int,
    current_user,
    request,
    mode: str = "online",
    repeated_id: str = None,
    create_approvals: bool = True,
    status = None  # ResponseStatus
):
    """
    Función modificada para incluir el estado y el envío de correos EN BACKGROUND.
    """
    from app.models import Form, User, Response, ResponseApproval, FormApproval, FormCloseConfig
    from app.models import ApprovalStatus, ResponseStatus
    from sqlalchemy import func
    from fastapi import HTTPException
    
    form = db.query(Form).filter(Form.id == form_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    last_mode_response = db.query(Response).filter(Response.mode == mode).order_by(Response.mode_sequence.desc()).first()
    new_mode_sequence = last_mode_response.mode_sequence + 1 if last_mode_response else 1

    response = Response(
        form_id=form_id,
        user_id=user_id,
        mode=mode,
        mode_sequence=new_mode_sequence,
        submitted_at=func.now(),
        repeated_id=repeated_id,
        status=status
    )
    db.add(response)
    db.commit()
    db.refresh(response)

    approvers_created = 0
    
    if create_approvals:
        form_approvals = db.query(FormApproval).filter(
            FormApproval.form_id == form_id,
            FormApproval.is_active == True
        ).all()

        for approver in form_approvals:
            response_approval = ResponseApproval(
                response_id=response.id,
                user_id=approver.user_id,
                sequence_number=approver.sequence_number,
                is_mandatory=approver.is_mandatory,
                status=ApprovalStatus.pendiente,
            )
            db.add(response_approval)
            approvers_created += 1

        db.commit()
        
        if approvers_created > 0:
            send_mails_to_next_supporters(response.id, db)
    
    # Si no hay aprobadores, enviar correos EN UN THREAD SEPARADO (NO BLOQUEA)
    if not create_approvals or approvers_created == 0:
        try:
            form_close_config = db.query(FormCloseConfig).filter(
                FormCloseConfig.form_id == form_id
            ).first()
            
            if form_close_config:
                # EJECUTAR EN THREAD SEPARADO - NO ESPERA
                from app.database import SessionLocal
                
                run_async_in_thread(
                    send_form_action_emails_background,
                    SessionLocal,
                    form_id=form.id,
                    current_user_id=current_user.id,
                    request=request
                )
                print("✅ Correos de cierre iniciados en background (en thread separado)")
        except Exception as e:
            print(f"❌ Error al iniciar correos de cierre: {str(e)}")

    return {
        "message": "Response saved successfully",
        "response_id": response.id,
        "status": status.value if status else "draft",
        "mode": mode,
        "mode_sequence": new_mode_sequence,
        "approvers_created": approvers_created,
        "emails_status": "en_proceso"
    }


async def create_answer_in_db(answer, db: Session, current_user: User, request, send_emails: bool = True):
    """
    ✅ MODIFICADO: Ya NO envía correos aquí, eso se hace en post_create_response
    """
    
    created_answers = []

    # Caso 1: Múltiples respuestas (JSON dict)
    if isinstance(answer.question_id, str):
        try:
            parsed_answer = json.loads(answer.answer_text)
            if not isinstance(parsed_answer, dict):
                raise ValueError("answer_text must be JSON dict for multiple answers")

            for question_id_str, text in parsed_answer.items():
                question_id = int(question_id_str)
                new_answer = Answer(
                    response_id=answer.response_id,
                    question_id=question_id,
                    answer_text=text,
                    file_path=answer.file_path,
                    repeated_id=answer.repeated_id,
                    form_design_element_id=answer.form_design_element_id
                )
                db.add(new_answer)
                db.flush()
                created_answers.append(new_answer)

            db.commit()
            for ans in created_answers:
                db.refresh(ans)

        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Error: {str(e)}")

    # Caso 2: Respuesta simple
    elif isinstance(answer.question_id, int):
        single_answer_result = save_single_answer(answer, db)
        created_answers = [single_answer_result] if single_answer_result else []
    else:
        raise HTTPException(status_code=400, detail="Invalid question_id type")

    # 🆕 REMOVIDO: Ya no enviamos correos aquí
    # Los correos se envían en post_create_response cuando se completa el formulario

    # Retornar resultado
    if isinstance(answer.question_id, str):
        return {
            "message": "Multiple answers saved",
            "answers": [{"id": a.id, "question_id": a.question_id} for a in created_answers]
        }
    else:
        return created_answers[0] if created_answers else None

def save_single_answer(answer, db: Session):
    """
    ✅ MODIFICADO: Ahora guarda form_design_element_id
    """
    print(f"📝 Guardando respuesta para question_id: {answer.question_id}")
    print(f"🔗 UUID del elemento: {answer.form_design_element_id}")
    
    # Buscar respuesta existente (opcional, dependiendo de tu lógica)
    existing_answer = db.query(Answer).filter(
        Answer.response_id == answer.response_id,
        Answer.question_id == answer.question_id
    ).first()

    # Crear nueva respuesta
    new_answer = Answer(
        response_id=answer.response_id,
        question_id=answer.question_id,
        answer_text=answer.answer_text,
        file_path=answer.file_path,
        # ✅ NUEVO: Guardar el UUID
        form_design_element_id=answer.form_design_element_id
    )
    
    db.add(new_answer)
    db.commit()
    db.refresh(new_answer)
    
    return {
        "message": "Respuesta guardada exitosamente", 
        "answer_id": new_answer.id
    }

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
    """
    Función para obtener un resumen de todos los usuarios.
    Solo trae campos esenciales sin información sensible como contraseñas.
    """
    results = db.query(
        User.id,
        User.num_document,
        User.name,
        User.email,
        User.telephone,
        User.user_type,
        User.nickname,
        User.recognition_id,
        User.asign_bitacora,
        User.id_category,
        UserCategory.id.label('category_id'),
        UserCategory.name.label('category_name')
    ).outerjoin(
        UserCategory, User.id_category == UserCategory.id
    ).all()

    if not results:
        raise HTTPException(status_code=404, detail="No se encontraron usuarios")

    # Convertir a diccionarios
    return [
        {
            "id": r.id,
            "num_document": r.num_document,
            "email": r.email,
            "user_type": r.user_type.value,
            "asign_bitacora": r.asign_bitacora,
            "name": r.name,
            "telephone": r.telephone,
            "category": {
                "id": r.category_id,
                "name": r.category_name
            } if r.category_id else None
        }
        for r in results
    ]
def get_response_id(db: Session, form_id: int, user_id: int):
    """Obtiene el ID de Response basado en form_id y user_id."""
    stmt = select(Response.id).where(Response.form_id == form_id, Response.user_id == user_id)
    result = db.execute(stmt).scalar()  # `.scalar()` devuelve solo el ID si existe

    if result is None:
        raise HTTPException(status_code=404, detail="No se encontró la respuesta")

    return {"response_id": result}


def get_all_forms(db: Session):
    """
    Realiza una consulta para obtener todos los formularios incluyendo su categoría.

    :param db: Sesión activa de la base de datos
    :return: Lista de formularios como diccionarios
    """
    forms = db.query(Form).options(joinedload(Form.category)).all()
    return [
        {
            "id": form.id,
            "user_id": form.user_id,
            "title": form.title,
            "description": form.description,
            "format_type": form.format_type.value,
            "is_enabled": form.is_enabled,
            "created_at": form.created_at,
            "category": {
                "id": form.category.id,
                "name": form.category.name,
                "description": form.category.description,
            } if form.category else None
        }
        for form in forms
    ]
def get_forms_by_user(db: Session, user_id: int):
    """
    Obtiene los formularios sin form_design y los convierte a diccionarios
    para máxima velocidad de serialización.
    """
    forms = (
        db.query(Form)
        .join(FormModerators, Form.id == FormModerators.form_id)
        .options(
            defer(Form.form_design),
            joinedload(Form.category)
        )
        .filter(FormModerators.user_id == user_id)
        .all()
    )
    
    # Convertir a diccionarios manualmente (más rápido que la serialización automática)
    result = []
    for form in forms:
        form_dict = {
            "id": form.id,
            "title": form.title,
            "format_type": form.format_type.value,  # ← .value porque es un Enum
            "is_enabled": form.is_enabled,
            "user_id": form.user_id,
            "description": form.description,
            "created_at": form.created_at.isoformat(),  # ← Convertir a string ISO
            "id_category": form.id_category,
            "category": {
                "id": form.category.id,
                "parent_id": form.category.parent_id,
                "is_expanded": form.category.is_expanded,
                "color": form.category.color,
                "updated_at": form.category.updated_at.isoformat() if form.category.updated_at else None,
                "name": form.category.name,
                "description": form.category.description,
                "order": form.category.order,
                "icon": form.category.icon,
                "created_at": form.category.created_at.isoformat()
            } if form.category else None
        }
        result.append(form_dict)
    
    return result

def get_forms_by_user_summary(db: Session, user_id: int):
    """
    Obtiene un resumen de los formularios (solo campos básicos para listados).
    La forma MÁS RÁPIDA posible.
    """
    results = (
        db.query(
            Form.id,
            Form.title,
            Form.description,
            Form.created_at,
            Form.user_id
        )
        .join(FormModerators, Form.id == FormModerators.form_id)
        .filter(FormModerators.user_id == user_id)
        .all()
    )
    
    # Convertir tuplas a diccionarios
    return [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "created_at": r.created_at.isoformat(),
            "user_id": r.user_id
        }
        for r in results
    ]


def get_forms_by_approver(db: Session, user_id: int):
    """
    Obtiene TODOS los formularios, incluyendo TODOS los aprobadores activos de cada formulario
    e indicando si el usuario autenticado es uno de ellos.
    
    :param db: Sesión de base de datos activa.
    :param user_id: ID del usuario autenticado.
    :return: Lista de todos los formularios con lista completa de aprobadores.
    """
    
    # Primero obtenemos todos los formularios
    forms = (
        db.query(Form)
        .options(joinedload(Form.category))
        .order_by(Form.title)
        .all()
    )
    
    # Luego obtenemos todos los aprobadores activos por formulario
    approvals_query = (
        db.query(
            FormApproval.form_id,
            FormApproval.sequence_number,
            FormApproval.is_mandatory,
            FormApproval.deadline_days,
            FormApproval.is_active,
            FormApproval.user_id,
            User.name.label('approver_name'),
            User.email.label('approver_email')
        )
        .join(User, FormApproval.user_id == User.id)
        .filter(FormApproval.is_active == True)
        .order_by(FormApproval.form_id, FormApproval.sequence_number)
        .all()
    )
    
    # Organizamos los aprobadores por form_id
    approvals_by_form = {}
    for approval in approvals_query:
        form_id = approval.form_id
        if form_id not in approvals_by_form:
            approvals_by_form[form_id] = []
        
        approvals_by_form[form_id].append({
            "sequence_number": approval.sequence_number,
            "is_mandatory": approval.is_mandatory,
            "deadline_days": approval.deadline_days,
            "is_active": approval.is_active,
            "user_id": approval.user_id,
            "approver_name": approval.approver_name,
            "approver_email": approval.approver_email,
            "is_current_user": approval.user_id == user_id
        })
    
    # Construimos la respuesta final
    result = []
    for form in forms:
        # Verificamos si el usuario actual es aprobador de este formulario
        form_approvals = approvals_by_form.get(form.id, [])
        user_is_approver = any(approval["is_current_user"] for approval in form_approvals)
        
        form_dict = {
            "id": form.id,
            "user_id": form.user_id,
            "title": form.title,
            "description": form.description,
            "format_type": form.format_type,
            "created_at": form.created_at,
            "id_category": form.id_category,
            "is_enabled": form.is_enabled,
            "category": {
                "id": form.category.id,
                "name": form.category.name,
                "description": form.category.description
            } if form.category else None,
            "approval_info": {
                "has_approvers": len(form_approvals) > 0,
                "user_is_approver": user_is_approver,
                "approvers": form_approvals  # Lista completa de aprobadores
            }
        }
        result.append(form_dict)
    
    return result
def get_answers_by_question(db: Session, question_id: int):
    # Consulta todas las respuestas asociadas al question_id
    answers = db.query(Answer).filter(Answer.question_id == question_id).all()
    return answers



def get_unrelated_questions(db: Session, form_id: int):
    # Subconsulta para obtener todos los IDs de preguntas relacionadas con el form_id dado
    """
    Consulta todas las preguntas que no están relacionadas con un formulario específico.

    Esta función realiza una subconsulta para obtener los `question_id` ya relacionados al formulario,  
    y luego retorna todas las preguntas que **no** se encuentran en esa lista.

    Parámetros:
    -----------
    db : Session
        Sesión activa de base de datos.

    form_id : int
        ID del formulario cuyas preguntas no relacionadas se desean obtener.

    Retorna:
    --------
    List[Question]:
        Lista de objetos `Question` no relacionados al formulario especificado.
    """
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
            - 'associated_users': Usuarios asociados (id, name, num_document).
            - 'unassociated_users': Resto de usuarios (id, name, num_document).

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

    # Separar usuarios y extraer solo los campos necesarios
    associated_users = [
        {"id": user.id, "name": user.name, "num_document": user.num_document}
        for user in all_users if user.id in associated_users_ids
    ]
    
    unassociated_users = [
        {"id": user.id, "name": user.name, "num_document": user.num_document}
        for user in all_users if user.id not in associated_users_ids
    ]

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
    """
    Lógica para crear una relación entre una pregunta y una tabla externa.

    Esta función verifica que la pregunta (y la relacionada si aplica) existan y que no
    exista una relación previa. Luego crea la relación usando la tabla y el campo proporcionados.

    Parámetros:
    -----------
    db : Session
        Sesión activa de base de datos.

    question_id : int
        ID de la pregunta origen.

    name_table : str
        Nombre de la tabla externa relacionada.

    related_question_id : Optional[int]
        ID de la pregunta relacionada (opcional).

    field_name : Optional[str]
        Nombre del campo de la tabla que se usará en la relación (opcional).

    Retorna:
    --------
    QuestionTableRelation:
        Objeto de relación recién creado.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentra la pregunta o la relacionada.
        - 400: Si ya existe una relación para esta pregunta.
    """
    
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
def get_related_or_filtered_answers_with_forms(db: Session, question_id: int):
    """
    Obtiene respuestas dinámicas relacionadas o filtradas para una pregunta,
    incluyendo información completa de los formularios donde aparecen.
    
    CORRECCIÓN:
    -----------
    - Ahora recolecta TODAS las respuestas únicas de la pregunta relacionada,
      incluso cuando hay múltiples answers con el mismo response_id.
    """
    # Verificar si existe una condición de filtro
    condition = db.query(QuestionFilterCondition).filter_by(filtered_question_id=question_id).first()

    if condition:
        # [... código de condición sin cambios ...]
        responses = db.query(Response).filter_by(form_id=condition.form_id).all()
        valid_answers = []

        for response in responses:
            answers_dict = {a.question_id: a.answer_text for a in response.answers}
            source_val = answers_dict.get(condition.source_question_id)
            condition_val = answers_dict.get(condition.condition_question_id)

            if source_val is None or condition_val is None:
                continue

            try:
                condition_val = float(condition_val)
                expected_val = float(condition.expected_value)
            except ValueError:
                condition_val = str(condition_val)
                expected_val = str(condition.expected_value)

            condition_met = False
            if condition.operator == '==':
                condition_met = condition_val == expected_val
            elif condition.operator == '!=':
                condition_met = condition_val != expected_val
            elif condition.operator == '>':
                condition_met = condition_val > expected_val
            elif condition.operator == '<':
                condition_met = condition_val < expected_val
            elif condition.operator == '>=':
                condition_met = condition_val >= expected_val
            elif condition.operator == '<=':
                condition_met = condition_val <= expected_val

            if condition_met:
                valid_answers.append(source_val)

        filtered = list(filter(None, set(valid_answers)))
        return {
            "source": "condicion_filtrada",
            "data": [{"name": val} for val in filtered],
            "correlations": {}
        }

    # Si no hay condición, usar relación de tabla
    relation = db.query(QuestionTableRelation).filter_by(question_id=question_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="No se encontró relación para esta pregunta")

    if relation.related_question_id:
        # Obtener la pregunta relacionada
        related_question = db.query(Question).filter_by(id=relation.related_question_id).first()
        if not related_question:
            raise HTTPException(status_code=404, detail="Pregunta relacionada no encontrada")

        # Encontrar todos los formularios que contienen esta pregunta relacionada
        form_questions = db.query(FormQuestion).filter_by(question_id=relation.related_question_id).all()
        
        if not form_questions:
            return {
                "source": "pregunta_relacionada",
                "data": [],
                "forms": [],
                "correlations": {}
            }

        forms_data = []
        all_unique_answers = set()
        correlations_map = {}

        for fq in form_questions:
            form = db.query(Form).filter_by(id=fq.form_id).first()
            if not form:
                continue

            # Obtener todas las preguntas del formulario
            form_question_relations = db.query(FormQuestion).filter_by(form_id=form.id).all()
            form_questions_data = []
            
            for fqr in form_question_relations:
                question = db.query(Question).filter_by(id=fqr.question_id).first()
                if question:
                    form_questions_data.append({
                        "id": question.id,
                        "text": question.question_text,
                        "type": question.question_type.value
                    })

            # Obtener todas las respuestas del formulario
            responses = db.query(Response).filter_by(form_id=form.id).all()
            responses_data = []

            for response in responses:
                user = db.query(User).filter_by(id=response.user_id).first()
                
                # Obtener todas las respuestas de esta response
                answers = db.query(Answer).filter_by(response_id=response.id).all()
                answers_data = []
                
                # NUEVO: Lista para almacenar TODAS las respuestas de la pregunta relacionada
                related_answer_texts = []
                response_answers_map = {}
                
                for answer in answers:
                    question = db.query(Question).filter_by(id=answer.question_id).first()
                    answer_data = {
                        "question_id": answer.question_id,
                        "question_text": question.question_text if question else "",
                        "answer_text": answer.answer_text or "",
                        "file_path": answer.file_path or ""
                    }
                    answers_data.append(answer_data)
                    
                    # Si esta es una respuesta de la pregunta relacionada, guardarla
                    if answer.question_id == relation.related_question_id and answer.answer_text:
                        related_answer_texts.append(answer.answer_text)
                    
                    # Agregar al mapa de respuestas para correlaciones
                    if answer.answer_text:
                        response_answers_map[answer.question_id] = answer.answer_text

                # CORRECCIÓN: Procesar TODAS las respuestas de la pregunta relacionada
                for related_answer_text in related_answer_texts:
                    # Agregar al conjunto de respuestas únicas
                    all_unique_answers.add(related_answer_text)
                    
                    # Crear/actualizar correlaciones
                    if related_answer_text not in correlations_map:
                        correlations_map[related_answer_text] = {}
                    
                    # Agregar correlaciones con otras respuestas del mismo response
                    for q_id, answer_text in response_answers_map.items():
                        if q_id != relation.related_question_id:
                            if q_id not in correlations_map[related_answer_text]:
                                correlations_map[related_answer_text][q_id] = answer_text

                # Obtener estado de aprobación
                latest_approval = db.query(ResponseApproval)\
                    .filter_by(response_id=response.id)\
                    .order_by(ResponseApproval.sequence_number.desc())\
                    .first()
                
                approval_status = {
                    "status": latest_approval.status.value if latest_approval else "pendiente",
                    "message": latest_approval.message or "" if latest_approval else ""
                }

                response_data = {
                    "response_id": response.id,
                    "status": response.status.value,
                    "user": {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "num_document": user.num_document
                    } if user else None,
                    "submitted_at": response.submitted_at.isoformat(),
                    "answers": answers_data,
                    "approval_status": approval_status
                }
                responses_data.append(response_data)

            form_data = {
                "form_id": form.id,
                "title": form.title,
                "description": form.description,
                "questions": form_questions_data,
                "responses": responses_data
            }
            forms_data.append(form_data)

        return {
            "source": "pregunta_relacionada",
            "related_question": {
                "id": related_question.id,
                "text": related_question.question_text,
                "type": related_question.question_type.value
            },
            "data": [{"name": answer} for answer in sorted(all_unique_answers) if answer],
            "forms": forms_data,
            "correlations": correlations_map
        }

    # Si no hay pregunta relacionada, usar tabla externa
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
        "data": [serialize(r) for r in results if getattr(r, field_name, None)],
        "forms": [],
        "correlations": {}
    }


def get_related_or_filtered_answers(db: Session, question_id: int):
    """
    Obtiene respuestas dinámicas relacionadas o filtradas para una pregunta.

    Lógica:
    -------
    1. Si existe una condición en `QuestionFilterCondition`, evalúa cada respuesta del formulario
       relacionado y filtra según el operador y valor esperado.
    2. Si no hay condición, revisa si hay una relación con otra pregunta (`related_question_id`).
    3. Si no hay `related_question_id`, obtiene los datos de una tabla externa (`name_table`)
       usando un campo específico (`field_name`).

    Parámetros:
    -----------
    db : Session
        Sesión activa de base de datos.

    question_id : int
        ID de la pregunta para la que se buscan respuestas relacionadas.

    Retorna:
    --------
    dict:
        Diccionario con el origen (`source`) y una lista de valores (`data`) en formato:
        - {"name": <valor>}

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentra relación para la pregunta.
        - 400: Si la tabla o campo especificado no es válido.
    """
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
        id_category=user.id_category  # Incluir categoría
    )
    
    nickname = generate_nickname(user.name)
    
    db_user = User(
        num_document=user_data.num_document,
        name=user_data.name,
        email=user_data.email,
        telephone=user_data.telephone,
        password=user_data.password,
        nickname=nickname,
        id_category=user_data.id_category  # Asignar categoría
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

def parse_location_answer(answer_text: str) -> str:
    """
    Parsea el JSON de respuestas de tipo location y extrae solo el valor de selection.
    
    Args:
        answer_text (str): El texto de respuesta en formato JSON
        
    Returns:
        str: El valor del campo selection o el texto original si no se puede parsear
    """
    try:
        # Intentar parsear el JSON
        data = json.loads(answer_text)
        
        if isinstance(data, list):
            # Buscar el elemento con type "selection"
            for item in data:
                if isinstance(item, dict) and item.get("type") == "selection":
                    return item.get("value", "")
            
            # Si no se encuentra selection, devolver vacío
            return ""
        else:
            # Si no es una lista, devolver tal como está
            return str(data)
            
    except (json.JSONDecodeError, Exception):
        # Si no es JSON válido, devolver el valor original
        return answer_text

def parse_location_answer(answer_text: str) -> Dict[str, str]:
    """
    Parsea el JSON de respuestas de tipo location y extrae los datos relevantes.
    
    Args:
        answer_text (str): El texto de respuesta en formato JSON
        
    Returns:
        Dict[str, str]: Diccionario con los datos extraídos
    """
    try:
        # Intentar parsear el JSON
        data = json.loads(answer_text)
        
        if isinstance(data, list):
            # Extraer información de cada elemento
            coordinates = ""
            selection = ""
            
            for item in data:
                if isinstance(item, dict):
                    if item.get("type") == "coordinates":
                        coordinates = item.get("value", "")
                    elif item.get("type") == "selection":
                        selection = item.get("value", "")
                    
                    # Si hay información adicional en all_answers
                    if "all_answers" in item:
                        for answer in item["all_answers"]:
                            question_id = answer.get("question_id")
                            answer_text = answer.get("answer_text", "")
                            
            
            return {
                "coordinates": coordinates,
                "selection": selection,
               
            }
        else:
            # Si no es una lista, devolver tal como está
            return {"raw_value": str(data)}
            
    except (json.JSONDecodeError, Exception):
        # Si no es JSON válido, devolver el valor original
        return {"raw_value": answer_text}

def get_all_user_responses_by_form_id(db: Session, form_id: int):
    """
    Recupera y estructura las respuestas de todos los usuarios para un formulario específico.

    - Agrupa respuestas por pregunta.
    - Soporta preguntas con múltiples respuestas (como repeticiones).
    - Devuelve filas planas donde cada fila representa una instancia única de respuestas de un usuario.
    - Solo incluye las respuestas más recientes del historial.
    - Maneja preguntas tipo location parseando el JSON y separando los datos.

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
    
    # Crear mapeo de question_id -> question para acceso rápido
    question_map = {q.id: q for q in questions}

    responses = db.query(Response).filter(Response.form_id == form_id)\
        .options(
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.user)
        ).all()

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

    data = []
    counter = 1  # Contador para el consecutivo

    for response in responses:
        # Filtrar solo las respuestas más recientes (excluyendo previous_answer_ids)
        current_answers = [
            answer for answer in response.answers 
            if answer.id not in previous_answer_ids
        ]
        
        # Agrupar respuestas por orden de aparición de repetidas
        grouped_answers = {}
        for answer in current_answers:
            q_text = answer.question.question_text
            question_type = answer.question.question_type
            
            # Procesar respuesta según el tipo de pregunta
            if question_type == "location" and answer.answer_text:
                # Parsear JSON de location
                location_data = parse_location_answer(answer.answer_text)
                
                # Agregar cada campo del location como columna separada
                for key, value in location_data.items():
                    column_name = f"{q_text} - {key.replace('_', ' ').title()}"
                    grouped_answers.setdefault(column_name, []).append(str(value))
            else:
                # Procesamiento normal para otros tipos de preguntas
                answer_value = answer.answer_text or answer.file_path or ""
                grouped_answers.setdefault(q_text, []).append(answer_value)

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
                new_approval = FormApproval(
                    form_id=data.form_id,
                    user_id=approver.user_id,
                    sequence_number=approver.sequence_number,
                    is_mandatory=approver.is_mandatory,
                    deadline_days=approver.deadline_days,
                    is_active=approver.is_active if approver.is_active is not None else True
                )
                db.add(new_approval)
                newly_created_user_ids.append(approver.user_id)
        else:
            # Si no existe un aprobador activo con el mismo user_id y form_id, se puede agregar el nuevo aprobador
            new_approval = FormApproval(
                form_id=data.form_id,
                user_id=approver.user_id,
                sequence_number=approver.sequence_number,
                is_mandatory=approver.is_mandatory,
                deadline_days=approver.deadline_days,
                is_active=approver.is_active if approver.is_active is not None else True
            )
            db.add(new_approval)
            newly_created_user_ids.append(approver.user_id)
    
    db.commit()
    return newly_created_user_ids

def create_response_approval(db: Session, approval_data: ResponseApprovalCreate) -> ResponseApproval:
    """
    Lógica para crear y almacenar una nueva aprobación de respuesta en la base de datos.

    Esta función construye una instancia del modelo `ResponseApproval` a partir de los datos proporcionados,
    la guarda en la base de datos y retorna el objeto creado.

    Parámetros:
    ----------
    db : Session
        Sesión activa de la base de datos.
    approval_data : ResponseApprovalCreate
        Datos necesarios para crear el objeto `ResponseApproval`.

    Retorna:
    -------
    ResponseApproval
        Objeto persistido con los datos de aprobación.

    Excepciones:
    -----------
    Cualquier excepción lanzada durante el proceso será manejada por la función que la invoca.
    """
    new_approval = ResponseApproval(**approval_data.model_dump())
    db.add(new_approval)
    db.commit()
    db.refresh(new_approval)
    return new_approval
def get_forms_pending_approval_for_user(user_id: int, db: Session):
    """
    Recupera los formularios y respuestas que requieren aprobación por parte de un usuario específico.
    INCLUYE VALIDACIÓN de requisitos de aprobadores anteriores con línea de aprobación.

    Esta función consulta las aprobaciones asignadas al usuario, valida que sea su turno 
    (es decir, que los aprobadores anteriores obligatorios ya hayan aprobado) 
    y ADEMÁS valida que todos los aprobadores anteriores hayan cumplido sus requisitos
    de formularios requeridos con línea de aprobación completada.
    """
    results = []

    form_approvals = (
        db.query(FormApproval)
        .filter(FormApproval.user_id == user_id, FormApproval.is_active == True)
        .all()
    )

    for form_approval in form_approvals:
        form = form_approval.form

        # Obtener requisitos de aprobación para este formulario y usuario
        approval_requirements = (
            db.query(ApprovalRequirement)
            .options(
                joinedload(ApprovalRequirement.required_form),
                joinedload(ApprovalRequirement.approver)
            )
            .filter(
                ApprovalRequirement.form_id == form.id,
                ApprovalRequirement.approver_id == user_id
            )
            .all()
        )

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

            # 🔥 NUEVA VALIDACIÓN: Verificar requisitos de aprobadores anteriores
            validation_result = validate_approver_requirements_with_approval_line(
                response.id, user_id, db
            )
            
            # Si no puede aprobar por requisitos bloqueantes, continuar con la siguiente respuesta
            # O incluir la respuesta pero marcada como bloqueada (según prefieras)
            if not validation_result["can_approve"]:
                # OPCIÓN 1: Saltar esta respuesta completamente
                continue
                
                # OPCIÓN 2: Incluir pero marcada como bloqueada (descomenta lo siguiente)
                # response_blocked = True
                # blocking_reasons = validation_result["blocking_requirements"]

            # Obtener el estado de requisitos específicos para esta respuesta
            response_requirements_status = (
                db.query(ResponseApprovalRequirement)
                .options(
                    joinedload(ResponseApprovalRequirement.approval_requirement)
                    .joinedload(ApprovalRequirement.required_form),
                    joinedload(ResponseApprovalRequirement.fulfilling_response)
                )
                .filter(ResponseApprovalRequirement.response_id == response.id)
                .all()
            )

            # Obtener historial de respuestas para esta response
            histories = db.query(AnswerHistory).filter(AnswerHistory.response_id == response.id).all()
            
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

            # Mostrar estado de cada aprobador de esta respuesta
            response_approvals_all = db.query(ResponseApproval).filter(
                ResponseApproval.response_id == response.id
            ).order_by(ResponseApproval.sequence_number).all()

            for ra in response_approvals_all:
                user_ra = ra.user

            # Obtener respuestas actuales (excluyendo las que son previous_answer_ids)
            answers = db.query(Answer, Question).join(Question).filter(
                Answer.response_id == response.id,
                ~Answer.id.in_(previous_answer_ids) if previous_answer_ids else True
            ).all()

            answers_data = []
            for a, q in answers:
                answer_data = {
                    "question_id": q.id,
                    "question_text": q.question_text,
                    "question_type": q.question_type,
                    "answer_text": a.answer_text,
                    "file_path": a.file_path,
                    "answer_id": a.id,
                    "has_history": a.id in history_map
                }
                
                # Agregar información del historial si existe
                if a.id in history_map:
                    history = history_map[a.id]
                    previous_answer = historical_answers.get(history.previous_answer_id) if history.previous_answer_id else None
                    
                    answer_data["history"] = {
                        "previous_answer": {
                            "answer_text": previous_answer.answer_text if previous_answer else None,
                            "file_path": previous_answer.file_path if previous_answer else None,
                        } if previous_answer else None,
                        "was_modified": True
                    }
                else:
                    answer_data["history"] = {
                        "previous_answer": None,
                        "was_modified": False
                    }
                
                answers_data.append(answer_data)

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
            } for ra in response_approvals_all]

            user_response = db.query(User).filter(User.id == response.user_id).first()

            # Construir información de requisitos de aprobación con estado de diligenciamiento
            requirements_data = []
            
            # Crear un mapeo de approval_requirement_id -> ResponseApprovalRequirement para búsqueda rápida
            requirement_status_map = {
                req_status.approval_requirement_id: req_status 
                for req_status in response_requirements_status
            }
            
            for req in approval_requirements:
                # Obtener el estado específico de este requisito para esta respuesta
                req_status = requirement_status_map.get(req.id)
                
                requirement_info = {
                    "requirement_id": req.id,
                    "required_form": {
                        "form_id": req.required_form_id,
                        "form_title": req.required_form.title,
                        "form_description": req.required_form.description
                    },
                    "linea_aprobacion": req.linea_aprobacion,
                    "approver": {
                        "user_id": req.approver.id,
                        "name": req.approver.name,
                        "email": req.approver.email,
                        "num_document": req.approver.num_document
                    },
                    # Estado de diligenciamiento del requisito
                    "fulfillment_status": {
                        "is_fulfilled": req_status.is_fulfilled if req_status else False,
                        "fulfilling_response_id": req_status.fulfilling_response_id if req_status else None,
                        "fulfilling_response_submitted_at": req_status.fulfilling_response.submitted_at.isoformat() if req_status and req_status.fulfilling_response else None,
                        "updated_at": req_status.updated_at.isoformat() if req_status else None,
                        "needs_completion": not (req_status and req_status.is_fulfilled),
                        "completion_status": "completed" if req_status and req_status.is_fulfilled else "pending"
                    }
                }
                requirements_data.append(requirement_info)

            # Calcular estadísticas de requisitos
            total_requirements = len(requirements_data)
            fulfilled_requirements = sum(1 for req in requirements_data if req["fulfillment_status"]["is_fulfilled"])
            pending_requirements = total_requirements - fulfilled_requirements
            all_requirements_fulfilled = fulfilled_requirements == total_requirements if total_requirements > 0 else True

            # Construir la respuesta final con información de validación
            response_data = {
                "deadline_days": form_approval.deadline_days,
                "form_id": form.id,
                "form_title": form.title,
                "form_description": form.description,
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
                "all_approvers": all_approvals,
                "response_history": {
                    "has_modifications": len(histories) > 0,
                    "total_changes": len(histories),
                    "modified_answers_count": len([a for a in answers_data if a["has_history"]])
                },
                "approval_requirements": {
                    "has_requirements": len(requirements_data) > 0,
                    "total_requirements": total_requirements,
                    "fulfilled_requirements": fulfilled_requirements,
                    "pending_requirements": pending_requirements,
                    "all_requirements_fulfilled": all_requirements_fulfilled,
                    "completion_percentage": round((fulfilled_requirements / total_requirements) * 100, 2) if total_requirements > 0 else 100,
                    "requirements": requirements_data
                },
                # 🔥 NUEVA SECCIÓN: Información de validación de requisitos anteriores
                "previous_approvers_validation": {
                    "can_approve": validation_result["can_approve"],
                    "has_blocking_requirements": len(validation_result["blocking_requirements"]) > 0,
                    "blocking_requirements": validation_result["blocking_requirements"],
                    "validation_details": validation_result["validation_details"]
                }
            }

            # Si quisieras incluir respuestas bloqueadas (OPCIÓN 2), descomenta:
            # if 'response_blocked' in locals() and response_blocked:
            #     response_data["approval_blocked"] = True
            #     response_data["blocking_reasons"] = blocking_reasons

            results.append(response_data)

    return results


# También necesitarás incluir las funciones de validación en el mismo archivo:

def validate_approver_requirements_with_approval_line(response_id: int, approver_user_id: int, db: Session):
    """
    Valida si un aprobador puede aprobar una respuesta verificando que TODOS los aprobadores
    anteriores en la secuencia hayan cumplido sus requisitos de aprobación.
    """
    # Obtener la secuencia del aprobador actual
    current_approver = (
        db.query(ResponseApproval)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.user_id == approver_user_id
        )
        .first()
    )
    
    if not current_approver:
        return {
            "can_approve": False,
            "blocking_requirements": [{"reason": "Usuario no es aprobador de esta respuesta"}],
            "validation_details": []
        }
    
    current_sequence = current_approver.sequence_number
    
    # Obtener todos los aprobadores anteriores (secuencia menor)
    previous_approvers = (
        db.query(ResponseApproval)
        .options(joinedload(ResponseApproval.user))
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.sequence_number < current_sequence
        )
        .all()
    )
    
    if not previous_approvers:
        return {
            "can_approve": True,
            "blocking_requirements": [],
            "validation_details": []
        }
    
    blocking_requirements = []
    validation_details = []
    
    # Verificar requisitos de cada aprobador anterior
    for prev_approver in previous_approvers:
        prev_approver_requirements = (
            db.query(ResponseApprovalRequirement)
            .join(ApprovalRequirement, ResponseApprovalRequirement.approval_requirement_id == ApprovalRequirement.id)
            .options(
                joinedload(ResponseApprovalRequirement.approval_requirement)
                .joinedload(ApprovalRequirement.required_form),
                joinedload(ResponseApprovalRequirement.approval_requirement)
                .joinedload(ApprovalRequirement.approver),
                joinedload(ResponseApprovalRequirement.fulfilling_response)
            )
            .filter(
                ResponseApprovalRequirement.response_id == response_id,
                ApprovalRequirement.approver_id == prev_approver.user_id
            )
            .all()
        )
        
        approver_detail = {
            "approver_user_id": prev_approver.user_id,
            "approver_name": prev_approver.user.name,
            "sequence_number": prev_approver.sequence_number,
            "has_requirements": len(prev_approver_requirements) > 0,
            "requirements_status": []
        }
        
        if not prev_approver_requirements:
            approver_detail["overall_status"] = "no_requirements_ok"
            validation_details.append(approver_detail)
            continue
        
        approver_has_blocking_requirements = False
        
        for req_status in prev_approver_requirements:
            requirement = req_status.approval_requirement
            required_form = requirement.required_form
            
            req_detail = {
                "requirement_id": requirement.id,
                "required_form_id": required_form.id,
                "required_form_title": required_form.title,
                "is_fulfilled": req_status.is_fulfilled,
                "linea_aprobacion": requirement.linea_aprobacion,
                "fulfilling_response_id": req_status.fulfilling_response_id,
                "status": None,
                "approval_line_validation": None
            }
            
            if not req_status.is_fulfilled:
                blocking_requirements.append({
                    "type": "unfulfilled_requirement",
                    "blocking_approver": {
                        "user_id": prev_approver.user_id,
                        "name": prev_approver.user.name,
                        "sequence": prev_approver.sequence_number
                    },
                    "requirement_id": requirement.id,
                    "required_form_title": required_form.title,
                    "reason": f"El aprobador {prev_approver.user.name} no ha diligenciado el formulario requerido '{required_form.title}'"
                })
                req_detail["status"] = "not_fulfilled"
                approver_has_blocking_requirements = True
            
            elif requirement.linea_aprobacion and req_status.fulfilling_response_id:
                approval_line_result = validate_approval_line_completion(req_status.fulfilling_response_id, db)
                req_detail["approval_line_validation"] = approval_line_result
                
                if not approval_line_result["all_approved"]:
                    blocking_requirements.append({
                        "type": "pending_approval_line",
                        "blocking_approver": {
                            "user_id": prev_approver.user_id,
                            "name": prev_approver.user.name,
                            "sequence": prev_approver.sequence_number
                        },
                        "requirement_id": requirement.id,
                        "required_form_title": required_form.title,
                        "fulfilling_response_id": req_status.fulfilling_response_id,
                        "reason": f"El formulario requerido '{required_form.title}' del aprobador {prev_approver.user.name} no ha completado su línea de aprobación",
                        "pending_approvers": approval_line_result["pending_approvers"]
                    })
                    req_detail["status"] = "approval_line_pending"
                    approver_has_blocking_requirements = True
                else:
                    req_detail["status"] = "fully_approved"
            else:
                req_detail["status"] = "fulfilled_no_approval_line"
            
            approver_detail["requirements_status"].append(req_detail)
        
        approver_detail["overall_status"] = "has_blocking_requirements" if approver_has_blocking_requirements else "all_requirements_fulfilled"
        validation_details.append(approver_detail)
    
    return {
        "can_approve": len(blocking_requirements) == 0,
        "blocking_requirements": blocking_requirements,
        "validation_details": validation_details
    }


def validate_approval_line_completion(response_id: int, db: Session):
    """Verifica si todos los aprobadores obligatorios de una respuesta ya aprobaron."""
    response_approvals = (
        db.query(ResponseApproval)
        .options(joinedload(ResponseApproval.user))
        .filter(ResponseApproval.response_id == response_id)
        .order_by(ResponseApproval.sequence_number)
        .all()
    )
    
    if not response_approvals:
        return {
            "all_approved": True,
            "total_approvers": 0,
            "approved_count": 0,
            "pending_approvers": [],
            "approval_status": []
        }
    
    approved_count = 0
    pending_approvers = []
    approval_status = []
    
    for approval in response_approvals:
        status_info = {
            "user_id": approval.user_id,
            "user_name": approval.user.name,
            "sequence_number": approval.sequence_number,
            "status": approval.status.value,
            "is_mandatory": approval.is_mandatory,
            "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None
        }
        
        if approval.status == ApprovalStatus.aprobado:
            approved_count += 1
        elif approval.is_mandatory:
            pending_approvers.append(status_info)
        
        approval_status.append(status_info)
    
    return {
        "all_approved": len(pending_approvers) == 0,
        "total_approvers": len(response_approvals),
        "approved_count": approved_count,
        "pending_approvers": pending_approvers,
        "approval_status": approval_status
    }

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

def get_active_form_actions(form_id: int, db):
    """
    Obtiene solo las acciones activas para un formulario en formato simplificado.
    Ahora retorna listas de destinatarios en lugar de un solo destinatario.
    
    Args:
        form_id (int): ID del formulario
        db: Instancia de la base de datos (session)
    
    Returns:
        list: Lista de tuplas (acción, [lista_de_destinatarios]) para las configuraciones activas
    """
    try:
        config = db.query(FormCloseConfig).filter(
            FormCloseConfig.form_id == form_id
        ).first()
        
        if not config:
            return []
        
        active_actions = []
        
        # 🆕 Parsear JSON a lista de emails
        if config.send_download_link and config.download_link_recipients:
            try:
                recipients = json.loads(config.download_link_recipients) if isinstance(config.download_link_recipients, str) else config.download_link_recipients
                if recipients:  # Solo agregar si hay emails
                    active_actions.append(('send_download_link', recipients))
            except Exception as e:
                print(f"Error al parsear download_link_recipients: {str(e)}")
        
        if config.send_pdf_attachment and config.email_recipients:
            try:
                recipients = json.loads(config.email_recipients) if isinstance(config.email_recipients, str) else config.email_recipients
                if recipients:
                    active_actions.append(('send_pdf_attachment', recipients))
            except Exception as e:
                print(f"Error al parsear email_recipients: {str(e)}")
        
        if config.generate_report and config.report_recipients:
            try:
                recipients = json.loads(config.report_recipients) if isinstance(config.report_recipients, str) else config.report_recipients
                if recipients:
                    active_actions.append(('generate_report', recipients))
            except Exception as e:
                print(f"Error al parsear report_recipients: {str(e)}")
        
        if config.do_nothing:
            active_actions.append(('do_nothing', []))
        
        return active_actions
        
    except Exception as e:
        print(f"Error al obtener acciones activas: {str(e)}")
        return []
    
def run_async_in_thread(async_func, db_session_factory, form_id, current_user_id, request):
    """
    Ejecuta una función async en un thread separado con nueva sesión.
    Totalmente independiente, no bloquea nada.
    """
    def wrapper():
        # CREAR NUEVA SESIÓN PARA EL THREAD
        new_db = db_session_factory()
        
        # Crear un nuevo event loop para este thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                async_func(
                    form_id=form_id,
                    current_user_id=current_user_id,
                    db=new_db,
                    request=request
                )
            )
        except Exception as e:
            print(f"❌ Error en thread: {str(e)}")
        finally:
            new_db.close()
            loop.close()
    
    # Crear thread en background (daemon=True para que no bloquee)
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()

async def send_form_action_emails_background(form_id: int, current_user_id: int, db, request):
    """
    Envía correos electrónicos según las acciones activas configuradas para un formulario.
    Se ejecuta EN BACKGROUND sin bloquear.
    """
    try:
        # OBTENER current_user CON LA NUEVA SESIÓN
        from app.models import User, Form, FormCloseConfig
        
        current_user = db.query(User).filter(User.id == current_user_id).first()
        
        if not current_user:
            print(f"❌ Usuario con ID {current_user_id} no encontrado")
            return
        
        form = db.query(Form).filter(Form.id == form_id).first()
        
        if not form:
            print(f"❌ Formulario con ID {form_id} no encontrado")
            return
        
        # OBTENER LAS ACCIONES ACTIVAS
        active_actions = get_active_form_actions(form_id, db)
        
        if not active_actions:
            print(f"No hay acciones activas configuradas para el formulario {form_id}")
            return
        
        results = {
            "success": True,
            "emails_sent": 0,
            "failed_emails": 0,
            "actions_processed": []
        }
        
        current_date = datetime.now().strftime("%d/%m/%Y")
        pdf_bytes = None
        pdf_filename = f"form_{form_id}_response.pdf"
        
        # Verificar si necesitamos generar el PDF
        needs_pdf = any(action in ['send_pdf_attachment', 'send_download_link'] for action, _ in active_actions)
        
        if needs_pdf:
            try:
                pdf_bytes = await generate_pdf_from_form_id(
                    form_id=form_id,
                    db=db,
                    current_user=current_user,
                    request=request
                )
                print(f"✅ PDF generado exitosamente para el formulario {form_id}")
            except Exception as e:
                print(f"❌ Error al generar PDF: {str(e)}")
                # Filtrar acciones que requieren PDF
                active_actions = [(action, recipients) for action, recipients in active_actions 
                                if action not in ['send_pdf_attachment', 'send_download_link']]
        
        # Procesar cada acción activa
        for action, recipients in active_actions:
            if action == 'do_nothing':
                print(f"Acción 'do_nothing' detectada - no se envía correo")
                results["actions_processed"].append({
                    "action": action,
                    "status": "skipped",
                    "message": "Acción configurada para no hacer nada"
                })
                continue
            
            # Iterar sobre cada destinatario
            for recipient in recipients:
                try:
                    email_sent = await send_action_notification_email(
                        action=action,
                        recipient=recipient,
                        form=form,
                        current_date=current_date,
                        pdf_bytes=pdf_bytes,
                        pdf_filename=pdf_filename,
                        db=db, 
                        current_user=current_user,
                    )
                    
                    if email_sent:
                        results["emails_sent"] += 1
                        results["actions_processed"].append({
                            "action": action,
                            "recipient": recipient,
                            "status": "success"
                        })
                        print(f"✅ Correo enviado exitosamente a {recipient} para acción '{action}'")
                    else:
                        results["failed_emails"] += 1
                        results["actions_processed"].append({
                            "action": action,
                            "recipient": recipient,
                            "status": "failed",
                            "error": "send_action_notification_email retornó False"
                        })
                        print(f"❌ Fallo al enviar correo a {recipient} para acción '{action}'")
                        
                except Exception as e:
                    results["failed_emails"] += 1
                    results["actions_processed"].append({
                        "action": action,
                        "recipient": recipient,
                        "status": "failed",
                        "error": str(e)
                    })
                    print(f"❌ Error al enviar correo a {recipient}: {str(e)}")
        
        print(f"✅ Proceso completado para formulario {form_id}. Resultado: {results}")
        
    except Exception as e:
        print(f"❌ Error al procesar acciones del formulario {form_id}: {str(e)}")   
        
async def send_form_action_emails(form_id: int, db, current_user, request):
    """
    Envía correos electrónicos según las acciones activas configuradas para un formulario.
    Ahora soporta múltiples destinatarios por acción.
    
    Args:
        form_id (int): ID del formulario
        db: Instancia de la base de datos (session)
        current_user: Usuario actual
        request: Objeto request de FastAPI
    
    Returns:
        dict: Resultados del envío de correos
    """
    try:
        # Obtener información del formulario
        form = db.query(Form).filter(Form.id == form_id).first()
        if not form:
            return {"success": False, "error": f"Formulario con ID {form_id} no encontrado", "emails_sent": 0}
        
        # Obtener las acciones activas (ahora con listas de emails)
        active_actions = get_active_form_actions(form_id, db)
        
        if not active_actions:
            print(f"No hay acciones activas configuradas para el formulario {form_id}")
            return {"success": True, "message": "No hay acciones configuradas", "emails_sent": 0}
        
        results = {
            "success": True,
            "emails_sent": 0,
            "failed_emails": 0,
            "actions_processed": []
        }
        
        current_date = datetime.now().strftime("%d/%m/%Y")
        
        # Generar PDF una sola vez si es necesario
        pdf_bytes = None
        pdf_filename = f"form_{form_id}_response.pdf"
        
        # Verificar si necesitamos generar el PDF
        needs_pdf = any(action in ['send_pdf_attachment', 'send_download_link'] for action, _ in active_actions)
        
        if needs_pdf:
            try:
                pdf_bytes = await generate_pdf_from_form_id(
                    form_id=form_id,
                    db=db,
                    current_user=current_user,
                    request=request
                )
                print(f"✅ PDF generado exitosamente para el formulario {form_id}")
            except Exception as e:
                print(f"❌ Error al generar PDF: {str(e)}")
                # Marcar acciones que requieren PDF como fallidas
                for action, recipients in active_actions:
                    if action in ['send_pdf_attachment', 'send_download_link']:
                        results["failed_emails"] += len(recipients)
                        for recipient in recipients:
                            results["actions_processed"].append({
                                "action": action,
                                "recipient": recipient,
                                "status": "failed",
                                "error": f"Error al generar PDF: {str(e)}"
                            })
                # Filtrar acciones que no requieren PDF
                active_actions = [(action, recipients) for action, recipients in active_actions 
                                if action not in ['send_pdf_attachment', 'send_download_link']]
        
        # 🆕 Procesar cada acción activa con MÚLTIPLES destinatarios
        for action, recipients in active_actions:
            if action == 'do_nothing':
                print(f"Acción 'do_nothing' detectada - no se envía correo")
                results["actions_processed"].append({
                    "action": action,
                    "status": "skipped",
                    "message": "Acción configurada para no hacer nada"
                })
                continue
            
            # 🆕 Iterar sobre cada destinatario
            for recipient in recipients:
                try:
                    email_sent = await send_action_notification_email(
                        action=action,
                        recipient=recipient,
                        form=form,
                        current_date=current_date,
                        pdf_bytes=pdf_bytes,
                        pdf_filename=pdf_filename,
                        db=db, 
                        current_user=current_user,
                    )
                    
                    if email_sent:
                        results["emails_sent"] += 1
                        results["actions_processed"].append({
                            "action": action,
                            "recipient": recipient,
                            "status": "success"
                        })
                        print(f"✅ Correo enviado exitosamente a {recipient} para acción '{action}'")
                    else:
                        results["failed_emails"] += 1
                        results["actions_processed"].append({
                            "action": action,
                            "recipient": recipient,
                            "status": "failed",
                            "error": "send_action_notification_email retornó False"
                        })
                        print(f"❌ Fallo al enviar correo a {recipient} para acción '{action}'")
                        
                except Exception as e:
                    results["failed_emails"] += 1
                    results["actions_processed"].append({
                        "action": action,
                        "recipient": recipient,
                        "status": "failed",
                        "error": str(e)
                    })
                    print(f"❌ Error al enviar correo a {recipient}: {str(e)}")
        
        return results
        
    except Exception as e:
        print(f"❌ Error al procesar acciones del formulario {form_id}: {str(e)}")
        return {"success": False, "error": str(e), "emails_sent": 0}
async def update_response_approval_status(
    response_id: int,
    update_data: UpdateResponseApprovalRequest,
    user_id: int,
    db: Session,
    current_user,
    request
):
    """
    Lógica principal para actualizar el estado de una aprobación de respuesta y realizar
    acciones relacionadas como notificaciones, verificación de flujos y envío de correos.

    Flujo general:
    --------------
    1. Busca el registro de `ResponseApproval` correspondiente.
    2. Actualiza su estado (aprobado o rechazado).
    3. Si es una aprobación, verifica si deben activarse las siguientes aprobaciones.
    4. Si todos los aprobadores (obligatorios y opcionales) han aprobado, finaliza el proceso.
    5. Envía correos a usuarios interesados según su configuración de notificación.
    6. NUEVO: Envía correos de cierre en BACKGROUND si todos aprobaron.

    Parámetros:
    ----------
    response_id : int
        ID de la respuesta a la cual está asociada la aprobación.

    update_data : UpdateResponseApprovalRequest
        Objeto con los nuevos valores para la aprobación.

    user_id : int
        ID del usuario que realiza la aprobación.

    db : Session
        Sesión activa de base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    request : Request
        Objeto de solicitud, útil para URLs completas o cabeceras.

    Retorna:
    -------
    ResponseApproval
        Objeto actualizado de aprobación de respuesta.

    Lanza:
    ------
    HTTPException 404:
        Si no se encuentra el `ResponseApproval` correspondiente.

    Efectos adicionales:
    --------------------
    - Envía correo al siguiente aprobador (si aplica).
    - Envía correo al creador del formulario si se finaliza el proceso.
    - Envía notificaciones a usuarios registrados según el evento configurado.
    - NUEVO: Inicia envío de correos de cierre en thread separado (background).
    """
    from app.models import ResponseApproval, Response, Form, FormApproval, FormApprovalNotification, ApprovalStatus
    from app.database import SessionLocal
    from fastapi import HTTPException
    from datetime import datetime
    
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

    # 2. Acciones según el estado
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
            FormApproval.is_active == True
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

    # 4. Verificar si todos los aprobadores han aprobado
    if not detener_proceso and update_data.status == "aprobado":
        # Verificar si todos los aprobadores obligatorios han aprobado
        todos_aprobadores_completados = all(
            any(ra.user_id == fa.user_id and ra.status == ApprovalStatus.aprobado 
                for ra in response_approvals)
            for fa in form_approval_template if fa.is_mandatory
        )
        
        # Verificar si todos los aprobadores (obligatorios y opcionales) han dado respuesta
        todos_han_respondido = all(
            any(ra.user_id == fa.user_id for ra in response_approvals)
            for fa in form_approval_template
        )
        
        if todos_aprobadores_completados and todos_han_respondido:
            # El proceso está completamente finalizado
            send_final_approval_email_to_original_user(response_id, db)
            
            # 🔥 EJECUTAR EN THREAD SEPARADO - NO ESPERA
            run_async_in_thread(
                send_form_action_emails_background,
                SessionLocal,
                form_id=form.id,
                current_user_id=current_user.id,
                request=request
            )
            print("✅ Correos de cierre iniciados en background (en thread separado)")

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
                subject=f"Proceso de aprobación - {form.title}"
            )

    return response_approval

def send_final_approval_email_to_original_user(response_id: int, db: Session):
    """
    Envía un correo al usuario original notificándole que su respuesta fue completamente aprobada
    """
    try:
        # Obtener información de la respuesta y usuario original
        response = db.query(Response).filter(Response.id == response_id).first()
        if not response:
            print(f"❌ No se encontró la respuesta {response_id}")
            return False
            
        form = db.query(Form).filter(Form.id == response.form_id).first()
        usuario_original = response.user  # Este es quien envió originalmente el formulario
        
        # Obtener todos los aprobadores y su estado
        form_approval_template = (
            db.query(FormApproval)
            .filter(
                FormApproval.form_id == form.id,
                FormApproval.is_active == True
            )
            .order_by(FormApproval.sequence_number)
            .all()
        )
        
        response_approvals = db.query(ResponseApproval).filter(
            ResponseApproval.response_id == response_id
        ).all()
        
        # Construir el contenido del correo
        contenido = f"""🎉 ¡Excelentes noticias!

Tu respuesta al formulario "{form.title}" ha sido COMPLETAMENTE APROBADA por todos los aprobadores requeridos.

📋 Detalles de tu envío:
• Formulario: {form.title}
• Formato: {form.format_type.value}

✅ Aprobadores que revisaron tu respuesta:
"""
        
        for fa in form_approval_template:
            ra = next((r for r in response_approvals if r.user_id == fa.user_id), None)
            if ra and ra.status == ApprovalStatus.aprobado:
                fecha_aprobacion = ra.reviewed_at.strftime('%d/%m/%Y %H:%M')
                obligatorio = "Obligatorio" if fa.is_mandatory else "Opcional"
                contenido += f"• [{fa.sequence_number}] {fa.user.name} ({obligatorio}) - Aprobado el {fecha_aprobacion}\n"
                if ra.message:
                    contenido += f"  💬 Comentario: {ra.message}\n"
        
        contenido += f"\n🎯 Tu respuesta ha sido procesada exitosamente y está lista para su implementación."
        
        # Enviar el correo usando la función existente
        return send_email_plain_approval_status(
            to_email=usuario_original.email,
            name_form=form.title,
            to_name=usuario_original.name,
            body_text=contenido,
            subject=f"✅ Tu formulario '{form.title}' ha sido APROBADO completamente"
        )
        
    except Exception as e:
        print(f"❌ Error enviando correo final al usuario original: {str(e)}")
        return False


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

    

    return {
        "status": "aprobado",
        "message": " | ".join(filter(None, messages))
    }


def get_form_with_full_responses(form_id: int, db: Session):
    """
    Recupera todos los detalles de un formulario con sus preguntas, respuestas, historial de respuestas
    y estado de aprobación para cada una.
    """
    
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
    
    form = db.query(Form).options(
        joinedload(Form.questions),
        joinedload(Form.responses).joinedload(Response.user),
    ).filter(Form.id == form_id).first()

    if not form:
        return None

    # Obtener todos los response_ids para buscar el historial
    response_ids = [response.id for response in form.responses]
    
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

    # ==========================================
    # AQUÍ ESTÁ EL CAMBIO IMPORTANTE
    # ==========================================
    # En lugar de obtener las preguntas de form.questions,
    # las extraemos de las respuestas REALES
    all_questions_map = {}  # question_id -> question_data
    
    for response in form.responses:
        # Obtener respuestas actuales (excluyendo las que son previous_answer_ids)
        answers = (
            db.query(Answer)
            .options(joinedload(Answer.question))
            .filter(
                Answer.response_id == response.id,
                ~Answer.id.in_(previous_answer_ids) if previous_answer_ids else True
            )
            .all()
        )
        
        # Agregar cada pregunta al mapa si no existe
        for ans in answers:
            if ans.question.id not in all_questions_map:
                all_questions_map[ans.question.id] = {
                    "id": ans.question.id,
                    "text": ans.question.question_text,
                    "type": ans.question.question_type.name if hasattr(ans.question.question_type, 'name') else str(ans.question.question_type),
                }
    
    # Convertir el mapa a lista y ordenar por ID
    questions_list = list(all_questions_map.values())
    
    results = {
        "form_id": form.id,
        "title": form.title,
        "description": form.description,
        "form_design": form.form_design,
        "questions": questions_list,  # ← Ahora tiene TODAS las preguntas reales
        "responses": [],
    }

    # Procesar las respuestas
    for response in form.responses:
        response_data = {
            "response_id": response.id,

            "status": response.status,
            "user": {
                "id": response.user.id,
                "name": response.user.name,
                "email": response.user.email,
                "num_document": response.user.num_document,
            },
            "submitted_at": response.submitted_at,
            "answers": [],
            "approval_status": None,
        }

        # Obtener respuestas actuales (excluyendo las que son previous_answer_ids)
        answers = (
            db.query(Answer)
            .options(joinedload(Answer.question))
            .filter(
                Answer.response_id == response.id,
                ~Answer.id.in_(previous_answer_ids) if previous_answer_ids else True
            )
            .all()
        )

        for ans in answers:
            # Procesar la respuesta según el tipo de pregunta
            processed_answer_text = process_regisfacial_answer(ans.answer_text, ans.question.question_type)
            
            response_data["answers"].append({
                "question_id": ans.question.id,
                "form_design_element_id": ans.form_design_element_id,
                "question_text": ans.question.question_text,
                "answer_text": processed_answer_text,
                "file_path": ans.file_path,
            })

        # Obtener aprobaciones y calcular estado
        approvals = db.query(ResponseApproval).filter_by(response_id=response.id).all()
        approval_info = get_response_approval_status(approvals)
        response_data["approval_status"] = approval_info

        results["responses"].append(response_data)

    return results


def update_form_design_service(db: Session, form_id: int, design_data: List[Dict[str, Any]]):
    """
    Lógica de base de datos para actualizar el diseño de un formulario.

    Esta función reemplaza por completo el campo `form_design` del formulario con el nuevo
    diseño recibido, que debe ser una lista de objetos JSON.

    Parámetros:
    -----------
    db : Session
        Sesión activa de base de datos.

    form_id : int
        ID del formulario que se desea actualizar.

    design_data : List[Dict[str, Any]]
        Nueva estructura de diseño a guardar. Puede incluir posiciones, tipos de campos,
        estilos u orden personalizado.

    Retorna:
    --------
    Form
        Objeto del formulario actualizado.

    Lanza:
    ------
    HTTPException 404:
        Si el formulario no existe.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    form.form_design = design_data  # guarda la lista completa
    db.commit()
    db.refresh(form)

    return form


def get_notifications_for_form(form_id: int, db: Session):
    # Verifica si el formulario existe
    """
    Recupera las notificaciones configuradas para un formulario específico.

    Esta función consulta en la base de datos todas las notificaciones asociadas 
    a un formulario a través del modelo `FormApprovalNotification`. Además, incluye 
    la información del usuario asignado a cada notificación.

    Parámetros:
    -----------
    form_id : int
        ID del formulario para el cual se desean obtener las notificaciones.

    db : Session
        Objeto de sesión SQLAlchemy utilizado para interactuar con la base de datos.

    Retorna:
    --------
    List[NotificationResponse]
        Lista de notificaciones configuradas, cada una con su usuario relacionado.

    Lanza:
    ------
    HTTPException 404:
        Si el formulario con el `form_id` especificado no existe en la base de datos.
    """
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
        # 🔍 ANÁLISIS DE RELACIONES ANTES DE ELIMINAR
        relations_info = analyze_form_relations(db, form_id)
        
        # Obtener todos los response_ids relacionados con el formulario
        response_ids = db.query(Response.id).filter(Response.form_id == form_id).all()
        response_ids = [r.id for r in response_ids]
        
        if response_ids:
            # Eliminar registros relacionados en orden de dependencias
            answer_ids = db.query(Answer.id).filter(Answer.response_id.in_(response_ids)).all()
            answer_ids = [a.id for a in answer_ids]
            
            if answer_ids:
                # Eliminar primero en tablas que dependen de Answer
                db.query(AnswerFileSerial).filter(AnswerFileSerial.answer_id.in_(answer_ids)).delete(synchronize_session=False)
                db.query(AnswerHistory).filter(AnswerHistory.previous_answer_id.in_(answer_ids)).delete(synchronize_session=False)
            
            # 🔹 Borrar dependencias antes de Responses
            db.query(ResponseApproval).filter(ResponseApproval.response_id.in_(response_ids)).delete(synchronize_session=False)
            db.query(ResponseApprovalRequirement).filter(ResponseApprovalRequirement.response_id.in_(response_ids)).delete(synchronize_session=False)
            
            db.query(Answer).filter(Answer.response_id.in_(response_ids)).delete(synchronize_session=False)
            db.query(Response).filter(Response.id.in_(response_ids)).delete(synchronize_session=False)
        
        # 🔹 Eliminar approval_requirements relacionados al formulario
        db.query(ApprovalRequirement).filter(ApprovalRequirement.form_id == form_id).delete(synchronize_session=False)
        db.query(ApprovalRequirement).filter(ApprovalRequirement.required_form_id == form_id).delete(synchronize_session=False)
        
        # 🔹 Eliminar dependencias en otras tablas
        db.query(QuestionFilterCondition).filter(QuestionFilterCondition.form_id == form_id).delete(synchronize_session=False)
        db.query(FormAnswer).filter(FormAnswer.form_id == form_id).delete(synchronize_session=False)
        db.query(FormApproval).filter(FormApproval.form_id == form_id).delete(synchronize_session=False)
        db.query(FormApprovalNotification).filter(FormApprovalNotification.form_id == form_id).delete(synchronize_session=False)
        db.query(FormSchedule).filter(FormSchedule.form_id == form_id).delete(synchronize_session=False)
        db.query(FormModerators).filter(FormModerators.form_id == form_id).delete(synchronize_session=False)
        db.query(FormQuestion).filter(FormQuestion.form_id == form_id).delete(synchronize_session=False)
        db.query(FormCloseConfig).filter(FormCloseConfig.form_id == form_id).delete(synchronize_session=False)
        
        # 🔹 Finalmente eliminar el formulario
        db.delete(form)
        db.commit()
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ocurrió un error al eliminar el formulario: {str(e)}"
        )
    
    return {
        "message": "Formulario, respuestas y registros relacionados eliminados correctamente.",
        "relations_deleted": relations_info
    }

def analyze_form_relations(db: Session, form_id: int):
    """
    Analiza todas las relaciones de un formulario antes de eliminarlo.
    """
    relations = {}
    
    # Obtener información básica del formulario
    form = db.query(Form).filter(Form.id == form_id).first()
    if form:
        relations["form_info"] = {
            "id": form.id,
            "title": form.title,
            "description": form.description
        }
    
    # Respuestas del formulario
    responses = db.query(Response).filter(Response.form_id == form_id).all()
    if responses:
        relations["responses"] = {
            "count": len(responses),
            "name": "Respuestas de usuarios",
            "description": "Respuestas enviadas por los usuarios que llenaron el formulario",
            "icon": "📝",
            "category": "user_data"
        }
        
        # Respuestas con detalles
        response_ids = [r.id for r in responses]
        
        # Answers relacionadas
        answers = db.query(Answer).filter(Answer.response_id.in_(response_ids)).all()
        if answers:
            relations["answers"] = {
                "count": len(answers),
                "name": "Respuestas específicas",
                "description": "Respuestas individuales a cada pregunta del formulario",
                "icon": "✍️",
                "category": "user_data"
            }
            
            answer_ids = [a.id for a in answers]
            
            # AnswerFileSerial
            file_serials = db.query(AnswerFileSerial).filter(AnswerFileSerial.answer_id.in_(answer_ids)).all()
            if file_serials:
                relations["answer_file_serials"] = {
                    "count": len(file_serials),
                    "name": "Archivos adjuntos",
                    "description": "Documentos, imágenes y otros archivos subidos por los usuarios",
                    "icon": "📎",
                    "category": "files"
                }
            
            # AnswerHistory
            answer_history = db.query(AnswerHistory).filter(AnswerHistory.previous_answer_id.in_(answer_ids)).all()
            if answer_history:
                relations["answer_history"] = {
                    "count": len(answer_history),
                    "name": "Historial de cambios",
                    "description": "Registro de modificaciones realizadas a las respuestas",
                    "icon": "📋",
                    "category": "audit"
                }
        
        # ResponseApproval
        response_approvals = db.query(ResponseApproval).filter(ResponseApproval.response_id.in_(response_ids)).all()
        if response_approvals:
            relations["response_approvals"] = {
                "count": len(response_approvals),
                "name": "Aprobaciones de respuestas",
                "description": "Estados de aprobación o rechazo de las respuestas enviadas",
                "icon": "✅",
                "category": "approval"
            }
    
    # Relaciones directas con el formulario
    relations_to_check = [
        {
            "query": db.query(QuestionFilterCondition).filter(QuestionFilterCondition.form_id == form_id),
            "key": "question_filter_conditions",
            "name": "Condiciones de filtro",
            "description": "Reglas de lógica condicional para mostrar u ocultar preguntas",
            "icon": "🔍",
            "category": "logic"
        },
        {
            "query": db.query(FormAnswer).filter(FormAnswer.form_id == form_id),
            "key": "form_answers",
            "name": "Respuestas del formulario",
            "description": "Respuestas almacenadas en el formulario",
            "icon": "💬",
            "category": "user_data"
        },
        {
            "query": db.query(FormApproval).filter(FormApproval.form_id == form_id),
            "key": "form_approvals",
            "name": "Configuración de aprobaciones",
            "description": "Configuración del flujo de aprobación del formulario",
            "icon": "⚙️",
            "category": "config"
        },
        {
            "query": db.query(FormApprovalNotification).filter(FormApprovalNotification.form_id == form_id),
            "key": "form_approval_notifications",
            "name": "Notificaciones de aprobación",
            "description": "Configuración de notificaciones para el proceso de aprobación",
            "icon": "🔔",
            "category": "notifications"
        },
        {
            "query": db.query(FormSchedule).filter(FormSchedule.form_id == form_id),
            "key": "form_schedules",
            "name": "Programación del formulario",
            "description": "Configuración de fechas de apertura y cierre del formulario",
            "icon": "📅",
            "category": "schedule"
        },
        {
            "query": db.query(FormModerators).filter(FormModerators.form_id == form_id),
            "key": "form_moderators",
            "name": "Moderadores asignados",
            "description": "Usuarios con permisos de moderación en este formulario",
            "icon": "👥",
            "category": "permissions"
        },
        {
            "query": db.query(FormQuestion).filter(FormQuestion.form_id == form_id),
            "key": "form_questions",
            "name": "Preguntas del formulario",
            "description": "Todas las preguntas y campos configurados en el formulario",
            "icon": "❓",
            "category": "structure"
        },
        {
            "query": db.query(FormCloseConfig).filter(FormCloseConfig.form_id == form_id),
            "key": "form_close_configs",
            "name": "Configuración de cierre",
            "description": "Configuración del comportamiento cuando el formulario se cierra",
            "icon": "🔒",
            "category": "config"
        }
    ]
    
    for relation in relations_to_check:
        records = relation["query"].all()
        if records:
            relations[relation["key"]] = {
                "count": len(records),
                "name": relation["name"],
                "description": relation["description"],
                "icon": relation["icon"],
                "category": relation["category"]
            }
    
    return relations


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

def process_responses_with_history(responses: List[Response], db: Session) -> List[Dict]:
    """
    Procesa una lista de respuestas incluyendo su historial de cambios.
    
    Args:
        responses (List[Response]): Lista de respuestas a procesar
        db (Session): Sesión de la base de datos
        
    Returns:
        List[Dict]: Lista de respuestas formateadas con historial cuando aplique
    """
    if not responses:
        return []
    
    # Obtener todos los historiales de respuestas
    response_ids = [r.id for r in responses]
    
    history_stmt = select(AnswerHistory).where(AnswerHistory.response_id.in_(response_ids))
    histories = db.execute(history_stmt).scalars().all()
    
    # Obtener todos los IDs de respuestas (previous y current) del historial
    all_answer_ids = set()
    for history in histories:
        if history.previous_answer_id:
            all_answer_ids.add(history.previous_answer_id)
        all_answer_ids.add(history.current_answer_id)
    
    # Obtener todas las respuestas del historial con sus preguntas
    historical_answers = {}
    if all_answer_ids:
        answer_stmt = (
            select(Answer)
            .where(Answer.id.in_(all_answer_ids))
            .options(joinedload(Answer.question))
        )
        historical_answer_list = db.execute(answer_stmt).unique().scalars().all()
        
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
    
    def build_answer_chain(current_answer_id: int, max_depth: int = 5) -> List[Dict]:
        """
        Construye la cadena completa de historial para una respuesta.
        Retorna una lista ordenada desde la más antigua hasta la más reciente.
        """
        chain = []
        seen_ids = set()
        current_id = current_answer_id
        
        # Primero agregamos la respuesta actual
        if current_id in historical_answers:
            current_answer = historical_answers[current_id]
            chain.append({
                "type": "current",
                "answer_text": current_answer.answer_text,
                "file_path": current_answer.file_path,
                "answer_id": current_answer.id
            })
            seen_ids.add(current_id)
        
        # Luego buscamos hacia atrás en el historial
        depth = 0
        while current_id in history_map and depth < max_depth:
            history_entry = history_map[current_id]
            if history_entry.previous_answer_id and history_entry.previous_answer_id not in seen_ids:
                previous_id = history_entry.previous_answer_id
                if previous_id in historical_answers:
                    previous_answer = historical_answers[previous_id]
                    chain.append({
                        "type": "previous",
                        "answer_text": previous_answer.answer_text,
                        "file_path": previous_answer.file_path,
                        "answer_id": previous_answer.id
                    })
                    seen_ids.add(previous_id)
                    current_id = previous_id
                    depth += 1
                else:
                    break
            else:
                break
        
        # Invertir para que el orden sea: más antigua → más reciente
        chain.reverse()
        return chain
    
    # Procesar cada respuesta
    result = []
    for response in responses:
        approval_result = get_response_approval_status(response.approvals)
        
        # Procesar las respuestas considerando el historial
        processed_answers = []
        
        for answer in response.answers:
            # Si esta respuesta es una respuesta anterior en el historial, saltarla
            # (ya será incluida en el objeto con historial)
            if answer.id in previous_answer_ids:
                continue
                
            # Verificar si esta respuesta tiene historial
            if answer.id in history_map:
                history = history_map[answer.id]
                
                # Construir la cadena completa de historial
                answer_chain = build_answer_chain(answer.id)
                
                # Crear objeto con historial completo
                answer_with_history = {
                    "question_id": answer.question.id,
                    "question_text": answer.question.question_text,
                    "question_type": answer.question.question_type,
                    "has_history": True,
                    "updated_at": history.updated_at,
                    "answers": answer_chain
                }
                
                processed_answers.append(answer_with_history)
                    
            else:
                # Respuesta sin historial
                answer_without_history = {
                    "question_id": answer.question.id,
                    "question_text": answer.question.question_text,
                    "question_type": answer.question.question_type,
                    "has_history": False,
                    "answer_text": answer.answer_text,
                    "file_path": answer.file_path,
                    "answer_id": answer.id
                }
                
                processed_answers.append(answer_without_history)

        # Formatear respuesta completa
        formatted_response = {
            "response_id": response.id,
            "repeated_id": response.repeated_id,
            "submitted_at": response.submitted_at,
            "approval_status": approval_result["status"],
            "message": approval_result["message"],
            "answers": processed_answers,
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
                for ap in response.approvals
            ]
        }
        
        result.append(formatted_response)
    
    return result


def create_user_category(db: Session, category: UserCategoryCreate):
    try:
        new_category = UserCategory(name=category.name)
        db.add(new_category)
        db.commit()
        db.refresh(new_category)
        return new_category
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La categoría ya existe."
        )

def get_all_user_categories(db: Session):
    return db.query(UserCategory).order_by(UserCategory.name).all()


def delete_user_category_by_id(db: Session, category_id: int):
    category = db.query(UserCategory).filter(UserCategory.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada"
        )
    db.delete(category)
    db.commit()
    return {"message": "Categoría eliminada correctamente"}


# Servicios para categorías de formularios

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

# # Crear una nueva categoría de formulario
# def create_form_category(db: Session, category: FormCategoryCreate):
#     try:
#         db_category = FormCategory(
#             name=category.name,
#             description=category.description
#         )
#         db.add(db_category)
#         db.commit()
#         db.refresh(db_category)
#         return db_category
#     except IntegrityError:
#         db.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Ya existe una categoría con ese nombre"
#         )

# # Obtener todas las categorías de formularios
# def get_all_form_categories(db: Session):
#     return db.query(FormCategory).all()

# # Obtener categoría por ID
# def get_form_category_by_id(db: Session, category_id: int):
#     return db.query(FormCategory).filter(FormCategory.id == category_id).first()

# # Eliminar categoría por ID
# def delete_form_category_by_id(db: Session, category_id: int):
#     category = db.query(FormCategory).filter(FormCategory.id == category_id).first()
    
#     if not category:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Categoría no encontrada"
#         )
    
#     # Establecer en NULL la categoría de los formularios que la usan
#     forms_with_category = db.query(Form).filter(Form.id_category == category_id).all()
#     for form in forms_with_category:
#         form.id_category = None

#     # Eliminar la categoría
#     db.delete(category)
#     db.commit()
    
#     return {"message": "Categoría eliminada correctamente y formularios actualizados"}

# # Actualizar categoría de formulario
# def update_form_category_assignment(db: Session, form_id: int, category_id: Optional[int]):
#     form = db.query(Form).filter(Form.id == form_id).first()
#     if not form:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Formulario no encontrado"
#         )
    
#     if category_id is not None:
#         category = db.query(FormCategory).filter(FormCategory.id == category_id).first()
#         if not category:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Categoría no encontrada"
#             )
    
#     form.id_category = category_id
#     db.commit()
#     db.refresh(form)
#     return form

# # Obtener formularios por categoría
# def get_forms_by_category(db: Session, category_id: int):
#     category = db.query(FormCategory).filter(FormCategory.id == category_id).first()
#     if not category:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Categoría no encontrada"
#         )
    
#     return db.query(Form).filter(Form.id_category == category_id).all()

# # Obtener formularios sin categoría
# def get_forms_without_category(db: Session):
#     return db.query(Form).filter(Form.id_category.is_(None)).all()


def create_form_category(db: Session, category: FormCategoryCreate):
    # Validar que el padre existe si se especifica
    if category.parent_id is not None:
        parent = db.query(FormCategory).filter(FormCategory.id == category.parent_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La categoría padre no existe"
            )
    
    # Verificar nombre único dentro del mismo nivel
    existing = db.query(FormCategory).filter(
        and_(
            FormCategory.name == category.name,
            FormCategory.parent_id == category.parent_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe una categoría con ese nombre en este nivel"
        )
    
    try:
        db_category = FormCategory(**category.dict())
        db.add(db_category)
        db.commit()
        db.refresh(db_category)
        return db_category
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear la categoría: {str(e)}"
        )

# Obtener árbol completo de categorías
def get_category_tree(db: Session) -> List[FormCategoryTreeResponse]:
    # Obtener solo las categorías raíz (sin padre)
    root_categories = db.query(FormCategory)\
        .filter(FormCategory.parent_id.is_(None))\
        .order_by(FormCategory.order, FormCategory.name)\
        .all()
    
    def build_tree(category: FormCategory) -> FormCategoryTreeResponse:
        # Contar formularios
        forms_count = db.query(func.count(Form.id))\
            .filter(Form.id_category == category.id)\
            .scalar()
        
        # Construir respuesta
        response = FormCategoryTreeResponse(
            id=category.id,
            name=category.name,
            description=category.description,
            parent_id=category.parent_id,
            icon=category.icon,
            color=category.color,
            order=category.order,
            created_at=category.created_at,
            updated_at=category.updated_at,
            forms_count=forms_count,
            children_count=len(category.children),
            children=[]
        )
        
        # Recursivamente construir hijos
        for child in sorted(category.children, key=lambda x: (x.order or 0, x.name)):
            response.children.append(build_tree(child))
        
        return response
    
    return [build_tree(cat) for cat in root_categories]

# Obtener categorías de un nivel específico
def get_categories_by_parent(db: Session, parent_id: Optional[int] = None):
    query = db.query(FormCategory).filter(FormCategory.parent_id == parent_id)
    return query.order_by(FormCategory.order, FormCategory.name).all()

# Actualizar categoría
def update_form_category_1(db: Session, category_id: int, category_update: FormCategoryUpdate):
    category = db.query(FormCategory).filter(FormCategory.id == category_id).first()
    
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada"
        )
    
    # Validar nuevo padre si se especifica
    if category_update.parent_id is not None:
        # Evitar ciclos: no puede ser su propio padre ni descendiente
        if category_update.parent_id == category_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Una categoría no puede ser su propio padre"
            )
        
        # Verificar que no se crea un ciclo
        if is_descendant(db, category_id, category_update.parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede mover a una subcategoría de sí misma"
            )
        
        parent = db.query(FormCategory).filter(FormCategory.id == category_update.parent_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La categoría padre no existe"
            )
    
    # Actualizar campos
    for field, value in category_update.dict(exclude_unset=True).items():
        setattr(category, field, value)
    
    try:
        db.commit()
        db.refresh(category)
        return category
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar la categoría: {str(e)}"
        )

# Función auxiliar para detectar ciclos
def is_descendant(db: Session, category_id: int, potential_parent_id: int) -> bool:
    """Verifica si potential_parent_id es descendiente de category_id"""
    current = db.query(FormCategory).filter(FormCategory.id == potential_parent_id).first()
    
    while current:
        if current.parent_id == category_id:
            return True
        if current.parent_id is None:
            return False
        current = db.query(FormCategory).filter(FormCategory.id == current.parent_id).first()
    
    return False

# Mover categoría
def move_category(db: Session, category_id: int, move_data: FormCategoryMove):
    return update_form_category_1(
        db, 
        category_id, 
        FormCategoryUpdate(
            parent_id=move_data.new_parent_id,
            order=move_data.new_order
        )
    )

# Eliminar categoría
def delete_form_category(db: Session, category_id: int, force: bool = False):
    category = db.query(FormCategory).filter(FormCategory.id == category_id).first()
    
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada"
        )
    
    # Verificar si tiene hijos
    if category.children and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede eliminar una categoría con subcategorías. Use force=true para eliminar todo el árbol."
        )
    
    # Mover formularios a la categoría padre o a null
    forms = db.query(Form).filter(Form.id_category == category_id).all()
    for form in forms:
        form.id_category = category.parent_id
    
    try:
        # Si force=True, las subcategorías se eliminan en cascada
        db.delete(category)
        db.commit()
        return {"message": "Categoría eliminada exitosamente", "forms_moved": len(forms)}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar la categoría: {str(e)}"
        )

# Obtener ruta completa (breadcrumb)
def get_category_path(db: Session, category_id: int) -> List[FormCategoryResponse]:
    path = []
    current = db.query(FormCategory).filter(FormCategory.id == category_id).first()
    
    while current:
        path.insert(0, current)
        if current.parent_id:
            current = db.query(FormCategory).filter(FormCategory.id == current.parent_id).first()
        else:
            break
    
    return path

def toggle_form_status(db: Session, form_id: int, is_enabled: bool):
    """
    Habilita o deshabilita un formulario.
    Solo administradores pueden usar esta función.
    """

        # Buscar el formulario
    form = db.query(Form).filter(Form.id == form_id).first()
        
    if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Form with id {form_id} not found"
            )
        
        # Actualizar el estado
    form.is_enabled = is_enabled
    db.commit()
    db.refresh(form)
        
    return {
            "message": f"Form {'enabled' if is_enabled else 'disabled'} successfully",
            "form_id": form.id,
            "title": form.title,
            "is_enabled": form.is_enabled
        }
        

def crear_palabras_clave_service(data: PalabrasClaveCreate, db: Session):
    """
    Crea un nuevo registro en la tabla form_palabras_clave.
    """
    keywords_str = ",".join([k.strip() for k in data.keywords if k.strip()])

    nueva_palabra = PalabrasClave(
        form_id=data.form_id,
        keywords=keywords_str
    )

    db.add(nueva_palabra)
    db.commit()
    db.refresh(nueva_palabra)

    return nueva_palabra

def create_bitacora_log_simple(db: Session, data: BitacoraLogsSimpleCreate, current_user: User):
    """
    Crea un registro en la tabla bitacora_logs_simple.
    """
    registrado_por = f"{current_user.name} - {current_user.num_document}"

    new_log = BitacoraLogsSimple(
        clasificacion=data.clasificacion,
        titulo=data.titulo,
        fecha=data.fecha,
        hora=data.hora,
        ubicacion=data.ubicacion,
        participantes=data.participantes,
        descripcion=data.descripcion,
        archivos=json.dumps(data.archivos) if data.archivos else None,
        registrado_por=registrado_por
    )

    try:
        db.add(new_log)
        db.commit()
        db.refresh(new_log)
        return new_log
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error de integridad en base de datos: {str(e.orig)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creando registro: {str(e)}"
        )
    
def get_all_bitacora_eventos(db: Session):
    """
    Obtiene todos los registros de la tabla bitacora_eventos.
    """
    try:
        logs = db.query(BitacoraLogsSimple).order_by(BitacoraLogsSimple.created_at.desc()).all()
        return logs
    except Exception as e:
        print(f"⚠️ Error al obtener bitácora: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los registros de bitácora."
        )
    
def get_bitacora_eventos_by_user(db: Session, user_identifier: str):
    """
    Obtiene los eventos donde el usuario autenticado:
    - Es el creador (registrado_por)
    - O aparece como participante (campo participantes)
    """
    try:
        logs = (
            db.query(BitacoraLogsSimple)
            .filter(
                or_(
                    BitacoraLogsSimple.registrado_por.ilike(f"%{user_identifier}%"),
                    and_(
                        BitacoraLogsSimple.participantes.isnot(None),
                        BitacoraLogsSimple.participantes.ilike(f"%{user_identifier}%")
                    )
                )
            )
            .order_by(BitacoraLogsSimple.created_at.desc())
            .all()
        )

        # 🔹 Eliminar duplicados por si un usuario aparece en ambos roles
        unique_logs = {log.id: log for log in logs}.values()

        return list(unique_logs)

    except Exception as e:
        print(f"⚠️ Error al obtener bitácora del usuario: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los registros de bitácora del usuario."
        )
    
def get_all_bitacora_formatos(db: Session):
    """
    Obtiene todos los registros de la bitácora con:
    - Formato (título)
    - Categoría del formato
    - Usuario que respondió
    - Preguntas y respuestas asociadas
    """
    bitacoras = db.query(RelationBitacora).all()
    data = []

    for rel in bitacoras:
        response = db.query(Response).filter(Response.id == rel.id_response).first()
        if not response:
            continue

        user = db.query(User).filter(User.id == response.user_id).first()
        form = db.query(Form).filter(Form.id == response.form_id).first()

        # ✅ Obtener la categoría del formato (si existe)
        categoria_form = None
        if form and form.id_category:
            categoria_obj = db.query(FormCategory).filter(FormCategory.id == form.id_category).first()
            categoria_form = categoria_obj.name if categoria_obj else "Sin categoría"
        
          # ✅ Obtener las palabras clave del formato
        palabras_obj = (
            db.query(PalabrasClave)
            .filter(PalabrasClave.form_id == form.id)
            .first()
            if form else None
        )
        palabras_clave = palabras_obj.keywords.split(",") if palabras_obj and palabras_obj.keywords else []


        # ✅ Obtener todas las preguntas y respuestas asociadas
        qa_items = db.query(QuestionAndAnswerBitacora).filter(
            QuestionAndAnswerBitacora.id_relation_bitacora == rel.id
        ).all()

        preguntas_respuestas = [
            {"pregunta": qa.question, "respuesta": qa.answer} for qa in qa_items
        ]

        # ✅ Construir el objeto de salida
        data.append({
            "id": rel.id,
            "formato": form.title if form else "Desconocido",
            "categoria_form": categoria_form or "Sin categoría",
            "usuario": user.name if user else "Anónimo",
            "respuestas": preguntas_respuestas,
            "palabras_clave": palabras_clave, 
            "created_at": rel.created_at,
        })

    return data

# def atender_y_finalizar_service(evento_id: int, usuario: str, num_document: str, db: Session):
#     """Marca un evento como atendido y finalizado por un usuario."""
#     evento = db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id == evento_id).first()

#     if not evento:
#         raise ValueError("Evento no encontrado")

#     if not usuario or not num_document:
#         raise ValueError("Datos del usuario incompletos")

#     try:
#         evento.estado = EstadoEvento.finalizado
#         evento.atendido_por = f"{usuario} - {num_document}"
#         evento.updated_at = datetime.utcnow()

#         db.commit()
#         db.refresh(evento)
#         return evento
#     except Exception as e:
#         db.rollback()
#         raise RuntimeError(f"Error al actualizar el evento: {e}")
    
def reabrir_evento_service(evento_id: int, usuario: str, num_document: str, db: Session):
    """Cambia el estado del evento a 'pendiente' y registra quién lo reabrió."""
    evento = db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id == evento_id).first()

    if not evento:
        raise ValueError("Evento no encontrado")

    if evento.estado == EstadoEvento.pendiente:
        raise ValueError("El evento ya está en estado pendiente")

    try:
        evento.estado = EstadoEvento.pendiente
        evento.atendido_por = f"{usuario} - {num_document}"
        evento.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(evento)
        return evento
    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Error al reabrir el evento: {e}")


def response_bitacora_log_simple(db: Session, log_data, current_user, evento_id: int):
    """
    Marca un evento como atendido y crea una respuesta asociada.
    """

    # 1️⃣ Buscar el evento original
    evento = db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento original no encontrado")

    # 2️⃣ Marcar el evento original como respondido
    evento.estado = EstadoEvento.respondido
    evento.atendido_por = f"{current_user.name} - {current_user.num_document}"
    evento.updated_at = datetime.utcnow()

    # 3️⃣ Determinar los participantes del nuevo evento
    # Autor original del evento
    participante_original = evento.registrado_por

    # Participantes enviados desde el front (puede venir en string, lista, o None)
    participantes_nuevos = []

    if log_data.participantes:
        # Si viene como string, convertir en lista
        if isinstance(log_data.participantes, str):
            # Si es un string separado por comas, lo convertimos
            participantes_nuevos = [p.strip() for p in log_data.participantes.split(",") if p.strip()]
        elif isinstance(log_data.participantes, list):
            participantes_nuevos = log_data.participantes

    # Agregar el autor original si no está ya incluido
    if participante_original not in participantes_nuevos:
        participantes_nuevos.append(participante_original)

    # Convertir a string final (unificado por comas)
    participantes_final = ", ".join(participantes_nuevos)

    # 4️⃣ Crear el nuevo evento como respuesta
    nueva_respuesta = BitacoraLogsSimple(
        clasificacion=evento.clasificacion,
        titulo=log_data.titulo,
        fecha=log_data.fecha,
        hora=log_data.hora,
        ubicacion=log_data.ubicacion,
        participantes=participantes_final,  # ✅ aquí va la lista actualizada
        descripcion=log_data.descripcion,
        archivos=json.dumps(log_data.archivos) if log_data.archivos else None,
        registrado_por=f"{current_user.name} - {current_user.num_document}",
        estado=EstadoEvento.pendiente,
        evento_responde_id=evento.id
    )

    db.add(nueva_respuesta)
    db.commit()
    db.refresh(nueva_respuesta)

    return {
        "evento_atendido": {
            "id": evento.id,
            "titulo": evento.titulo,
            "estado": evento.estado.value,
            "atendido_por": evento.atendido_por,
            "updated_at": evento.updated_at,
        },
        "respuesta_creada": {
            "id": nueva_respuesta.id,
            "clasificacion": nueva_respuesta.clasificacion,
            "titulo": nueva_respuesta.titulo,
            "estado": nueva_respuesta.estado.value,
            "registrado_por": nueva_respuesta.registrado_por,
            "participantes": nueva_respuesta.participantes,  # ✅ mostramos resultado final
            "evento_responde_id": nueva_respuesta.evento_responde_id,
            "created_at": nueva_respuesta.created_at,
        },
    }

def finalizar_conversacion_completa(db: Session, evento_id: int, usuario: str):
    """
    Finaliza toda una conversación (evento raíz y todas sus respuestas).
    """
    # Buscar el evento base
    evento = db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id == evento_id).first()
    if not evento:
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    # Buscar el evento raíz (el primero de la conversación)
    evento_raiz = evento
    while evento_raiz.evento_responde_id:
        evento_raiz = (
            db.query(BitacoraLogsSimple)
            .filter(BitacoraLogsSimple.id == evento_raiz.evento_responde_id)
            .first()
        )
        if not evento_raiz:
            raise HTTPException(status_code=404, detail="Evento raíz no encontrado")

    # Buscar todos los eventos que pertenecen a esa conversación
    ids_conversacion = [evento_raiz.id]
    pendientes = [evento_raiz.id]
    while pendientes:
        actual_id = pendientes.pop(0)
        hijos = (
            db.query(BitacoraLogsSimple)
            .filter(BitacoraLogsSimple.evento_responde_id == actual_id)
            .all()
        )
        for hijo in hijos:
            ids_conversacion.append(hijo.id)
            pendientes.append(hijo.id)

    # Actualizar el estado de todos los eventos
    db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id.in_(ids_conversacion)).update(
        {
            BitacoraLogsSimple.estado: EstadoEvento.finalizado,
            BitacoraLogsSimple.atendido_por: usuario,
            BitacoraLogsSimple.updated_at: datetime.utcnow(),
        },
        synchronize_session=False
    )
    db.commit()

    return {
        "message": f"Conversación finalizada correctamente. {len(ids_conversacion)} eventos actualizados.",
        "eventos_finalizados": ids_conversacion,
    }

def obtener_conversacion_completa(db: Session, evento_id: int):
    """
    Devuelve el evento raíz y todas sus respuestas (en orden de creación),
    incluyendo todos los campos relevantes y archivos adjuntos.
    """

    evento = db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id == evento_id).first()
    if not evento:
        return None

    # 🔁 Si este evento es una respuesta, buscamos la raíz
    while evento.evento_responde_id:
        evento = db.query(BitacoraLogsSimple).filter(BitacoraLogsSimple.id == evento.evento_responde_id).first()

    # 🧩 Función recursiva para construir el árbol de respuestas
    def build_tree(ev: BitacoraLogsSimple):
        respuestas = (
            db.query(BitacoraLogsSimple)
            .filter(BitacoraLogsSimple.evento_responde_id == ev.id)
            .order_by(BitacoraLogsSimple.created_at.asc())
            .all()
        )

        # ✅ Convertimos los archivos desde JSON si existen
        archivos = []
        if ev.archivos:
            try:
                archivos = json.loads(ev.archivos)
            except json.JSONDecodeError:
                archivos = [ev.archivos]  # fallback si no está en formato JSON

        return {
            "id": ev.id,
            "clasificacion": ev.clasificacion,
            "titulo": ev.titulo,
            "descripcion": ev.descripcion,
            "fecha": ev.fecha,
            "hora": ev.hora,
            "ubicacion": ev.ubicacion,
            "participantes": ev.participantes,
            "registrado_por": ev.registrado_por,
            "atendido_por": ev.atendido_por,
            "estado": ev.estado.value if hasattr(ev.estado, "value") else ev.estado,
            "archivos": archivos,
            "created_at": ev.created_at,
            "updated_at": ev.updated_at,
            "respuestas": [build_tree(r) for r in respuestas],
        }

    return build_tree(evento)


def get_palabras_clave_by_form(db: Session, form_id: int):
    return db.query(PalabrasClave).filter(PalabrasClave.form_id == form_id).first()
