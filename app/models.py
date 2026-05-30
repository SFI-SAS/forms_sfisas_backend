from datetime import datetime
from sqlalchemy import (
    Boolean, Column, BigInteger, DateTime, Integer, String, Text, 
    ForeignKey, TIMESTAMP, Enum, UniqueConstraint, func, text
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum
import json
from sqlalchemy import TypeDecorator

# ====== DEFINIR EL TIPO AUTOJSON ======

class AutoJSON(TypeDecorator):
    """Tipo que convierte automáticamente dict → JSON string"""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError:
                return json.dumps(value, ensure_ascii=False)
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value

class CaseInsensitiveEnum(TypeDecorator):
    """Enum que normaliza valores a minúsculas antes de validar"""
    impl = String
    cache_ok = True

    def __init__(self, enum_class, *args, **kwargs):
        self.enum_class = enum_class
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            return value.value.lower()
        return str(value).lower()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # Convertir a minúsculas y buscar en el enum
        value_lower = str(value).lower()
        try:
            return self.enum_class(value_lower)
        except ValueError:
            # Si no existe, intentar buscar por nombre
            for member in self.enum_class:
                if member.value == value_lower or member.name == value_lower:
                    return member
            # Si aún no existe, retornar el valor por defecto o lanzar error
            return self.enum_class.text  # valor por defecto

# ====== ENUMS ======

class UserType(enum.Enum):
    admin = "admin"
    creator = "creator"
    user = "user"

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

class ResponseStatus(enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"

class EstadoEvento(enum.Enum):
    pendiente = "pendiente"
    finalizado = "finalizado"
    respondido = "respondido"

# ====== MODELOS ======

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
    recognition_id = Column(String(100), nullable=True, unique=True)  
    asign_bitacora = Column(Boolean, default=False, nullable=False)
    id_category = Column(BigInteger, ForeignKey('user_categories.id'), nullable=True)
    
    category = relationship("UserCategory", back_populates="users")
    form_moderators = relationship('FormModerators', back_populates='user')
    forms = relationship('Form', back_populates='user')
    responses = relationship('Response', back_populates='user')
    forms_movimientos = relationship(
        'FormMovimientos',
        back_populates='user',
    )
    form_templates = relationship("FormTemplate", back_populates="user")

class UserCategory(Base):
    __tablename__ = 'user_categories'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    users = relationship("User", back_populates="category")

class Form(Base):
    __tablename__ = 'forms'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    format_type = Column(Enum(FormatType), nullable=False, default=FormatType.abierto)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    # ✅ USA AutoJSON EN LUGAR DE JSON O TEXT
    form_design = Column(AutoJSON, nullable=True, default={})
    id_category = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    
    # ✅ NUEVOS CAMPOS
    instructivo_url = Column(Text, nullable=True)
    alert_message = Column(Text, nullable=True)  # Texto de alerta antes de llenar el formato

    # ═══════════════════════════════════════════════════════════════════════
    # ✅ NUEVO: Modo de aprobación
    # ───────────────────────────────────────────────────────────────────────
    #   'sequential' → jerárquico (como siempre). El aprobador #N solo puede
    #                  aprobar si los anteriores (sequence_number menor) ya
    #                  aprobaron. Un rechazo bloquea a los siguientes.
    #   'parallel'   → todos pueden aprobar/rechazar en cualquier orden.
    #                  El estado final sigue el mismo criterio: si alguien
    #                  rechaza el formato queda 'rechazado'; si TODOS los
    #                  obligatorios aprueban, queda 'aprobado'.
    # ═══════════════════════════════════════════════════════════════════════
    approval_mode = Column(String(20), nullable=False, default='sequential')

    # Hotfix QA runner 2026-05-30: el endpoint /projects/by-project/{id} usa
    # Form.project_id pero el modelo no la declaraba (causaba AttributeError).
    project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=True, index=True)

    user = relationship('User', back_populates='forms')
    form_moderators = relationship("FormModerators", back_populates="form", cascade="all, delete-orphan")
    questions = relationship("Question", secondary="form_questions", back_populates="forms")
    responses = relationship('Response', back_populates='form')
    form_answers = relationship('FormAnswer', back_populates='form')
    category = relationship("FormCategory", back_populates="forms")

class FormCategory(Base):
    __tablename__ = 'form_categories'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    parent_id = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
    order = Column(Integer, default=0)
    is_expanded = Column(Boolean, default=True)
    icon = Column(String(50), nullable=True)
    color = Column(String(20), nullable=True)
    # Modo de aprobación heredado a los formatos de esta categoría:
    #   'sequential' | 'parallel'. Se sobreescribe Form.approval_mode al
    #   sincronizar aprobadores categoría → formato.
    approval_mode = Column(
        String(20), nullable=False, default='sequential', server_default='sequential'
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now())

    forms = relationship("Form", back_populates="category")
    parent = relationship("FormCategory", remote_side=[id], back_populates="children")
    children = relationship("FormCategory", back_populates="parent", cascade="all, delete-orphan", order_by="FormCategory.order")
    forms_movimientos = relationship(
            "FormMovimientos",
            back_populates="category"
        )
    approvals = relationship("CategoryApproval", back_populates="category", cascade="all, delete-orphan")
    
class Question(Base):
    __tablename__ = 'questions'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    question_type = Column(CaseInsensitiveEnum(QuestionType), default=QuestionType.text, nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    root = Column(Boolean, nullable=False, default=False)
    id_category = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)
    id_alias = Column(Integer, ForeignKey("alias.id"), nullable=True, index=True)
    
    category = relationship('QuestionCategory', back_populates='questions')
    forms = relationship('Form', secondary='form_questions', back_populates='questions')
    options = relationship('Option', back_populates='question')
    answers = relationship('Answer', back_populates='question')
    form_answers = relationship('FormAnswer', back_populates='question')
    alias = relationship('Alias', backref='questions')

class QuestionCategory(Base):
    __tablename__ = 'question_categories'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    parent_id = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)
    parent = relationship('QuestionCategory', remote_side=[id], backref='subcategories')
    questions = relationship('Question', back_populates='category')

