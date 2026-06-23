import json
import logging
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, validator, model_validator
from typing import Any, Literal, Optional, List, Dict, Union
from datetime import datetime
from enum import Enum

from app.models import ApprovalStatus

logger = logging.getLogger(__name__)

class QuestionIdsRequest(BaseModel):
    """Modelo para actualizar las preguntas de un formulario"""
    question_ids: List[int] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "question_ids": [1, 2, 3, 4]
            }
        }
        
# Enum for UserType
class UserType(str, Enum):
    admin = "admin"
    creator = "creator"
    user = "user"

# Enum for FormStatus
class FormStatus(str, Enum):
    draft = 'draft'
    published = 'published'

# Schemas for User
class UserBase(BaseModel):
    name: str = Field(..., example="John Doe")
    email: EmailStr = Field(..., example="john@example.com")
    num_document: str = Field(..., example="10203040506")
    telephone: str = Field(..., example="3013033435")
    user_type: UserType = Field(default=UserType.user, example="user") 

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, example="securepassword")
    id_category: Optional[int] = Field(None, example=1)
    
class UserResponse(UserBase):
    id: int

    class Config:
        from_attributes = True


class UserTokenOut(BaseModel):
    """H-BW-004: Schema restringido para /validate-token — sin password hash ni recognition_id.
    Incluye num_document y telephone porque el endpoint es llamado por el perfil del
    propio usuario (Profile.tsx), que necesita esos campos para mostrarlos y editarlos.
    """
    id: int
    email: EmailStr
    name: str
    user_type: UserType
    num_document: Optional[str] = None
    telephone: Optional[str] = None

    class Config:
        from_attributes = True


class UserSelfUpdate(BaseModel):
    """Campos que un usuario puede actualizar de sí mismo (no privilegiados)."""
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None

class UserAdminUpdate(UserSelfUpdate):
    """Campos adicionales que solo admin/creator pueden modificar."""
    user_type: Optional[UserType] = None

UserUpdate = UserAdminUpdate
    
# Schemas for Option
class OptionCreate(BaseModel):
    question_id: int
    option_text: str

class OptionResponse(BaseModel):
    id: int
    question_id: int
    option_text: str

    class Config:
        from_attributes = True

# Schemas for Question
class QuestionBase(BaseModel):
    question_text: str = Field(..., example="What is your favorite color?")
    description: Optional[str] = None
    question_type: str = Field(..., example="multiple_choice")
    required: bool = Field(..., example=True)
    unique_answer: bool = Field(False, example=False)
    root:bool =  Field(..., example=True)
    id_category: Optional[int] = None


class QuestionBaseAll(BaseModel):
    question_text: str = Field(..., example="What is your favorite color?")
    description: Optional[str] = None
    question_type: str = Field(..., example="multiple_choice")
    required: bool = Field(..., example=True)
    unique_answer: bool = Field(False, example=False)
    root:bool =  Field(..., example=True)
    id_category: int | None = None
    
class QuestionCreate(QuestionBase):
    id_form: Optional[int] = None

class QuestionResponse(QuestionBaseAll):
    id: int
    id_form: Optional[int] = None

    class Config:
        from_attributes = True

class QuestionOptions(QuestionBase):
    id: int
    options: List[OptionResponse] = []
    
    class Config:
        from_attributes = True

class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    unique_answer: Optional[bool] = None
    id_form: Optional[int] = None

