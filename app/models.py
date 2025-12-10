# from sqlalchemy import (
#     JSON, Boolean, Column, BigInteger, DateTime, Integer, LargeBinary, String, Text, ForeignKey, TIMESTAMP, Enum, func, text
# )
# from sqlalchemy.orm import relationship
# from app.database import Base
# import enum
# from sqlalchemy import event

# from pytz import timezone
# BOGOTA_TZ = timezone('America/Bogota')

# class UserType(enum.Enum):
#     admin = "admin"
#     creator = "creator"
#     user = "user"

# # Definir ENUM para form_status

# class QuestionType(str, enum.Enum):
#     text = "text"
#     multiple_choice = "multiple_choice"
#     one_choice = "one_choice"
#     file = "file"
#     table = "table"
#     date = "date"
#     number = "number"
#     time = "time"
#     location = "location"
#     firm = "firm"
#     regisfacial = "regisfacial"
    
# class ApprovalStatus(enum.Enum):
#     pendiente = "pendiente"
#     aprobado = "aprobado"
#     rechazado = "rechazado"

# class FormatType(enum.Enum):
#     abierto = "abierto"
#     cerrado = "cerrado"
#     semi_abierto = "semi_abierto"


# class Models(Base):
#     __abstract__ = True

# # Modelo Users
# class User(Base):
#     __tablename__ = 'users'
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     num_document = Column(String(50), nullable=False)
#     name = Column(String(255), nullable=False)
#     email = Column(String(255), unique=True, nullable=False)
#     telephone = Column(String(20), nullable=False)
#     user_type = Column(Enum(UserType), default=UserType.user, nullable=False)
#     nickname = Column(String(100), nullable=True)
#     password = Column(Text, nullable=False)
#     recognition_id = Column(String(100), nullable=True, unique=True)  
#     asign_bitacora = Column(Boolean, default=False, nullable=False)
    
#     id_category  = Column(BigInteger, ForeignKey('user_categories.id'), nullable=True)
#     category = relationship("UserCategory", back_populates="users")
    
#     # Relaciones existentes
#     form_moderators = relationship('FormModerators', back_populates='user')
#     forms = relationship('Form', back_populates='user')
#     responses = relationship('Response', back_populates='user')

# class UserCategory(Base):
#     __tablename__ = 'user_categories'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     name = Column(String(100), nullable=False, unique=True)

#     users = relationship("User", back_populates="category")

# # Modelo Forms
# class Form(Base):
#     __tablename__ = 'forms'
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
#     title = Column(String(255), nullable=False)
#     description = Column(String(255), nullable=True)
#     format_type = Column(Enum(FormatType), nullable=False, default=FormatType.abierto)
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     form_design = Column(JSON, nullable=True, default=dict)
    
#     # Nuevo campo para categoría
#     id_category = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
#     is_enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    
#     # Relaciones existentes
#     user = relationship('User', back_populates='forms')
#     form_moderators = relationship("FormModerators", back_populates="form", cascade="all, delete-orphan")
#     questions = relationship("Question", secondary="form_questions", back_populates="forms")
#     responses = relationship('Response', back_populates='form')
#     form_answers = relationship('FormAnswer', back_populates='form')
    
#     # Nueva relación con categoría
#     category = relationship("FormCategory", back_populates="forms")


# # Modelo actualizado para soportar jerarquías
# class FormCategory(Base):
#     __tablename__ = 'form_categories'
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     name = Column(String(100), nullable=False)
#     description = Column(String(255), nullable=True)
    
#     # Campo clave para la jerarquía
#     parent_id = Column(BigInteger, ForeignKey('form_categories.id'), nullable=True)
    
#     # Campos adicionales útiles
#     order = Column(Integer, default=0)  # Para ordenar carpetas al mismo nivel
#     is_expanded = Column(Boolean, default=True)  # Estado UI por defecto
#     icon = Column(String(50), nullable=True)  # Icono opcional
#     color = Column(String(20), nullable=True)  # Color opcional
    
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
#     updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now())
    
#     # Relaciones
#     # Relación con formularios
#     forms = relationship("Form", back_populates="category")
    
