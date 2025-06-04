from sqlalchemy import (
    JSON, Boolean, Column, BigInteger, DateTime, Integer, LargeBinary, String, Text, ForeignKey, TIMESTAMP, Enum, func, text
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum
from sqlalchemy import event

from pytz import timezone
BOGOTA_TZ = timezone('America/Bogota')

class UserType(enum.Enum):
    admin = "admin"
    creator = "creator"
    user = "user"

# Definir ENUM para form_status

class QuestionType(str, enum.Enum):
    text = "text"
    multiple_choice = "multiple_choice"
    one_choice = "one_choice"
    file = "file"
    table = "table"
    date = "date"
    number = "number"

class ApprovalStatus(enum.Enum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"

class FormatType(enum.Enum):
    abierto = "abierto"
    cerrado = "cerrado"
    semi_abierto = "semi_abierto"


class Models(Base):
    __abstract__ = True

# Modelo Users
class User(Base):
    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    num_document = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    telephone = Column(String(20), nullable=False)
    user_type = Column(Enum(UserType), default=UserType.user, nullable=False)
    nickname = Column(String(100), nullable=True)  # Nuevo campo agregado
    password = Column(Text, nullable=False)
    
    form_moderators = relationship('FormModerators', back_populates='user')
    forms = relationship('Form', back_populates='user')
    responses = relationship('Response', back_populates='user')  # Corrige esto si tienes definida la tabla Response

# Modelo Forms
class Form(Base):
    __tablename__ = 'forms'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    format_type = Column(Enum(FormatType), nullable=False, default=FormatType.abierto)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    form_design = Column(JSON, nullable=True, default=dict)
    user = relationship('User', back_populates='forms')
    form_moderators = relationship("FormModerators", back_populates="form", cascade="all, delete-orphan")
    questions = relationship("Question", secondary="form_questions", back_populates="forms")
    responses = relationship('Response', back_populates='form')  # Esto debe coincidir con la tabla Response
    form_answers = relationship('FormAnswer', back_populates='form')  # Nueva relación
    
    

# Modelo Questions
class Question(Base):
    __tablename__ = 'questions'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(String(255), nullable=False)
    question_type = Column(Enum(QuestionType), server_default=QuestionType.text.name, nullable=False)
    required = Column(Boolean, nullable=False, server_default=text("1"))  # Solución aquí
    root = Column(Boolean, nullable=False, server_default=text("0"))


    forms = relationship('Form', secondary='form_questions', back_populates='questions')
    options = relationship('Option', back_populates='question')
    answers = relationship('Answer', back_populates='question')
    form_answers = relationship('FormAnswer', back_populates='question') 
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
    mode = Column(String(20), nullable=False) 
    mode_sequence = Column(Integer, nullable=False)  
    repeated_id = Column(String(80), nullable=True)
    submitted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    form = relationship('Form', back_populates='responses')
    user = relationship('User', back_populates='responses')
    answers = relationship('Answer', back_populates='response')
    approvals = relationship("ResponseApproval", back_populates="response")

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
    file_serial = relationship('AnswerFileSerial', back_populates='answer', uselist=False, cascade='all, delete-orphan')

    
# Modelo Project
class Project(Base):
    __tablename__ = 'projects'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class FormSchedule(Base):
    __tablename__ = 'form_schedules'


    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    frequency_type = Column(String(50), nullable=False)  # "daily", "weekly", "monthly", "periodic", "specific_date"
    repeat_days = Column(String(255), nullable=True)  # Para "weekly" -> ejemplo: "monday,wednesday,friday"
    interval_days = Column(Integer, nullable=True)  # Para "periodic" -> cada X días (por ejemplo cada 3 días)
    specific_date = Column(DateTime, nullable=True)  # Para "specific_date" -> fecha exacta
    status = Column(Boolean, default=True, nullable=False)


class FormModerators(Base):
    __tablename__ = 'form_moderators'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id', ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    # Relaciones
    form = relationship('Form', back_populates='form_moderators')
    user = relationship('User', back_populates='form_moderators')
    
    

class FormAnswer(Base):
    __tablename__ = 'form_answers'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    is_repeated = Column(Boolean, default=False, nullable=False)

    # Relaciones
    form = relationship('Form', back_populates='form_answers')
    question = relationship('Question', back_populates='form_answers')


class QuestionTableRelation(Base):
    __tablename__ = 'question_table_relations'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False, unique=True)
    related_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=True)
    name_table = Column(String(255), nullable=False)
    field_name = Column(String(255), nullable=True)

    question = relationship('Question', foreign_keys=[question_id], backref='table_relation', uselist=False)

    related_question = relationship('Question', foreign_keys=[related_question_id], backref='related_table_relations', uselist=False)
    
    

class AnswerFileSerial(Base):
    __tablename__ = 'answer_file_serials'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    serial = Column(String(100), nullable=False)
    answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=False)

    answer = relationship('Answer', back_populates='file_serial')



class FormApproval(Base):
    __tablename__ = 'form_approvals'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    sequence_number = Column(Integer, nullable=False, default=1)
    is_mandatory = Column(Boolean, default=True)
    deadline_days = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    form = relationship("Form", backref="approval_template")
    user = relationship("User", backref="forms_to_approve")


class ResponseApproval(Base):
    __tablename__ = 'response_approvals'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    is_mandatory = Column(Boolean, default=True)
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.pendiente, nullable=False)
    
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    message = Column(Text, nullable=True)
    reconsideration_requested = Column(Boolean, nullable=True, default=False)
    response = relationship("Response", back_populates="approvals")
    user = relationship("User")


class FormApprovalNotification(Base):
    __tablename__ = 'form_approval_notifications'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    notify_on = Column(Enum("cada_aprobacion", "aprobacion_final", name="notify_type"), nullable=False)

    form = relationship("Form", backref="notification_rules")
    user = relationship("User")


class EmailConfig(Base):
    __tablename__ = "email_config"

    id = Column(Integer, primary_key=True, index=True)
    email_address = Column(String(255), nullable=False)  
    is_active = Column(Boolean, default=True)
    
    
class QuestionFilterCondition(Base):
    __tablename__ = "question_filter_conditions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    filtered_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    source_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    condition_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    expected_value = Column(String(255), nullable=False)
    operator = Column(String(10), nullable=False, default="==")

    form = relationship("Form")
    filtered_question = relationship("Question", foreign_keys=[filtered_question_id])
    source_question = relationship("Question", foreign_keys=[source_question_id])
    condition_question = relationship("Question", foreign_keys=[condition_question_id])

    
@event.listens_for(EmailConfig.__table__, "after_create")
def insert_default_emails(target, connection, **kwargs):
    """ Inserta dos registros de ejemplo al crear la tabla """
    connection.execute(
        target.insert(),
        [
            {"email_address": "example1@domain.com", "is_active": False},
            {"email_address": "example2@domain.com", "is_active": False},
        ],
    )
    
    