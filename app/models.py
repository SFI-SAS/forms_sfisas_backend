from datetime import datetime
from sqlalchemy import (
    Boolean, Column, BigInteger, DateTime, String, Text, ForeignKey, TIMESTAMP, Enum, func, text
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class UserType(enum.Enum):
    admin = "admin"
    respondent = "respondent"

# Definir ENUM para form_status

    
class QuestionType(enum.Enum):
    text = "text"
    multiple_choice = "multiple_choice"
    file = "file"

class Models(Base):
    __abstract__ = True

# Modelo Users
class User(Base):
    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    num_document = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    telephone = Column(String(20), unique=True, nullable=False)
    user_type = Column(Enum(UserType), default=UserType.respondent, nullable=False)
    nickname = Column(String(100), nullable=True)  # Nuevo campo agregado
    password = Column(Text, nullable=False)

    forms = relationship('Form', back_populates='user')
    responses = relationship('Response', back_populates='user')

# Modelo Forms
class Form(Base):
    __tablename__ = 'forms'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=False)  # Relación con Project

    title = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    user = relationship('User', back_populates='forms')
    project = relationship('Project', back_populates='forms')  # Relación con el modelo Project
    questions = relationship("Question", secondary="form_questions", back_populates="forms")
    responses = relationship('Response', back_populates='form')


# Modelo Questions
class Question(Base):
    __tablename__ = 'questions'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(String(255), nullable=False)
    question_type = Column(Enum(QuestionType), server_default=QuestionType.text.name, nullable=False)
    required = Column(Boolean, nullable=False, server_default=text("1"))  # Solución aquí

    forms = relationship('Form', secondary='form_questions', back_populates='questions')
    options = relationship('Option', back_populates='question')
    answers = relationship('Answer', back_populates='question')
# Tabla intermedia para la relación muchos a muchos entre Form y Question
class FormQuestion(Base):
    __tablename__ = 'form_questions'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'))
    question_id = Column(BigInteger, ForeignKey('questions.id'))
    
# Modelo Options
class Option(Base):
    __tablename__ = 'options'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    option_text = Column(String(255), nullable=False)

    question = relationship('Question', back_populates='options')

# Modelo Responses
class Response(Base):
    __tablename__ = 'responses'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    submitted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    form = relationship('Form', back_populates='responses')
    user = relationship('User', back_populates='responses')
    answers = relationship('Answer', back_populates='response')

# Modelo Answers
class Answer(Base):
    __tablename__ = 'answers'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    answer_text = Column(String(255), nullable=True)
    file_path = Column(Text, nullable=True)

    response = relationship('Response', back_populates='answers')
    question = relationship('Question', back_populates='answers')
    
    
# Modelo Project
class Project(Base):
    __tablename__ = 'projects'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    forms = relationship('Form', back_populates='project')  # Relación inversa con Form