#     # Auto-referencia para jerarquía
#     parent = relationship(
#         "FormCategory",
#         remote_side=[id],
#         back_populates="children"
#     )
#     children = relationship(
#         "FormCategory",
#         back_populates="parent",
#         cascade="all, delete-orphan",
#         order_by="FormCategory.order"
#     )


# class Question(Base):
#     __tablename__ = 'questions'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     question_text = Column(String(255), nullable=False)
#     question_type = Column(Enum(QuestionType), server_default=QuestionType.text.name, nullable=False)
#     required = Column(Boolean, nullable=False, server_default=text("1"))
#     root = Column(Boolean, nullable=False, server_default=text("0"))

#     id_category = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)

#     # Relaciones
#     category = relationship('QuestionCategory', back_populates='questions')
#     forms = relationship('Form', secondary='form_questions', back_populates='questions')
#     options = relationship('Option', back_populates='question')
#     answers = relationship('Answer', back_populates='question')
#     form_answers = relationship('FormAnswer', back_populates='question')
# # Tabla intermedia para la relación muchos a muchos entre Form y Question

# class QuestionCategory(Base):
#     __tablename__ = 'question_categories'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     name = Column(String(100), nullable=False, unique=True)

#     # Campo que permite jerarquía (categoría padre)
#     parent_id = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)

#     # Relación con su categoría padre
#     parent = relationship('QuestionCategory', remote_side=[id], backref='subcategories')

#     # Relación con preguntas
#     questions = relationship('Question', back_populates='category')

    
# class FormQuestion(Base):
#     __tablename__ = 'form_questions'
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'))
#     question_id = Column(BigInteger, ForeignKey('questions.id'))
    

# # Modelo Options
# class Option(Base):
#     __tablename__ = 'options'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
#     option_text = Column(String(255), nullable=False)

#     question = relationship('Question', back_populates='options')

# # Modelo Responses

# class ResponseStatus(enum.Enum):
#     draft = "draft"                    # Guardado pero no enviado para aprobación
#     submitted = "submitted"            # Enviado para aprobación
#     approved = "approved"              # Aprobado completamente
#     rejected = "rejected"  
    
# class Response(Base):
#     __tablename__ = 'responses'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
#     user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
#     mode = Column(String(20), nullable=False) 
#     mode_sequence = Column(Integer, nullable=False)  
#     repeated_id = Column(String(80), nullable=True)
#     submitted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    
#     status = Column(Enum(ResponseStatus), default=ResponseStatus.draft, nullable=False)


#     form = relationship('Form', back_populates='responses')
#     user = relationship('User', back_populates='responses')
#     answers = relationship('Answer', back_populates='response')
#     approvals = relationship("ResponseApproval", back_populates="response")

# # Modelo Answers
# class Answer(Base):
#     __tablename__ = 'answers'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)
#     question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
#     answer_text = Column(String(255), nullable=True)
#     file_path = Column(Text, nullable=True)
    
#     # ✅ NUEVO CAMPO: UUID del elemento en form_design
#     form_design_element_id = Column(String(100), nullable=True)
#     # Este campo guarda el UUID del elemento específico en form_design
#     # Permite identificar múltiples instancias de la misma pregunta

#     response = relationship('Response', back_populates='answers')
#     question = relationship('Question', back_populates='answers')
#     file_serial = relationship('AnswerFileSerial', back_populates='answer', uselist=False, cascade='all, delete-orphan')
# # Modelo Project
# class Project(Base):
#     __tablename__ = 'projects'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     name = Column(String(255), nullable=False)
#     description = Column(Text, nullable=True)
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


# class FormSchedule(Base):
#     __tablename__ = 'form_schedules'


#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
#     user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
#     frequency_type = Column(String(50), nullable=False)  # "daily", "weekly", "monthly", "periodic", "specific_date"
#     repeat_days = Column(String(255), nullable=True)  # Para "weekly" -> ejemplo: "monday,wednesday,friday"
#     interval_days = Column(Integer, nullable=True)  # Para "periodic" -> cada X días (por ejemplo cada 3 días)
#     specific_date = Column(DateTime, nullable=True)  # Para "specific_date" -> fecha exacta
#     status = Column(Boolean, default=True, nullable=False)