class FormQuestion(Base):
    __tablename__ = 'form_questions'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'))
    question_id = Column(BigInteger, ForeignKey('questions.id'))

class Option(Base):
    __tablename__ = 'options'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    option_text = Column(String(255), nullable=False)
    question = relationship('Question', back_populates='options')

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
    sync_pendiente = Column(Boolean, default=False, nullable=False)
    form = relationship('Form', back_populates='responses')
    user = relationship('User', back_populates='responses')
    answers = relationship('Answer', back_populates='response')
    approvals = relationship("ResponseApproval", back_populates="response")
    question_rules = relationship(
        "RelationQuestionRule",
        foreign_keys="RelationQuestionRule.id_response",
        back_populates="related_response",
        cascade="all, delete-orphan"    
    )


class Answer(Base):
    __tablename__ = 'answers'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    answer_text = Column(String(255), nullable=True)
    file_path = Column(Text, nullable=True)
    form_design_element_id = Column(String(100), nullable=True)
    
    response = relationship('Response', back_populates='answers')
    question = relationship('Question', back_populates='answers')
    file_serial = relationship('AnswerFileSerial', back_populates='answer', uselist=False, cascade='all, delete-orphan')

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
    frequency_type = Column(String(50), nullable=False)
    repeat_days = Column(String(255), nullable=True)
    interval_days = Column(Integer, nullable=True)
    specific_date = Column(DateTime, nullable=True)
    status = Column(Boolean, default=True, nullable=False)

class FormModerators(Base):
    __tablename__ = 'form_moderators'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id', ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    form = relationship('Form', back_populates='form_moderators')
    user = relationship('User', back_populates='form_moderators')

class FormAnswer(Base):
    __tablename__ = 'form_answers'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
    is_repeated = Column(Boolean, default=False, nullable=False)
    form = relationship('Form', back_populates='form_answers')
    question = relationship('Question', back_populates='form_answers')

