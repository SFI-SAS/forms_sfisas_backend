from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from app.models import FormSchedule, Project, User, Form, Question, Option, Response, Answer, FormQuestion
from app.schemas import ProjectCreate, UserCreate, FormCreate, QuestionCreate, OptionCreate, ResponseCreate, AnswerCreate, UserType, UserUpdate, QuestionUpdate
from fastapi import HTTPException, status
from typing import List
from datetime import datetime


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

# Form CRUD Operations
def create_form(db: Session, form: FormCreate, user_id: int):
    try:
        db_form = Form(
            user_id=user_id,
            project_id=form.project_id,  
            title=form.title,
            description=form.description,
            created_at=datetime.utcnow()  
        )
        
        db.add(db_form)  # Agregar a la sesión
        db.commit()  # Confirmar cambios en la DB
        db.refresh(db_form)  # Actualizar el objeto con los valores generados

        return db_form  # Devolver el formulario creado
    except IntegrityError:
        db.rollback()  # Revertir cambios si hay un error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error to create form with the information provided")
    
    
def get_form(db: Session, form_id: int):
    return db.query(Form).options(
        joinedload(Form.questions).joinedload(Question.options)  # Cargar preguntas y opciones en una sola consulta
    ).filter(Form.id == form_id).first()

def get_forms(db: Session, skip: int = 0, limit: int = 10):
    return db.query(Form).offset(skip).limit(limit).all()

# Question CRUD Operations
def create_question(db: Session, question: QuestionCreate):
    try:
        db_question = Question(
            question_text=question.question_text,
            question_type=question.question_type,
            required=question.required  # Se pasa el valor de required
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

def get_questions(db: Session, skip: int = 0, limit: int = 10):
    return db.query(Question).offset(skip).limit(limit).all()

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

def post_create_response(db: Session, form_id: int, user_id: int):
    """Función para crear una nueva respuesta en la base de datos si la encuesta y el usuario existen."""

    form = db.query(Form).filter(Form.id == form_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Verificar si ya existe una respuesta para el mismo form_id y user_id
    existing_response = db.query(Response).filter(
        Response.form_id == form_id,
        Response.user_id == user_id
    ).first()

    if existing_response:
        return {"message": "Respuesta ya existe", "response_id": existing_response.id}

    # Si no existe, crear una nueva respuesta
    response = Response(form_id=form_id, user_id=user_id, submitted_at=func.now())

    db.add(response)
    db.commit()
    db.refresh(response)

    return {"message": "Respuesta guardada exitosamente", "response_id": response.id}

def create_answer_in_db(answer, db: Session):
    existing_answer = db.query(Answer).filter(
        Answer.response_id == answer.response_id,
        Answer.question_id == answer.question_id
    ).first()

    if existing_answer:
        # Actualizar la respuesta existente
        existing_answer.answer_text = answer.answer_text
        existing_answer.file_path = answer.file_path
        message = "Respuesta actualizada exitosamente"
    else:
        # Crear una nueva respuesta si no existe
        new_answer = Answer(
            response_id=answer.response_id,
            question_id=answer.question_id,
            answer_text=answer.answer_text,
            file_path=answer.file_path
        )
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


def create_form_schedule(db: Session, form_id: int, user_id: int, repeat_days: str | None, status: bool):
    new_schedule = FormSchedule(
        form_id=form_id,
        user_id=user_id,
        repeat_days=repeat_days,
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