# class FormModerators(Base):
#     __tablename__ = 'form_moderators'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id', ondelete="CASCADE"), nullable=False)
#     user_id = Column(BigInteger, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
#     assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

#     # Relaciones
#     form = relationship('Form', back_populates='form_moderators')
#     user = relationship('User', back_populates='form_moderators')
    
    

# class FormAnswer(Base):
#     __tablename__ = 'form_answers'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
#     question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
#     is_repeated = Column(Boolean, default=False, nullable=False)

#     # Relaciones
#     form = relationship('Form', back_populates='form_answers')
#     question = relationship('Question', back_populates='form_answers')


# class QuestionTableRelation(Base):
#     __tablename__ = 'question_table_relations'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False, unique=True)
#     related_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=True)
#     name_table = Column(String(255), nullable=False)
#     field_name = Column(String(255), nullable=True)

#     question = relationship('Question', foreign_keys=[question_id], backref='table_relation', uselist=False)

#     related_question = relationship('Question', foreign_keys=[related_question_id], backref='related_table_relations', uselist=False)
    
    

# class AnswerFileSerial(Base):
#     __tablename__ = 'answer_file_serials'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     serial = Column(String(100), nullable=False)
#     answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=False)

#     answer = relationship('Answer', back_populates='file_serial')




# class FormApproval(Base):
#     __tablename__ = 'form_approvals'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
#     user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
#     sequence_number = Column(Integer, nullable=False, default=1)
#     is_mandatory = Column(Boolean, default=True)
#     deadline_days = Column(Integer, nullable=True)
#     is_active = Column(Boolean, default=True, nullable=False)
    
#     form = relationship("Form", backref="approval_template")
#     user = relationship("User", backref="forms_to_approve")


# class ResponseApproval(Base):
#     __tablename__ = 'response_approvals'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)
#     user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
#     sequence_number = Column(Integer, nullable=False)
#     is_mandatory = Column(Boolean, default=True)
#     status = Column(Enum(ApprovalStatus), default=ApprovalStatus.pendiente, nullable=False)
    
#     reviewed_at = Column(DateTime(timezone=True), nullable=True)
#     message = Column(Text, nullable=True)
#     reconsideration_requested = Column(Boolean, nullable=True, default=False)
#     attachment_files = Column(JSON, nullable=True, default=None)
#     response = relationship("Response", back_populates="approvals")
#     user = relationship("User")


# class FormApprovalNotification(Base):
#     __tablename__ = 'form_approval_notifications'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
#     user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
#     notify_on = Column(Enum("cada_aprobacion", "aprobacion_final", name="notify_type"), nullable=False)

#     form = relationship("Form", backref="notification_rules")
#     user = relationship("User")


# class EmailConfig(Base):
#     __tablename__ = "email_config"

#     id = Column(Integer, primary_key=True, index=True)
#     email_address = Column(String(255), nullable=False)  
#     is_active = Column(Boolean, default=True)
    
    
# class QuestionFilterCondition(Base):
#     __tablename__ = "question_filter_conditions"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
#     filtered_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
#     source_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
#     condition_question_id = Column(BigInteger, ForeignKey('questions.id'), nullable=False)
#     expected_value = Column(String(255), nullable=False)
#     operator = Column(String(10), nullable=False, default="==")

#     form = relationship("Form")
#     filtered_question = relationship("Question", foreign_keys=[filtered_question_id])
#     source_question = relationship("Question", foreign_keys=[source_question_id])
#     condition_question = relationship("Question", foreign_keys=[condition_question_id])

    
# @event.listens_for(EmailConfig.__table__, "after_create")
# def insert_default_emails(target, connection, **kwargs):
#     """ Inserta dos registros de ejemplo al crear la tabla """
#     connection.execute(
#         target.insert(),
#         [
#             {"email_address": "example1@domain.com", "is_active": False},
#             {"email_address": "example2@domain.com", "is_active": False},
#         ],
#     )
    