class QuestionTableRelation(Base):
    __tablename__ = 'question_table_relations'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False, unique=True)
    related_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=True)
    related_form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=True)
    name_table = Column(String(255), nullable=False)
    field_name = Column(String(255), nullable=True)
    question = relationship('Question', foreign_keys=[question_id], backref='table_relation', uselist=False)
    related_question = relationship('Question', foreign_keys=[related_question_id], backref='related_table_relations', uselist=False)
    related_form = relationship('Form', foreign_keys=[related_form_id], backref='related_form_serial', uselist=False)

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
    # Método de firma del aprobador. Valores permitidos (CHECK en BD):
    #   'button'           → solo botón (clásico)
    #   'button_or_facial' → botón o firma facial (aprobador elige)
    #   'facial'           → solo firma facial (obligatoria)
    firm_mode = Column(
        String(20), nullable=False, default='button', server_default='button'
    )
    # Pregunta regisfacial fuente: contra qué pregunta de registro facial se
    # valida al aprobador. Obligatoria cuando firm_mode != 'button' (CHECK en BD).
    firm_source_question_id = Column(
        BigInteger, ForeignKey('questions.id', ondelete='SET NULL'), nullable=True
    )
    form = relationship("Form", backref="approval_template")
    user = relationship("User", backref="forms_to_approve")
    firm_source_question = relationship("Question", foreign_keys=[firm_source_question_id])

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
    # ✅ USA AutoJSON
    attachment_files = Column(AutoJSON, nullable=True, default=None)
    # Heredado de FormApproval.firm_mode al clonar al enviar respuesta.
    # Fija el método con el que el aprobador debe actuar para esta respuesta:
    #   'button' | 'button_or_facial' | 'facial'
    firm_mode = Column(
        String(20), nullable=False, default='button', server_default='button'
    )
    # Evidencia: cuando el aprobador firma facialmente, aquí queda el id del
    # Answer regisfacial usado para validar (auditoría). NULL si aún no
    # aprobó facialmente o si firm_mode='button'.
    firm_answer_id = Column(
        BigInteger, ForeignKey('answers.id', ondelete='SET NULL'), nullable=True
    )
    # Pregunta regisfacial fuente heredada de FormApproval al clonar.
    firm_source_question_id = Column(
        BigInteger, ForeignKey('questions.id', ondelete='SET NULL'), nullable=True
    )
    response = relationship("Response", back_populates="approvals")
    user = relationship("User")
    firm_answer = relationship("Answer", foreign_keys=[firm_answer_id])
    firm_source_question = relationship("Question", foreign_keys=[firm_source_question_id])

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

class AnswerHistory(Base):
    __tablename__ = 'answer_history'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)
    previous_answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=True)
    current_answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

class FormCloseConfig(Base):
    __tablename__ = 'form_close_configs'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    send_download_link = Column(Boolean, default=False, nullable=False)
    send_pdf_attachment = Column(Boolean, default=False, nullable=False)
    generate_report = Column(Boolean, default=False, nullable=False)
    do_nothing = Column(Boolean, default=True, nullable=False)
    send_custom_template = Column(Boolean, default=False, nullable=False)
    custom_template_include_pdf = Column(Boolean, default=False, nullable=False)
    download_link_recipients = Column(AutoJSON, nullable=True, default=None)
    email_recipients = Column(AutoJSON, nullable=True, default=None)
    report_recipients = Column(AutoJSON, nullable=True, default=None)
    custom_template_recipients = Column(AutoJSON, nullable=True, default=None)
    custom_template_id = Column(BigInteger, ForeignKey('download_templates.id'), nullable=True)
    custom_email_subject = Column(String(255), nullable=True)
    custom_email_body = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
class QuestionLocationRelation(Base):
    __tablename__ = 'question_location_relations'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, nullable=False)
    origin_question_id = Column(BigInteger, nullable=False)
    target_question_id = Column(BigInteger, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

class ApprovalRequirement(Base):
    __tablename__ = "approval_requirements"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey("forms.id"), nullable=False)
    approver_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    required_form_id = Column(BigInteger, ForeignKey("forms.id"), nullable=False)
    linea_aprobacion = Column(Boolean, default=True, nullable=False)
    form = relationship("Form", foreign_keys=[form_id], backref="approval_requirements")
    approver = relationship("User", backref="approval_requirements")
    required_form = relationship("Form", foreign_keys=[required_form_id])

