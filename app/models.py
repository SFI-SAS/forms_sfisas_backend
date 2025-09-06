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
    time = "time"
    location = "location"
    firm = "firm"
    regisfacial = "regisfacial"
    
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
    nickname = Column(String(100), nullable=True)
    password = Column(Text, nullable=False)
    recognition_id = Column(String(100), nullable=True, unique=True)  # <-- nuevo campo
    
    id_category = Column(BigInteger, ForeignKey('user_categories.id'), nullable=True)
    category = relationship("UserCategory", back_populates="users")
    
    # Relaciones existentes
    form_moderators = relationship('FormModerators', back_populates='user')
    forms = relationship('Form', back_populates='user')
    responses = relationship('Response', back_populates='user')

class UserCategory(Base):
    __tablename__ = 'user_categories'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)

    users = relationship("User", back_populates="category")

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
    
    # Nuevo campo para categoría
    id_category = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
    
    # Relaciones existentes
    user = relationship('User', back_populates='forms')
    form_moderators = relationship("FormModerators", back_populates="form", cascade="all, delete-orphan")
    questions = relationship("Question", secondary="form_questions", back_populates="forms")
    responses = relationship('Response', back_populates='form')
    form_answers = relationship('FormAnswer', back_populates='form')
    
    # Nueva relación con categoría
    category = relationship("FormCategory", back_populates="forms")


class FormCategory(Base):
    __tablename__ = 'form_categories'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255), nullable=True)  # Opcional: descripción de la categoría
    
    # Relación con formularios
    forms = relationship("Form", back_populates="category")

# Modelo Questions
class Question(Base):
    __tablename__ = 'questions'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(String(255), nullable=False)
    question_type = Column(Enum(QuestionType), server_default=QuestionType.text.name, nullable=False)
    required = Column(Boolean, nullable=False, server_default=text("1"))
    root = Column(Boolean, nullable=False, server_default=text("0"))

    id_category = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)

    # Relaciones
    category = relationship('QuestionCategory', back_populates='questions')
    forms = relationship('Form', secondary='form_questions', back_populates='questions')
    options = relationship('Option', back_populates='question')
    answers = relationship('Answer', back_populates='question')
    form_answers = relationship('FormAnswer', back_populates='question')
# Tabla intermedia para la relación muchos a muchos entre Form y Question

class QuestionCategory(Base):
    __tablename__ = 'question_categories'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)

    # Campo que permite jerarquía (categoría padre)
    parent_id = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)

    # Relación con su categoría padre
    parent = relationship('QuestionCategory', remote_side=[id], backref='subcategories')

    # Relación con preguntas
    questions = relationship('Question', back_populates='category')

    
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

class ResponseStatus(enum.Enum):
    draft = "draft"                    # Guardado pero no enviado para aprobación
    submitted = "submitted"            # Enviado para aprobación
    approved = "approved"              # Aprobado completamente
    rejected = "rejected"  
    
class Response(Base):
    __tablename__ = 'responses'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    mode = Column(String(20), nullable=False) 
    mode_sequence = Column(Integer, nullable=False)  
    repeated_id = Column(String(80), nullable=True)
    submitted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    
    status = Column(Enum(ResponseStatus), default=ResponseStatus.draft, nullable=False)


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
    
    # Nuevos campos
    required_forms_ids = Column(JSON, nullable=True)  # Lista de IDs de formularios requeridos
    follows_approval_sequence = Column(Boolean, default=True, nullable=False)  # Si sigue la secuencia de aprobación
    
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
    

class AnswerHistory(Base):
    __tablename__ = 'answer_history'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)    
    # ID de la respuesta anterior (None si es la primera)
    previous_answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=True)
    
    # ID de la respuesta actual
    current_answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=False)
    
    # Información adicional
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class FormCloseConfig(Base):
    __tablename__ = 'form_close_configs'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    
    # Configuraciones de cierre (booleanos para cada acción)
    send_download_link = Column(Boolean, default=False, nullable=False)
    send_pdf_attachment = Column(Boolean, default=False, nullable=False)
    generate_report = Column(Boolean, default=False, nullable=False)
    do_nothing = Column(Boolean, default=True, nullable=False)  # Por defecto activado
    
    # Destinatarios para las acciones que los requieren
    download_link_recipient = Column(String(255), nullable=True)  # Para send_download_link
    email_recipient = Column(String(255), nullable=True)  # Para send_pdf_attachment
    report_recipient = Column(String(255), nullable=True)  # Para generate_report
    
    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class QuestionLocationRelation(Base):
    __tablename__ = 'question_location_relations'

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    form_id = Column(BigInteger, nullable=False) 
    origin_question_id = Column(BigInteger, nullable=False)  
    target_question_id = Column(BigInteger, nullable=False)  

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