# class AnswerHistory(Base):
#     __tablename__ = 'answer_history'
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     response_id = Column(BigInteger, ForeignKey('responses.id'), nullable=False)    
#     # ID de la respuesta anterior (None si es la primera)
#     previous_answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=True)
    
#     # ID de la respuesta actual
#     current_answer_id = Column(BigInteger, ForeignKey('answers.id'), nullable=False)
    
#     # Información adicional
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


# class FormCloseConfig(Base):
#     __tablename__ = 'form_close_configs'
    
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, ForeignKey('forms.id'), nullable=False)
    
#     # Configuraciones de cierre (booleanos para cada acción)
#     send_download_link = Column(Boolean, default=False, nullable=False)
#     send_pdf_attachment = Column(Boolean, default=False, nullable=False)
#     generate_report = Column(Boolean, default=False, nullable=False)
#     do_nothing = Column(Boolean, default=True, nullable=False)
    
#     # 🆕 CAMBIADO: Ahora almacenan JSON con listas de emails
#     download_link_recipients = Column(Text, nullable=True)  # JSON: ["email1", "email2"]
#     email_recipients = Column(Text, nullable=True)  # JSON: ["email1", "email2"]
#     report_recipients = Column(Text, nullable=True)  # JSON: ["email1", "email2"]
    
#     # Timestamps
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

# class QuestionLocationRelation(Base):
#     __tablename__ = 'question_location_relations'

#     id = Column(BigInteger, primary_key=True, autoincrement=True)

#     form_id = Column(BigInteger, nullable=False) 
#     origin_question_id = Column(BigInteger, nullable=False)  
#     target_question_id = Column(BigInteger, nullable=False)  

#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


# class ApprovalRequirement(Base):
#     __tablename__ = "approval_requirements"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)

#     # Formulario principal al que aplica el requisito
#     form_id = Column(BigInteger, ForeignKey("forms.id"), nullable=False)

#     # Usuario responsable de aprobar
#     approver_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)

#     # Formulario que debe estar diligenciado/aprobado como requisito
#     required_form_id = Column(BigInteger, ForeignKey("forms.id"), nullable=False)

#     # Indica si debe seguir una línea de aprobación (secuencia obligatoria)
#     linea_aprobacion = Column(Boolean, default=True, nullable=False)


#     # Relaciones
#     form = relationship("Form", foreign_keys=[form_id], backref="approval_requirements")
#     approver = relationship("User", backref="approval_requirements")
#     required_form = relationship("Form", foreign_keys=[required_form_id])



# class ResponseApprovalRequirement(Base):
#     """
#     Tabla que controla los requisitos de aprobación específicos para cada respuesta.
#     Permite tener múltiples respuestas del mismo usuario al mismo formulario,
#     cada una con su propio control de requisitos.
#     """
#     __tablename__ = "response_approval_requirements"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
    
#     # La respuesta específica que debe cumplir el requisito
#     response_id = Column(BigInteger, ForeignKey("responses.id"), nullable=False)
    
#     # El requisito base desde la configuración del formulario
#     approval_requirement_id = Column(BigInteger, ForeignKey("approval_requirements.id"), nullable=False)
    
#     # ID de la respuesta del formulario requerido que cumple este requisito
#     # (NULL significa que aún no se ha cumplido)
#     fulfilling_response_id = Column(BigInteger, ForeignKey("responses.id"), nullable=True)
    
#     # Estado del requisito para esta respuesta específica
#     is_fulfilled = Column(Boolean, default=False, nullable=False)
    
#     # Timestamps para auditoría
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
#     # Relaciones
#     response = relationship("Response", foreign_keys=[response_id], backref="approval_requirements_status")
#     approval_requirement = relationship("ApprovalRequirement", backref="response_requirements")
#     fulfilling_response = relationship("Response", foreign_keys=[fulfilling_response_id])



# class RelationBitacora(Base):
#     __tablename__ = "relation_bitacora"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     id_response = Column(BigInteger, nullable=False) 

#     # Timestamps para auditoría
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

