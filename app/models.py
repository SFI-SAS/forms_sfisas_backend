from sqlalchemy import (
    Column, BigInteger, String, Text, ForeignKey, TIMESTAMP, Enum, func
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class UserType(enum.Enum):
    admin = "admin"
    respondent = "respondent"

# Definir ENUM para form_status
class FormStatus(enum.Enum):
    draft = 'draft'
    published = 'published'
    
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
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password = Column(Text, nullable=False)
    user_type = Column(Enum(UserType), default=UserType.respondent, nullable=False)

    forms = relationship('Form', back_populates='user')
    responses = relationship('Response', back_populates='user')

# Modelo Forms
class Form(Base):
    __tablename__ = 'forms'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    status = Column(Enum(FormStatus), server_default=FormStatus.draft.name, nullable=False)

    user = relationship('User', back_populates='forms')
    questions = relationship("Question", secondary="form_questions", back_populates="forms")
    responses = relationship('Response', back_populates='form')

# Modelo Questions
class Question(Base):
    __tablename__ = 'questions'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(String(255), nullable=False)
    question_type = Column(Enum(QuestionType), server_default=QuestionType.text.name, nullable=False)  # Utiliza el enum aquí

    forms = relationship('Form', secondary='form_questions', back_populates='questions')
    options = relationship('Option', back_populates='question')
    answers = relationship('Answer', back_populates='question')
    
    
# Tabla intermedia para la relación muchos a muchos entre Form y Question
class FormQuestion(Base):
    __tablename__ = 'form_questions'
    form_id = Column(BigInteger, ForeignKey('forms.id'), primary_key=True)
    question_id = Column(BigInteger, ForeignKey('questions.id'), primary_key=True)
    
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