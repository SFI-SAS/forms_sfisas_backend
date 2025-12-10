import json
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Any, Literal, Optional, List, Dict, Union
from datetime import date, datetime
from enum import Enum

from app.models import ApprovalStatus

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

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    user_type: Optional[UserType] = None
    
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
    question_type: str = Field(..., example="multiple_choice")
    required: bool = Field(..., example=True) 
    root:bool =  Field(..., example=True) 
    id_category: Optional[int] = None


class QuestionBaseAll(BaseModel):
    question_text: str = Field(..., example="What is your favorite color?")
    question_type: str = Field(..., example="multiple_choice")
    required: bool = Field(..., example=True) 
    root:bool =  Field(..., example=True)
    id_category: int | None = None
    
    
class QuestionCreate(QuestionBase):
    pass # Allow creation without assignment

class QuestionResponse(QuestionBaseAll):
    id: int
    
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
   
    title: str = Field(..., example="Survey Form")
    description: Optional[str] = Field(None, example="This is a survey form description.")
    assign_user: List[int]  
    format_type: FormatTypeEnum = Field(..., example="abierto") 
    id_category: Optional[int] 

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


class FormApprovalCreateSchema(BaseModel):
    form_id: int
    approvers: List[ApproverSchema]

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
    user: UserInfo

    class Config:
        from_attributes = True

class FormWithApproversResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    format_type: str
    form_design: Optional[Dict[str, Any]] = None

    approvers: List[FormApprovalInfo]

    class Config:
        from_attributes = True
        
class FormApprovalUpdate(BaseModel):
    id: int
    user_id: Optional[int] = None
    sequence_number: Optional[int] = None
    is_mandatory: Optional[bool] = None
    deadline_days: Optional[int] = None

class BulkUpdateFormApprovals(BaseModel):
    updates: List[FormApprovalUpdate]
    
    
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
    
    # 🆕 Ahora son listas de strings
    download_link_recipients: Optional[List[str]] = None
    email_recipients: Optional[List[str]] = None
    report_recipients: Optional[List[str]] = None
    
    @validator('download_link_recipients', 'email_recipients', 'report_recipients', pre=True)
    def validate_emails(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
                return [v]
        return v

class FormCloseConfigOut(BaseModel):
    id: int
    form_id: int
    send_download_link: bool
    send_pdf_attachment: bool
    generate_report: bool
    do_nothing: bool
    download_link_recipients: Optional[List[str]] = None
    email_recipients: Optional[List[str]] = None
    report_recipients: Optional[List[str]] = None
    
    class Config:
        orm_mode = True
        
    @validator('download_link_recipients', 'email_recipients', 'report_recipients', pre=True)
    def parse_json_field(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
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


class QuestionWithCategory(BaseModel):
    id: int
    question_text: str
    question_type: str
    required: bool
    root: bool
    category: CategorySchema | None  # o directamente Optional[CategorySchema]

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
        
        
class GetAnswersRequest(BaseModel):
    response_id: int
    question_ids: List[int]

class AnswerValue(BaseModel):
    question_id: int
    question_text: str
    answer_text: str | None
    answer_value: float | None  # Para operaciones matemáticas

class GetAnswersResponse(BaseModel):
    response_id: int
    form_id: int
    answers: List[AnswerValue]