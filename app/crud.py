from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from app.models import Project, User, Form, Question, Option, Response, Answer, FormQuestion
from app.schemas import ProjectCreate, UserCreate, FormCreate, QuestionCreate, OptionCreate, ResponseCreate, AnswerCreate, UserType, UserUpdate, QuestionUpdate
from fastapi import HTTPException, status
from typing import List

# User CRUD Operations
def create_user(db: Session, user: UserCreate):
    db_user = User(num_document=user.num_document, name=user.name, email=user.email, telephone=user.telephone, password=user.password)
    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    except IntegrityError as e:
        print(e)
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

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
        db_form = Form(user_id=user_id, title=form.title, description=form.description, status=form.status)
        db.add(db_form)
        db.commit()
        db.refresh(db_form)
        return db_form
    except IntegrityError:
        db.rollback()
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
        db_question = Question(question_text=question.question_text, question_type=question.question_type)
        db.add(db_question)
        db.commit()
        db.refresh(db_question)
        return db_question        
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error to create a question with the provided information")


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