# class QuestionAndAnswerBitacora(Base):
#     __tablename__ = "question_and_answer_bitacora"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     id_relation_bitacora = Column(BigInteger, ForeignKey("relation_bitacora.id"), nullable=False)
#     name_format = Column(String(255), nullable=False)
#     name_user = Column(String(255), nullable=False)
#     question = Column(String(255), nullable=False)
#     answer = Column(Text, nullable=True)

#     # Timestamps para auditoría
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
# class EstadoEvento(enum.Enum):
#     pendiente = "pendiente"
#     finalizado = "finalizado"
#     respondido = "respondido"

# class BitacoraLogsSimple(Base):
#     __tablename__ = "bitacora_logs_simple"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     clasificacion = Column(String(100), nullable=False)
#     titulo = Column(String(255), nullable=False)
#     fecha = Column(String(20), nullable=False)
#     hora = Column(String(10), nullable=False)
#     ubicacion = Column(String(255), nullable=True)
#     participantes = Column(Text, nullable=True)
#     descripcion = Column(Text, nullable=True)

#     # Nuevo campo
#     archivos = Column(Text, nullable=True)  # Guarda lista JSON de nombres o rutas
#     registrado_por = Column(String(255), nullable=False)  # Ejemplo: "Neider Torres - 1010234567"

#         # 👇 Nuevos campos
#     estado = Column(Enum(EstadoEvento), default=EstadoEvento.pendiente, nullable=False)
#     atendido_por = Column(String(255), nullable=True)
#     evento_responde_id = Column(BigInteger, ForeignKey("bitacora_logs_simple.id"), nullable=True)

#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

#     # Relación autorreferencial (evento que responde a otro)
#     respuestas = relationship(
#         "BitacoraLogsSimple",
#         backref="evento_padre",
#         remote_side=[id]
#     )


# class PalabrasClave(Base):
#     __tablename__ = "form_palabras_clave"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, nullable=False) 
#     keywords = Column(String(500), nullable=False)  # Cambié a plural y aumenté el tamaño

#     # Timestamps para auditoría
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# class ClasificacionBitacoraRelacion(Base):
#     __tablename__ = "clasificacion_bitacora_relacion"

#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     form_id = Column(BigInteger, nullable=False) 
#     question_id = Column(BigInteger, nullable=False) 

#     # Timestamps para auditoría
#     created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
#     updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)



# En tu archivo de modelos (models.py)

from sqlalchemy import (
    Boolean, Column, BigInteger, DateTime, Integer, LargeBinary, String, Text, 
    ForeignKey, TIMESTAMP, Enum, func, text
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
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now())
    
    forms = relationship("Form", back_populates="category")
    parent = relationship("FormCategory", remote_side=[id], back_populates="children")
    children = relationship("FormCategory", back_populates="parent", cascade="all, delete-orphan", order_by="FormCategory.order")

class Question(Base):
    __tablename__ = 'questions'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(String(255), nullable=False)
    question_type = Column(Enum(QuestionType), default=QuestionType.text, nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    root = Column(Boolean, nullable=False, default=False)
    id_category = Column(BigInteger, ForeignKey('question_categories.id'), nullable=True)
    
    category = relationship('QuestionCategory', back_populates='questions')
    forms = relationship('Form', secondary='form_questions', back_populates='questions')
    options = relationship('Option', back_populates='question')
    answers = relationship('Answer', back_populates='question')
    form_answers = relationship('FormAnswer', back_populates='question')

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
    
    form = relationship('Form', back_populates='responses')
    user = relationship('User', back_populates='responses')
    answers = relationship('Answer', back_populates='response')
    approvals = relationship("ResponseApproval", back_populates="response")

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
    # ✅ USA AutoJSON
    attachment_files = Column(AutoJSON, nullable=True, default=None)
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
    # ✅ USA AutoJSON para listas
    download_link_recipients = Column(AutoJSON, nullable=True, default=None)
    email_recipients = Column(AutoJSON, nullable=True, default=None)
    report_recipients = Column(AutoJSON, nullable=True, default=None)
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
    
    
    