class ResponseApprovalRequirement(Base):
    __tablename__ = "response_approval_requirements"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey("responses.id"), nullable=False)
    approval_requirement_id = Column(BigInteger, ForeignKey("approval_requirements.id"), nullable=False)
    fulfilling_response_id = Column(BigInteger, ForeignKey("responses.id"), nullable=True)
    is_fulfilled = Column(Boolean, default=False, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    response = relationship("Response", foreign_keys=[response_id], backref="approval_requirements_status")
    approval_requirement = relationship("ApprovalRequirement", backref="response_requirements")
    fulfilling_response = relationship("Response", foreign_keys=[fulfilling_response_id])

class RelationBitacora(Base):
    __tablename__ = "relation_bitacora"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_response = Column(BigInteger, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class QuestionAndAnswerBitacora(Base):
    __tablename__ = "question_and_answer_bitacora"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_relation_bitacora = Column(BigInteger, ForeignKey("relation_bitacora.id"), nullable=False)
    name_format = Column(String(255), nullable=False)
    name_user = Column(String(255), nullable=False)
    question = Column(String(255), nullable=False)
    answer = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class BitacoraLogsSimple(Base):
    __tablename__ = "bitacora_logs_simple"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    clasificacion = Column(String(100), nullable=False)
    titulo = Column(String(255), nullable=False)
    fecha = Column(String(20), nullable=False)
    hora = Column(String(10), nullable=False)
    ubicacion = Column(String(255), nullable=True)
    participantes = Column(Text, nullable=True)
    descripcion = Column(Text, nullable=True)
    # ✅ USA AutoJSON para archivos
    archivos = Column(AutoJSON, nullable=True, default=None)
    registrado_por = Column(String(255), nullable=False)
    estado = Column(Enum(EstadoEvento), default=EstadoEvento.pendiente, nullable=False)
    atendido_por = Column(String(255), nullable=True)
    evento_responde_id = Column(BigInteger, ForeignKey("bitacora_logs_simple.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    respuestas = relationship("BitacoraLogsSimple", backref="evento_padre", remote_side=[id])

class PalabrasClave(Base):
    __tablename__ = "form_palabras_clave"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, nullable=False)
    keywords = Column(String(500), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class ClasificacionBitacoraRelacion(Base):
    __tablename__ = "clasificacion_bitacora_relacion"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, nullable=False)
    question_id = Column(BigInteger, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    
class RelationOperationMath(Base):
    __tablename__ = "relation_operation_math"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_form = Column(BigInteger, ForeignKey("forms.id"), nullable=False)
    id_questions = Column(AutoJSON, nullable=False)  # Almacena lista de IDs de preguntas
    operations = Column(String(500), nullable=False)  # Fórmula u operación matemática
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    form = relationship("Form", backref="math_operations")
    
    
    

# Agregar al archivo models.py

class DownloadTemplate(Base):
    __tablename__ = "download_templates"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Configuración guardada como JSON
    form_ids = Column(AutoJSON, nullable=False)  # Lista de IDs de formularios
    selected_fields = Column(AutoJSON, nullable=False)  # Lista de IDs de campos
    conditions = Column(AutoJSON, nullable=True, default=[])  # Condiciones de filtro
    date_filter = Column(AutoJSON, nullable=True, default={})  # Filtro de fechas
    preferred_format = Column(String(20), nullable=False, default='excel')  # excel, csv, pdf, word
    
    # Metadata
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relación con usuario
    user = relationship("User", backref="download_templates")
    
class Alias(Base):
    __tablename__ = "alias"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Alias(id={self.id}, name={self.name})>"

class FormMovimientos(Base):
    __tablename__ = 'forms_movimientos'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    form_ids = Column(AutoJSON, nullable=False)  # Lista de IDs de formularios  
    question_ids = Column(AutoJSON, nullable=False)  # Lista de IDs de preguntas
    title = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    # ✅ USA AutoJSON EN LUGAR DE JSON O TEXT
    id_category = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    
    user = relationship('User', back_populates='forms_movimientos')
    category = relationship("FormCategory", back_populates="forms_movimientos")            

class RelationQuestionRule(Base):
    __tablename__ = "relation_question_rule"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_form = Column(BigInteger, ForeignKey("forms.id"), nullable=False)
    id_question = Column(BigInteger, ForeignKey("questions.id"), nullable=False)
    id_response = Column(BigInteger, ForeignKey("responses.id"), nullable=True)
    date_notification = Column(DateTime(timezone=True))# Tipo de regla
    time_alert = Column(String(100), nullable=True)  # Hora para alerta o notificación
    enabled = Column(Boolean, default=True, nullable=False)

    # ═══════════════════════════════════════════════════════════════════
    # ✅ NUEVOS CAMPOS — soporte para email_notification combinado con date_notification
    # Cuando `notification_email` tiene valor, el scheduler enviará el recordatorio
    # a ese email en vez de al usuario que diligenció el response.
    # Cuando está en NULL (reglas viejas de campos date_notification),
    # el comportamiento sigue siendo idéntico al de antes: se usa user.email del response.
    # ═══════════════════════════════════════════════════════════════════
    notification_email = Column(String(255), nullable=True)   # Email destinatario custom (campos email_notification)
    notification_message = Column(Text, nullable=True)        # Mensaje personalizado opcional

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    question = relationship('Question', foreign_keys=[id_question], backref='related_question_rule', uselist=False)
    related_form = relationship('Form', foreign_keys=[id_form], backref='related_form_rule', uselist=False)
    related_response = relationship(
        "Response",
        foreign_keys=[id_response],
        back_populates="question_rules"
    )

class TemplateScope(str, enum.Enum):
    private = "private"
    company = "company"
    public = "public"


class FormTemplate(Base):
    __tablename__ = 'form_templates'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    id_category = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
    tags = Column(AutoJSON, nullable=True, default=[])
    thumbnail_url = Column(Text, nullable=True)
    template_design = Column(AutoJSON, nullable=False, default=[])
    scope = Column(Enum(TemplateScope), nullable=False, default=TemplateScope.private)
    usage_count = Column(BigInteger, nullable=False, default=0)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship('User', back_populates='form_templates')
    category = relationship('FormCategory')


class CategoryApproval(Base):
    __tablename__ = 'category_approvals'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    category_id = Column(BigInteger, ForeignKey('form_categories.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    sequence_number = Column(Integer, nullable=False, default=1)
    is_mandatory = Column(Boolean, nullable=False, default=True)
    deadline_days = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Método de firma del aprobador (heredado al FormApproval cuando el formato
    # toma sus aprobadores de la categoría):
    #   'button' | 'button_or_facial' | 'facial'
    firm_mode = Column(
        String(20), nullable=False, default='button', server_default='button'
    )
    # Pregunta regisfacial fuente. Obligatoria cuando firm_mode != 'button'.
    firm_source_question_id = Column(
        BigInteger, ForeignKey('questions.id', ondelete='SET NULL'), nullable=True
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('category_id', 'user_id', name='uq_category_user'),
    )

    # Relationships
    category = relationship('FormCategory', back_populates='approvals')
    user = relationship('User')
    firm_source_question = relationship('Question', foreign_keys=[firm_source_question_id])


class ConsultantScope(str, enum.Enum):
    form = "form"
    user = "user"
    form_user = "form_user"
    category = "category"


class ConsultantAssignment(Base):
    __tablename__ = 'consultant_assignments'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    consultant_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    scope = Column(Enum(ConsultantScope), nullable=False)
    form_id = Column(BigInteger, ForeignKey('forms.id', ondelete='CASCADE'), nullable=True)
    target_user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    category_id = Column(BigInteger, ForeignKey('form_categories.id', ondelete='CASCADE'), nullable=True)
    created_by = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    consultant = relationship('User', foreign_keys=[consultant_id])
    target_user = relationship('User', foreign_keys=[target_user_id])
    creator = relationship('User', foreign_keys=[created_by])
    form = relationship('Form', foreign_keys=[form_id])
    category = relationship('FormCategory', foreign_keys=[category_id])


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILES — agrupan usuarios y formatos para que los miembros puedan
# diligenciar los formatos asignados al perfil.
# Solo administradores gestionan estas tablas.
# ═══════════════════════════════════════════════════════════════════════════════

class Profile(Base):
    __tablename__ = 'profiles'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_by = Column(BigInteger, ForeignKey('users.id'), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    creator = relationship('User', foreign_keys=[created_by])
    user_links = relationship('ProfileUser', back_populates='profile', cascade='all, delete-orphan')
    form_links = relationship('ProfileForm', back_populates='profile', cascade='all, delete-orphan')
    category_links = relationship('ProfileCategory', back_populates='profile', cascade='all, delete-orphan')


class ProfileUser(Base):
    __tablename__ = 'profile_users'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('profile_id', 'user_id', name='uq_profile_user'),
    )

    profile = relationship('Profile', back_populates='user_links')
    user = relationship('User')


class ProfileForm(Base):
    __tablename__ = 'profile_forms'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False, index=True)
    form_id = Column(BigInteger, ForeignKey('forms.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('profile_id', 'form_id', name='uq_profile_form'),
    )

    profile = relationship('Profile', back_populates='form_links')
    form = relationship('Form')


class ProfileCategory(Base):
    __tablename__ = 'profile_categories'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False, index=True)
    category_id = Column(BigInteger, ForeignKey('form_categories.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('profile_id', 'category_id', name='uq_profile_category'),
    )

    profile = relationship('Profile', back_populates='category_links')
    category = relationship('FormCategory')


# ============================================================================
# Integraciones: tabla que define qué formatos puede integrar cada usuario
# vía el endpoint POST /integrations/answers.
# ============================================================================
class IntegratorFormatAccess(Base):
    __tablename__ = 'integrator_format_access'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    format_id = Column(BigInteger, ForeignKey('forms.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_by = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'format_id', name='uq_integrator_format'),
    )

    user = relationship('User', foreign_keys=[user_id], backref='integrator_format_accesses')
    assigner = relationship('User', foreign_keys=[assigned_by])
    form = relationship('Form')


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVIDADES GENÉRICAS — agrupan formatos y, por cada formato, definen quién lo
# diligencia. El diligenciador se elige a través de un PERFIL (Profile): se elige
# un perfil, se listan sus usuarios y se escoge uno. Un mismo formato puede tener
# varios diligenciadores dentro de la actividad (varias filas form↔usuario).
# Esta capa solo guarda configuración; reutiliza /profiles para leer perfiles.
# Solo administradores gestionan estas tablas.
# ═══════════════════════════════════════════════════════════════════════════════

class GenericActivity(Base):
    __tablename__ = 'generic_activities'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_by = Column(BigInteger, ForeignKey('users.id'), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    creator = relationship('User', foreign_keys=[created_by])
    form_links = relationship('GenericActivityForm', back_populates='activity', cascade='all, delete-orphan')


class GenericActivityForm(Base):
    """Una fila = en la actividad, el formato F lo diligencia el usuario U,
    elegido a través del perfil P. Varios diligenciadores por formato => varias
    filas con el mismo (activity_id, form_id) y distinto user_id.
    profile_id es SET NULL: si el perfil se elimina, la asignación conserva al
    usuario pero pierde la referencia al perfil de origen."""
    __tablename__ = 'generic_activity_forms'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    activity_id = Column(BigInteger, ForeignKey('generic_activities.id', ondelete='CASCADE'), nullable=False, index=True)
    form_id = Column(BigInteger, ForeignKey('forms.id', ondelete='CASCADE'), nullable=False, index=True)
    profile_id = Column(BigInteger, ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('activity_id', 'form_id', 'user_id', name='uq_generic_activity_form_user'),
    )

    activity = relationship('GenericActivity', back_populates='form_links')
    form = relationship('Form')
    profile = relationship('Profile')
    user = relationship('User', foreign_keys=[user_id])