class GetFormBase(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    project_id: int
    created_at: datetime
    
    
class FormatTypeEnum(str, Enum):
    abierto = "abierto"
    cerrado = "cerrado"
    semi_abierto = "semi_abierto"

class FormBaseUser(BaseModel):
    title: str
    description: Optional[str] = None
    assign_user: List[int]
    format_type: str
    id_category: Optional[int] = None
    project_id: Optional[int] = None
    sync_approvers: Optional[bool] = True  # ← NUEVO

class FormBaseUserCreate(BaseModel):
   
    title: str = Field(..., example="Survey Form")
    description: Optional[str] = Field(None, example="This is a survey form description.")
    assign_user: List[int]
    mode: Literal["online", "offline"]  

    
class FormBase(BaseModel):
   
    title: str = Field(..., example="Survey Form")
    description: Optional[str] = Field(None, example="This is a survey form description.")

class FormCreate(FormBase):
    pass
class FormResponse(FormBase):
    id:int
    user_id: int
    created_at: datetime
    questions: List[QuestionOptions] = [] 
    
    class Config:
        from_attributes = True
        
class QuestionAdd(BaseModel):
    question_ids: List[int]

# Schemas for Response
class ResponseBase(BaseModel):
    submitted_at: Optional[datetime] = None

class ResponseCreate(ResponseBase):
    pass

class ResponseResponse(ResponseBase):
    id: int
    form_id: int
    user_id: int

    class Config:
        from_attributes = True

# Schemas for Answer
class AnswerBase(BaseModel):
    answer_text: Optional[str] = Field(None, example="Red")
    file_path: Optional[str] = Field(None, example="/uploads/answer123.png")

class AnswerCreate(AnswerBase):
    pass

class AnswerResponse(AnswerBase):
    id: int
    response_id: int
    question_id: int

    class Config:
        from_attributes = True
        
class Token(BaseModel):
    access_token: str
    token_type: str
    
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    
class ProjectResponse(ProjectCreate):
    id: int
    created_at: datetime
    
class PostCreate(BaseModel):
    response_id: int
    question_id: Union[int, str]  
    answer_text: str | None = None
    file_path: str | None = None
    form_design_element_id: Optional[str] = None 

    
class FormScheduleCreate(BaseModel):
    form_id: int
    user_id: int
    frequency_type: str  
    repeat_days: Optional[list[str]] = None 
    interval_days: Optional[int] = None      
    specific_date: Optional[datetime] = None 
    status: bool = True
    
class FormScheduleOut(BaseModel):
    id: int
    form_id: int
    user_id: int
    frequency_type: str
    repeat_days: Optional[str] = None
    interval_days: Optional[int] = None
    specific_date: Optional[datetime] = None
    status: bool

class FormSchema(BaseModel):
    id: int
    user_id: int
    title: str
    description: Optional[str]
    
    created_at: datetime
    
class AnswerSchema(BaseModel):
    id: int
    response_id: int
    question_id: int
    answer_text: Optional[str]
    file_path: Optional[str]

class UserUpdateInfo(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1)
    num_document: str = Field(..., min_length=3)
    telephone: str = Field(..., min_length=7)


class QuestionTableRelationCreate(BaseModel):
    question_id: int
    name_table: str
    related_question_id: Optional[int] = None
    related_form_id: Optional[int] = None
    field_name: Optional[str] = None 
    
    
class UserBaseCreate(BaseModel):
    num_document: str
    name: str
    email: EmailStr
    telephone: str
    id_category: Optional[int] = None 
    
class UpdateAnswerText(BaseModel):
    id: int
    answer_text: str
    

class UpdateAnswertHistory(BaseModel):
    id_answer: int
    answer_text: str


class FormAnswerCreate(BaseModel):
    form_id: int
    question_id: int
    is_repeated: bool = False
    
class FileSerialCreate(BaseModel):
    answer_id: int
    serial: str
    
    
class ApproverCreate(BaseModel):
    user_id: int
    sequence_number: int = 1
    is_mandatory: bool = True
    deadline_days: Optional[int] = None

class FormApprovalCreateRequest(BaseModel):
    form_id: int
    approvers: List[ApproverCreate]
    
class QuestionSchema(BaseModel):
    id: int
    question_text: str
    question_type: str
    required: bool
    root: bool



class AnswerSchema(BaseModel):
    id: int
    question_id: int
    answer_text: Optional[str]
    file_path: Optional[str]
    question: QuestionSchema  # ← Aquí se incluye la pregunta



class UserSchema(BaseModel):
    id: int
    name: str
    email: str



class ResponseSchema(BaseModel):
    id: int
    user: UserSchema
    answers: list[AnswerSchema]



class FormApprovalSchema(BaseModel):
    id: int
    user: UserSchema
    sequence_number: int
    is_mandatory: bool
    deadline_days: Optional[int]
    status: str
    reviewed_at: Optional[datetime]
    message: Optional[str]



class FormWithResponsesSchema(BaseModel):
    id: int
    title: str
    description: Optional[str]
    responses: list[ResponseSchema]
    approvals: list[FormApprovalSchema]

class FormatType(str, Enum):
    abierto = "abierto"
    cerrado = "cerrado"

class FormatTypeEdit(str, Enum):
    abierto = "abierto"
    cerrado = "cerrado"
    semi_abierto = "semi_abierto"  # ← Guión bajo
    
class ApproverSchema(BaseModel):
    user_id: int
    sequence_number: int = Field(default=1)
    is_mandatory: bool = Field(default=True)
    deadline_days: Optional[int] = None
    is_active: Optional[bool] = Field(default=True)
    # Método de firma del aprobador:
    #   'button'           → solo botón (clásico)
    #   'button_or_facial' → botón o firma facial (aprobador elige)
    #   'facial'           → solo firma facial (obligatoria)
    firm_mode: Literal["button", "button_or_facial", "facial"] = Field(default="button")
    # Pregunta regisfacial fuente de los registros para validar al aprobador.
    # Obligatoria cuando firm_mode != 'button' (validado en model_validator).
    firm_source_question_id: Optional[int] = None

    @model_validator(mode="after")
    def _validate_firm_source(self) -> "ApproverSchema":
        if self.firm_mode != "button" and self.firm_source_question_id is None:
            raise ValueError(
                "firm_source_question_id es obligatorio cuando firm_mode != 'button'"
            )
        return self


class FormApprovalCreateSchema(BaseModel):
    form_id: int
    approvers: List[ApproverSchema]
    approval_mode: Optional[Literal["sequential", "parallel"]] = "sequential"

    class Config:
        from_attributes = True


class UpdateRecognitionId(BaseModel):
    num_document: str
    recognition_id: str
    
    
class FormApprovalResponseSchema(BaseModel):
    id: int
    form_id: int
    user_id: int
    sequence_number: int
    is_mandatory: bool
    deadline_days: Optional[int] = None
    is_active: bool
    required_forms_ids: Optional[List[int]] = None
    follows_approval_sequence: bool

    class Config:
        from_attributes = True
        
class ResponseApprovalCreate(BaseModel):
    response_id: int
    user_id: int
    sequence_number: int
    is_mandatory: bool = True
    status: Optional[ApprovalStatus] = ApprovalStatus.pendiente
    message: Optional[str] = None

    class Config:
        from_attributes = True
        
    
class NotificationCreate(BaseModel):
    form_id: int
    user_id: int
    notify_on: Literal["cada_aprobacion", "aprobacion_final"]
    
class ApprovalStatusEnum(str, Enum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"


class UpdateResponseApprovalRequest(BaseModel):
    status: str
    reviewed_at: Optional[datetime] = None
    message: Optional[str] = None
    selectedSequence: int
    # Solo presente cuando el aprobador firma facialmente. Es el Answer.id de
    # una respuesta tipo regisfacial del propio aprobador (evidencia de no-repudio).
    # Reglas de coherencia (validadas en update_response_approval_status):
    #   - firm_mode='facial' + status='aprobado' → obligatorio
    #   - firm_mode='button' + firm_answer_id presente → 400
    #   - firm_mode='button_or_facial' → opcional, ambos válidos
    firm_answer_id: Optional[int] = None

    
class FormDesignUpdate(BaseModel):
    form_design: List[Dict[str, Any]]
    
class UserInfo(BaseModel):
    id: int
    name: str
    nickname: Optional[str]
    num_document: str

    class Config:
        from_attributes = True

class FormApprovalInfo(BaseModel):
    id: int
    user_id: int
    sequence_number: int
    is_mandatory: bool
    deadline_days: Optional[int]
    firm_mode: str = "button"
    firm_source_question_id: Optional[int] = None
    user: UserInfo

    class Config:
        from_attributes = True

class FormWithApproversResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    format_type: str
    form_design: Optional[Dict[str, Any]] = None
    approval_mode: str = "sequential"

    approvers: List[FormApprovalInfo]

    class Config:
        from_attributes = True
        
class FormApprovalUpdate(BaseModel):
    id: int
    user_id: Optional[int] = None
    sequence_number: Optional[int] = None
    is_mandatory: Optional[bool] = None
    deadline_days: Optional[int] = None
    firm_mode: Optional[Literal["button", "button_or_facial", "facial"]] = None
    firm_source_question_id: Optional[int] = None

class BulkUpdateFormApprovals(BaseModel):
    updates: List[FormApprovalUpdate]
    # Modo de aprobación del formato. Si viene, se actualiza forms.approval_mode.
    # Si es None, se conserva el valor actual del formato.
    approval_mode: Optional[Literal["sequential", "parallel"]] = None


class NotificationResponse(BaseModel):
    id: int  # <-- Incluimos el ID del ResponseApproval
    notify_on: str
    user: UserBase

    class Config:
        from_attributes = True


class NotificationsByFormResponse_schema(BaseModel):
    form_id: int
    notifications: List[NotificationResponse]

    class Config:
        from_attributes = True
class UpdateNotifyOnSchema(BaseModel):
    notify_on: str

    class Config:
        from_attributes = True
        
class EmailConfigCreate(BaseModel):
    email_address: EmailStr
    is_active: bool = True
    
class EmailConfigResponse(BaseModel):
    id: int
    email_address: EmailStr
    is_active: bool
    
class EmailConfigUpdate(BaseModel):
    email_address: str
    
class EmailStatusUpdate(BaseModel):
    is_active: bool
    
    

class QuestionFilterConditionCreate(BaseModel):
    form_id: int = Field(..., description="ID del formulario al que pertenece la condición")
    filtered_question_id: int = Field(..., description="ID de la pregunta que será filtrada (ej. 'proyectos activos')")
    source_question_id: int = Field(..., description="ID de la pregunta de donde vienen las respuestas (ej. 'proyectos')")
    condition_question_id: int = Field(..., description="ID de la pregunta condicional (ej. 'estatus')")
    expected_value: str = Field(..., description="Valor esperado para la condición (ej. 'Activo')")

    operator: Literal['==', '!=', '>', '<', '>=', '<=', 'in', 'not in'] = Field(
        default='==', description="Operador lógico para la comparación"
    )

    
class FilteredAnswersResponse(BaseModel):
    answer: str
    
class ResponseItem(BaseModel):
    question_id: Union[int, UUID, str] 
    response: Union[str, dict, bool]  # ✅ Ahora puede ser string, dict o booleano
    file_path: Optional[str] = None
    repeated_id: Optional[str] = None
    
class AnswerHistoryCreate(BaseModel):
    response_id: int
    previous_answer_id: Optional[int] = None
    current_answer_id: int
    
    
class QuestionAnswerDetailSchema(BaseModel):
    id: int
    question_id: int
    question_text: str
    answer_text: Optional[str]
    file_path: Optional[str]
    
    class Config:
        from_attributes = True

class AnswerHistoryChangeSchema(BaseModel):
    id: int
    previous_answer_id: Optional[int]
    current_answer_id: int
    updated_at: datetime
    previous_answer: Optional[QuestionAnswerDetailSchema]
    current_answer: QuestionAnswerDetailSchema
    
    class Config:
        from_attributes = True

class ResponseWithAnswersAndHistorySchema(BaseModel):
    id: int
    form_id: int
    user_id: int
    mode: str
    mode_sequence: int
    repeated_id: Optional[str]
    submitted_at: datetime
    current_answers: List[QuestionAnswerDetailSchema]
    answer_history: List[AnswerHistoryChangeSchema]
    
    class Config:
        from_attributes = True
        

class FormCloseConfigCreate(BaseModel):
    form_id: int
    send_download_link: bool = False
    send_pdf_attachment: bool = False
    generate_report: bool = False
    do_nothing: bool = True
    send_custom_template: bool = False
    custom_template_include_pdf: bool = False
    download_link_recipients: Optional[List[str]] = None
    email_recipients: Optional[List[str]] = None
    report_recipients: Optional[List[str]] = None
    custom_template_recipients: Optional[List[str]] = None
    custom_template_id: Optional[int] = None
    custom_email_subject: Optional[str] = None
    custom_email_body: Optional[str] = None

    @validator('download_link_recipients', 'email_recipients', 'report_recipients', 'custom_template_recipients', pre=True)
    def validate_emails(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as e:
                # SECURITY (ID-040): bare `except:` reemplazado; no logueamos `v` por contener PII (emails).
                logger.warning("ID-040: validate_emails JSON parse fallido (%s) → fallback [v]", type(e).__name__)
                return [v]
        return v
class FormCloseConfigOut(BaseModel):
    id: int
    form_id: int
    send_download_link: bool
    send_pdf_attachment: bool
    generate_report: bool
    do_nothing: bool
    send_custom_template: bool
    custom_template_include_pdf: bool
    download_link_recipients: Optional[List[str]] = None
    email_recipients: Optional[List[str]] = None
    report_recipients: Optional[List[str]] = None
    custom_template_recipients: Optional[List[str]] = None
    custom_template_id: Optional[int] = None
    custom_email_subject: Optional[str] = None
    custom_email_body: Optional[str] = None

    class Config:
        orm_mode = True

    @validator('download_link_recipients', 'email_recipients', 'report_recipients', 'custom_template_recipients', pre=True)
    def parse_json_field(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as e:
                # SECURITY (ID-040): bare `except:` reemplazado; no logueamos `v` por contener PII (emails).
                logger.warning("ID-040: parse_json_field JSON parse fallido (%s) → fallback []", type(e).__name__)
                return []
        return v

class FormCloseConfigUpdate(BaseModel):
    send_download_link: Optional[bool] = None
    send_pdf_attachment: Optional[bool] = None
    generate_report: Optional[bool] = None
    do_nothing: Optional[bool] = None
    download_link_recipient: Optional[EmailStr] = None
    email_recipient: Optional[EmailStr] = None
    report_recipient: Optional[EmailStr] = None



class QuestionLocationRelationCreate(BaseModel):
    form_id: int
    origin_question_id: int
    target_question_id: int  
    
    

class QuestionLocationRelationOut(BaseModel):
    id: int
    form_id: int
    origin_question_id: int
    target_question_id: int
    created_at: datetime

    class Config:
        from_attributes = True
        
        
class QuestionCategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None  
class QuestionCategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    subcategories: Optional[List["QuestionCategoryOut"]] = []

    class Config:
        from_attributes = True
class CategorySchema(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class AliasSchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    
    class Config:
        from_attributes = True
        

class FormBasicInfo(BaseModel):
    id: int
    title: str

    class Config:
        from_attributes = True
        
class QuestionWithCategory(BaseModel):
    id: int
    question_text: str
    description: Optional[str] = None
    question_type: str
    required: bool
    root: bool
    category: CategorySchema | None
    related_question_id: Optional[int] = None
    related_question: Optional[dict] = None  # ← CAMBIAR A dict, no a objeto
    forms: List[FormBasicInfo] = []
    id_form: Optional[int] = None
    class Config:
        from_attributes = True


        
class UpdateQuestionCategory(BaseModel):
    id_category: int | None
    
class UserCategoryCreate(BaseModel):
    name: str

class UserCategoryResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class UpdateUserCategory(BaseModel):
    id_category: Optional[int] = None
    
class FormCategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    parent_id: Optional[int] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    order: int = 0
    
class FormCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    parent_id: Optional[int] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    order: Optional[int] = None
class FormCategoryMove(BaseModel):
    new_parent_id: Optional[int] = None
    new_order: Optional[int] = None

# Esquema para crear categoría
class FormCategoryCreate(FormCategoryBase):
    pass

# Esquema para actualizar categoría de un formulario
class UpdateFormCategory(BaseModel):
    id_category: Optional[int] = None

# Esquema de respuesta para categoría
class FormCategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    parent_id: Optional[int]
    icon: Optional[str]
    color: Optional[str]
    order: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    # Contadores útiles
    forms_count: int = 0
    children_count: int = 0
    
    class Config:
        from_attributes = True

class FormCategoryResponse(BaseModel):
    # Asumo que estos campos están presentes o son similares en tu modelo base:
    id: int
    name: str
    parent_id: Optional[int] = None
    
    order: Optional[int] = None # Acepta int O None, lo que resuelve el error 500.
    
    class Config:
        from_attributes = True

class UpdateFormBasicInfo(BaseModel):
    title: Optional[str] = Field(None, max_length=255, min_length=1)
    description: Optional[str] = Field(None, max_length=255)
    format_type: Optional[FormatTypeEdit] = None
    project_id: Optional[int] = None

# Tu clase FormCategoryTreeResponse quedaría igual, ya que hereda la solución:
class FormCategoryTreeResponse(FormCategoryResponse):
    children: List['FormCategoryTreeResponse'] = []
    forms: List['FormResponse'] = [] 

FormCategoryTreeResponse.model_rebuild()

# Tu clase FormCategoryWithFormsResponse también se beneficia:
class FormCategoryWithFormsResponse(FormCategoryResponse):
    forms: List['FormResponse'] = []
     
    class Config:
        from_attributes = True
# Esquema básico de formulario para evitar importación circular
class FormBasicResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    format_type: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# Actualizar el esquema de Form para incluir categoría
class FormResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    format_type: str
    created_at: datetime
    user_id: int
    id_category: Optional[int] = None
    is_enabled: bool = True
    category: Optional[FormCategoryResponse] = None
    
    class Config:
        from_attributes = True
 
 
 
 
class FilterCondition(BaseModel):
    field_id: int
    operator: str  # "=", "!=", "contains", "starts_with", "ends_with", ">", "<", ">=", "<="
    value: str
    # Nuevo campo opcional para especificar formularios (Opción B)
    target_form_ids: Optional[List[int]] = None  # Si es None, se aplica a todos los formularios que tengan el campo
    
class DateFilter(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class DownloadRequest(BaseModel):
    form_ids: List[int]
    selected_fields: List[int]  # IDs de las preguntas que quiere incluir
    conditions: List[FilterCondition] = []
    date_filter: Optional[DateFilter] = None
    limit: Optional[int] = 100  # Para preview


class RegisfacialAnswerResponse(BaseModel):
    answer_text: str
    encrypted_hash: str

    class Config:
        from_attributes = True
        
        
class ApprovalRequirementCreateSchema(BaseModel):
    form_id: int
    approver_id: int
    required_form_id: int
    linea_aprobacion: Optional[bool] = True

class ApprovalRequirementsCreateSchema(BaseModel):
    requirements: List[ApprovalRequirementCreateSchema]



class ResponseRequirementCreate(BaseModel):
    response_id: int
    approval_requirement_id: int
    fulfilling_response_id: int = None
    
class ResponseRequirementUpdate(BaseModel):
    fulfilling_response_id: int = None
    is_fulfilled: bool = False
   
class ApprovalRequirementInfo(BaseModel):
    requirement_id: int
    required_form: dict
    linea_aprobacion: bool
    approver: dict
    fulfillment_status: dict

class ApproverInfo(BaseModel):
    user_id: int
    sequence_number: int
    is_mandatory: bool
    status: str
    reconsideration_requested: bool
    reviewed_at: Optional[datetime]
    message: Optional[str]
    attachment_files: Optional[Any] = None
    # Método de firma de la ResponseApproval (heredado del FormApproval al
    # enviar la respuesta). Default 'button' para retrocompatibilidad.
    firm_mode: str = "button"
    # Si ya aprobó facialmente, aquí queda el id del Answer regisfacial usado.
    firm_answer_id: Optional[int] = None
    # Pregunta regisfacial fuente configurada por el admin.
    firm_source_question_id: Optional[int] = None
    user: dict

class ResponseDetailInfo(BaseModel):
    response_id: int
    form_id: int
    form_title: str
    form_description: str
    submitted_by: dict
    submitted_at: datetime
    your_approval_status: Optional[dict]
    all_approvers: List[ApproverInfo]
    approval_requirements: dict
    
class RequiredFormsResponse(BaseModel):
    main_response_id: int
    approver: Dict[str, Any]
    required_forms: List[Dict[str, Any]]
    summary: Dict[str, Any]
    
class FormStatusUpdate(BaseModel):
    is_enabled: bool
    
    class Config:
        json_schema_extra = {
            "example": {
                "is_enabled": False
            }
        }
        
class BitacoraLogsSimpleCreate(BaseModel):
    clasificacion: str
    titulo: str
    fecha: str
    hora: str
    ubicacion: Optional[str] = None
    participantes: Optional[str] = None
    descripcion: Optional[str] = None
    archivos: Optional[List[str]] = None  # lista de nombres de archivos subidos

class BitacoraLogsSimpleAnswer(BaseModel):
    titulo: str
    fecha: str
    hora: str
    ubicacion: Optional[str] = None
    participantes: Optional[str] = None
    descripcion: Optional[str] = None
    archivos: Optional[List[str]] = None

class BitacoraResponse(BaseModel):
    id: int
    clasificacion: str
    titulo: str
    descripcion: Optional[str]
    fecha: str
    hora: str
    registrado_por: str
    estado: str
    atendido_por: Optional[str]
    archivos: Optional[List[str]] = [] 
    created_at: datetime
    respuestas: List["BitacoraResponse"] = []

    class Config:
        orm_mode = True
        arbitrary_types_allowed = True

BitacoraResponse.update_forward_refs()


class PalabrasClaveCreate(BaseModel):
    form_id: int
    keywords: List[str]  # Lista de palabras clave

class FormResponseBitacora(BaseModel):
    id: int
    title: str
    description: Optional[str]
    format_type: str
    id_category: Optional[int]
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True

class PalabrasClaveOut(BaseModel):
    id: int
    form_id: int
    keywords: str

    class Config:
        from_attributes = True

class PalabrasClaveUpdate(BaseModel):
    palabra: str
    
    
class RelationOperationMathCreate(BaseModel):
    id_form: int = Field(..., gt=0, description="ID del formulario")
    id_questions: List[int] = Field(..., min_items=1, description="Lista de IDs de preguntas")
    operations: str = Field(..., min_length=1, max_length=500, description="Fórmula u operación matemática")

    class Config:
        example = {
            "id_form": 1,
            "id_questions": [1, 2, 3],
            "operations": "Q1 + Q2 * Q3"
        }


class RelationOperationMathOut(BaseModel):
    id: int
    id_form: int
    id_questions: List[int]
    operations: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        
        
class GetQuestionTextsRequest(BaseModel):
    question_ids: List[int]

class QuestionTextValue(BaseModel):
    question_id: int
    question_text: str

class GetQuestionTextsResponse(BaseModel):
    questions: List[QuestionTextValue]
    
class RelationOperationMathCreate(BaseModel):
    id_form: int = Field(..., description="ID del formulario")
    id_questions: List[int] = Field(..., description="Lista de IDs de preguntas")
    operations: str = Field(..., description="Fórmula matemática")

class RelationOperationMathOut(BaseModel):
    id: int
    id_form: int
    id_questions: List[int]
    operations: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
        
class AlertMessageRequest(BaseModel):
    alert_message: str

class InstructivoFile(BaseModel):
    """Modelo para cada archivo de instructivo"""
    url: str
    description: str
    original_name: str
    file_type: str
    size: int

class RelatedQuestionInfo(BaseModel):
    id: int
    question_text: str

    class Config:
        from_attributes = True

class RelatedSelectInfo(BaseModel):
    question_id: int
    question_text: str
    related_question_id: int
    related_question_text: str
    related_form_id: Optional[int] = None
    can_autocomplete: bool = False

class AutocompleteRelation(BaseModel):
    source_question_id: int
    target_question_id: int
    relation_group_id: str  # UUID único para agrupar campos relacionados
    color: str  # Color hex para identificación visual
    
class DetectSelectRelationsRequest(BaseModel):
    form_id: int
    question_ids: List[int]

class AnswerByQuestionResponse(BaseModel):
    answer_id: int
    question_id: int
    response_id: int
    form_id: int
    user_id: int
    answer_text: Optional[str]
    file_path: Optional[str]
    submitted_at: datetime

    class Config:
        from_attributes = True
        
class AliasBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="nombre_completo")
    description: Optional[str] = Field(None, max_length=500, example="Campo para el nombre completo")

class AliasCreate(AliasBase):
    pass

class AliasUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)

class AliasResponse(AliasBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AliasList(BaseModel):
    id: int
    name: str
    description: Optional[str]

    class Config:
        from_attributes = True
        
class AliasBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="nombre_completo")
    description: Optional[str] = Field(None, max_length=500, example="Campo para el nombre completo")

class AliasCreate(AliasBase):
    pass

class AliasUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)

class AliasResponse(AliasBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AliasList(BaseModel):
    id: int
    name: str
    description: Optional[str]

    class Config:
        from_attributes = True

class MovementAliasGroup(BaseModel):
    """
    Agrupa varios campos (preguntas) de un movimiento bajo un mismo alias.
    Es ESPECÍFICO del movimiento (aislado): no toca la tabla global `alias`
    ni `Question.id_alias`. Ej: alias "NOMBRE" une "nombre del empleado" y
    "nombre del ingeniero" para que representen lo mismo dentro del movimiento.
    """
    name: str = Field(..., min_length=1, max_length=255, example="NOMBRE")
    description: Optional[str] = Field(None, max_length=500)
    question_ids: List[int] = []


class MovementFormAlias(BaseModel):
    """
    Alias por FORMATO dentro de un movimiento (aislado). Renombra cómo se ve
    cada formato de origen en la columna "Formato origen" del detalle, sin tocar
    el título real del formato.
    """
    form_id: int
    alias: str = Field(..., min_length=1, max_length=255)


class FormMovimientoBase(BaseModel):
    form_ids: List[int] = []
    question_ids: List[int] = []
    title: str
    description: Optional[str] = None
    id_category: Optional[int] = None
    alias_groups: List[MovementAliasGroup] = []
    form_aliases: List[MovementFormAlias] = []


class FormMovimientoResponse(BaseModel):
    id: int
    user_id: int
    form_ids: List[int]
    question_ids: List[int]
    title: str
    description: Optional[str]
    id_category: Optional[int]
    is_enabled: bool
    created_at: datetime
    alias_groups: List[MovementAliasGroup] = []
    form_aliases: List[MovementFormAlias] = []
    
class LastAnswerFilterRequest(BaseModel):
    form_id: int
    target_question_id: int  # ID de la pregunta cuya respuesta queremos (ej: "proyecto")
    filter_question_id: int  # ID de la pregunta para filtrar (ej: "nombre")
    filter_value: str        # Valor con el que filtrar (ej: "Neider")

# Schema para la respuesta
class LastAnswerResponse(BaseModel):
    response_id: int
    answer_id: int
    answer_text: Optional[str]
    file_path: Optional[str]
    submitted_at: str
    question_text: str
    filter_question_text: str
    filter_value_found: str

    class Config:
        from_attributes = True

from pydantic import BaseModel

class RelatedAnswerRequest(BaseModel):
    form_id: int
    question_id_base: int
    value_base: str
    question_id_match: int
    question_id_lookup: int

class EmailAnswerItem(BaseModel):
    question_text: str
    answer_text: Optional[str] = None
    file_path: Optional[str] = None

class SendResponseEmailRequest(BaseModel):
    email_to: List[str]   # 🔥 antes era string
    form_title: str
    response_id: int
    answers: List[EmailAnswerItem]

class RelationQuestionRuleCreate(BaseModel):
    id_form: int
    id_question: int
    id_response: Optional[int] = None
    date_notification: Optional[datetime] = None
    time_alert: Optional[str] = None
    enabled: Optional[bool] = True

class RelationQuestionRuleResponse(BaseModel):
    id: int
    id_form: int
    id_question: int
    id_response: Optional[int]
    date_notification: Optional[datetime]
    time_alert: Optional[str]
    enabled: bool

    class Config:
        from_attributes = True


class FormTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    id_category: Optional[int] = None
    tags: Optional[List[str]] = []
    scope: Optional[str] = "private"
    source_form_id: Optional[int] = None
    template_design: Optional[List[Dict[str, Any]]] = None


class FormTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    id_category: Optional[int] = None
    tags: Optional[List[str]] = None
    scope: Optional[str] = None
    template_design: Optional[List[Dict[str, Any]]] = None


class TemplateCategoryInfo(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None

    class Config:
        from_attributes = True


class FormTemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    id_category: Optional[int]
    category: Optional[TemplateCategoryInfo] = None
    tags: List[str]
    scope: str
    usage_count: int
    created_at: datetime
    updated_at: datetime
    user_id: int

    class Config:
        from_attributes = True


class FormTemplateDetail(FormTemplateResponse):
    template_design: List[Dict[str, Any]]


class CategoryApprovalCreate(BaseModel):
    user_id: int
    sequence_number: int = Field(1, ge=1)
    is_mandatory: bool = True
    deadline_days: Optional[int] = None
    # Método de firma. Hereda al FormApproval cuando un formato adopta los
    # aprobadores de su categoría.
    firm_mode: Literal["button", "button_or_facial", "facial"] = Field(default="button")
    # Pregunta regisfacial fuente. Obligatoria cuando firm_mode != 'button'.
    firm_source_question_id: Optional[int] = None

    @model_validator(mode="after")
    def _validate_firm_source(self) -> "CategoryApprovalCreate":
        if self.firm_mode != "button" and self.firm_source_question_id is None:
            raise ValueError(
                "firm_source_question_id es obligatorio cuando firm_mode != 'button'"
            )
        return self


class CategoryApprovalUpdate(BaseModel):
    sequence_number: Optional[int] = Field(None, ge=1)
    is_mandatory: Optional[bool] = None
    deadline_days: Optional[int] = None
    is_active: Optional[bool] = None
    firm_mode: Optional[Literal["button", "button_or_facial", "facial"]] = None
    firm_source_question_id: Optional[int] = None


class CategoryApprovalBulkSave(BaseModel):
    """Para guardar toda la lista de aprobadores de una categoría de una vez."""
    approvers: List[CategoryApprovalCreate]
    # Modo de aprobación de la categoría. Si viene, se actualiza
    # form_categories.approval_mode (y se propaga a los formatos cuando se
    # sincroniza). Si es None, se conserva el valor actual de la categoría.
    approval_mode: Optional[Literal["sequential", "parallel"]] = None


class ApproverUserInfo(BaseModel):
    id: int
    name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class CategoryApprovalResponse(BaseModel):
    id: int
    category_id: int
    user_id: int
    user: Optional[ApproverUserInfo] = None
    sequence_number: int
    is_mandatory: bool
    deadline_days: Optional[int]
    is_active: bool
    firm_mode: str = "button"
    firm_source_question_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CategoryWithApproversResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    approval_mode: str = "sequential"
    approvers: List[CategoryApprovalResponse] = []

    class Config:
        from_attributes = True

class UpdateFormCategory(BaseModel):
    id_category: Optional[int] = None
    sync_approvers: Optional[bool] = True  # ← NUEVO

class UpdateMathOperationRequest(BaseModel):
    operations: str


class QuestionUpdatePayload(BaseModel):
    question_text: Optional[str] = None
    description: Optional[str] = None
    question_type: Optional[str] = None
    id_category: Optional[int] = None
    id_form: Optional[int] = None


# ===================== CONSULTANTS =====================

class ConsultantScopeStr(str, Enum):
    form = "form"
    user = "user"
    form_user = "form_user"
    category = "category"


class ConsultantAssignmentCreate(BaseModel):
    consultant_id: int
    scope: ConsultantScopeStr
    form_id: Optional[int] = None
    target_user_id: Optional[int] = None
    category_id: Optional[int] = None


class ConsultantAssignmentUpdate(BaseModel):
    scope: Optional[ConsultantScopeStr] = None
    form_id: Optional[int] = None
    target_user_id: Optional[int] = None
    category_id: Optional[int] = None
    is_active: Optional[bool] = None


class ConsultantAssignmentOut(BaseModel):
    id: int
    consultant_id: int
    consultant_name: Optional[str] = None
    consultant_email: Optional[str] = None
    scope: ConsultantScopeStr
    form_id: Optional[int] = None
    form_title: Optional[str] = None
    target_user_id: Optional[int] = None
    target_user_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ConsultantUserOut(BaseModel):
    """Un usuario con sus asignaciones agrupadas, para la pantalla admin."""
    consultant_id: int
    consultant_name: str
    consultant_email: str
    assignments: List[ConsultantAssignmentOut] = []


class ConsultantResponseRow(BaseModel):
    """Cada respuesta visible para el consultor."""
    response_id: int
    form_id: int
    form_title: str
    submitted_by_id: int
    submitted_by_name: str
    submitted_at: Optional[datetime] = None
    status: Optional[str] = None
    category_name: Optional[str] = None


class ConsultantResponsesPage(BaseModel):
    items: List[ConsultantResponseRow]
    total: int
    page: int
    page_size: int


class ConsultantAssignmentBulkRule(BaseModel):
    scope: ConsultantScopeStr
    form_id: Optional[int] = None
    target_user_id: Optional[int] = None
    category_id: Optional[int] = None


class ConsultantAssignmentBulkCreate(BaseModel):
    consultant_id: int
    rules: List[ConsultantAssignmentBulkRule]


# ─────────────────────────────────────────────────────────────────────────────
# PROFILES
# ─────────────────────────────────────────────────────────────────────────────

class ProfileMemberOut(BaseModel):
    id: int
    name: str
    email: str
    num_document: Optional[str] = None
    user_type: Optional[str] = None

    class Config:
        from_attributes = True


class ProfileFormOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class ProfileCategoryOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    user_ids: List[int] = []
    form_ids: List[int] = []
    category_ids: List[int] = []


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProfileMembersUpdate(BaseModel):
    user_ids: List[int]


class ProfileFormsUpdate(BaseModel):
    form_ids: List[int]


class ProfileCategoriesUpdate(BaseModel):
    category_ids: List[int]


class ProfileOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    users: List[ProfileMemberOut] = []
    forms: List[ProfileFormOut] = []
    categories: List[ProfileCategoryOut] = []

    class Config:
        from_attributes = True


class ProfileSummaryOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    user_count: int
    form_count: int           # formatos efectivos (directos + via categoria), distinct
    direct_form_count: int    # solo asignados directamente
    category_count: int       # categorias enlazadas
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# GENERIC ACTIVITIES (Actividades genéricas)
# Una actividad agrupa formatos y, por cada formato, define quién lo diligencia
# (un usuario elegido a través de un perfil). Varios diligenciadores por formato.
# ─────────────────────────────────────────────────────────────────────────────

class GenericActivityFormItem(BaseModel):
    """Una asignación: el formato form_id lo diligencia user_id, elegido vía
    profile_id (el perfil del cual se escogió al usuario)."""
    form_id: int
    user_id: int
    profile_id: Optional[int] = None


class GenericActivityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    items: List[GenericActivityFormItem] = []
    # Feature "Servicios": formatos del servicio (la asignación de usuarios es
    # OPCIONAL/diferida). Pueden venir solo aquí, sin items.
    form_ids: List[int] = []
    # Clasificación opcional: formato + pregunta + valor elegido.
    classification_form_id: Optional[int] = None
    classification_question_id: Optional[int] = None
    classification_value: Optional[str] = Field(None, max_length=255)


class GenericActivityUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    # Clasificación: enviar los 3 juntos para fijarla; enviar value="" (o null
    # en los tres) para limpiarla. Ver lógica del endpoint.
    classification_form_id: Optional[int] = None
    classification_question_id: Optional[int] = None
    classification_value: Optional[str] = Field(None, max_length=255)


class GenericActivityFormsUpdate(BaseModel):
    """Reemplaza por completo el conjunto de asignaciones de la actividad."""
    items: List[GenericActivityFormItem]


class GenericActivityFormOut(BaseModel):
    id: int
    form_id: int
    form_title: str
    profile_id: Optional[int] = None
    profile_name: Optional[str] = None
    user_id: int
    user_name: str
    user_email: Optional[str] = None

    class Config:
        from_attributes = True


class GenericActivityFormLinkOut(BaseModel):
    """Un formato que pertenece al servicio (sin/independiente de diligenciador)."""
    id: int
    form_id: int
    form_title: str

    class Config:
        from_attributes = True


class GenericActivityOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Formatos del servicio (feature "Servicios"). Independiente de items.
    forms: List[GenericActivityFormLinkOut] = []
    items: List[GenericActivityFormOut] = []
    # Clasificación
    classification_form_id: Optional[int] = None
    classification_form_title: Optional[str] = None
    classification_question_id: Optional[int] = None
    classification_question_text: Optional[str] = None
    classification_value: Optional[str] = None

    class Config:
        from_attributes = True


class GenericActivitySummaryOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    form_count: int        # formatos distintos en la actividad
    assignment_count: int  # total de asignaciones (filas formato↔usuario)
    created_at: datetime
    updated_at: datetime
    classification_value: Optional[str] = None

    class Config:
        from_attributes = True


class GenericActivityMineOut(BaseModel):
    """Para el endpoint /me: actividades donde el usuario es diligenciador."""
    id: int
    name: str
    description: Optional[str] = None
    form_count: int  # formatos asignados a ESTE usuario en la actividad
    classification_value: Optional[str] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Feature "Servicios" — pregunta clasificadora por formato + relación
# respuesta↔servicio + selección de servicios al diligenciar.
# ─────────────────────────────────────────────────────────────────────────────

class ClassifiableQuestionOut(BaseModel):
    """Pregunta texto/select candidata a clasificar servicios."""
    question_id: int
    question_text: str
    question_type: str


class FormServiceClassificationOut(BaseModel):
    """Pregunta clasificadora actual de un formato (vacía si no hay)."""
    form_id: int
    question_id: Optional[int] = None
    question_text: Optional[str] = None


class FormServiceClassificationSet(BaseModel):
    """Fija (question_id) o limpia (question_id=null) la pregunta clasificadora."""
    question_id: Optional[int] = None


class ServiceSelectableOut(BaseModel):
    """Servicio activo (id+nombre) para el modal de relación al diligenciar."""
    id: int
    name: str


class ResponseServiceLinkCreate(BaseModel):
    """Relaciona la respuesta con un servicio. classification_value es el valor
    respondido en la pregunta clasificadora (respaldo)."""
    activity_id: int
    question_id: Optional[int] = None
    classification_value: Optional[str] = Field(None, max_length=255)


class ResponseServiceLinkOut(BaseModel):
    id: int
    response_id: int
    activity_id: int
    activity_name: str
    question_id: Optional[int] = None
    classification_value: Optional[str] = None

    class Config:
        from_attributes = True


class ResponseServiceLinkDetailOut(BaseModel):
    """Una respuesta relacionada con el servicio al diligenciar (clasificación
    a nivel de respuesta). Para mostrarla en el apartado de Servicios."""
    response_id: int
    form_id: int
    form_title: str
    user_name: str
    classification_value: Optional[str] = None
    submitted_at: Optional[datetime] = None


class ServiceFormLinksAdd(BaseModel):
    """Agrega formatos a un servicio existente (additivo)."""
    form_ids: List[int]


class ServiceAssignmentsAdd(BaseModel):
    """Asigna diligenciadores a un formato del servicio (additivo)."""
    form_id: int
    user_ids: List[int]
    profile_id: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Editores de respuestas (formatos cerrados)
# ─────────────────────────────────────────────────────────────────────────────

AnswerEditorsModeLiteral = Literal['none', 'all', 'list']


class AnswerEditorUserOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    num_document: Optional[str] = None

    class Config:
        from_attributes = True


class AnswerEditorsConfigOut(BaseModel):
    form_id: int
    format_type: str
    mode: AnswerEditorsModeLiteral
    users: List[AnswerEditorUserOut] = []


class AnswerEditorsConfigUpdate(BaseModel):
    mode: AnswerEditorsModeLiteral
    user_ids: List[int] = []
