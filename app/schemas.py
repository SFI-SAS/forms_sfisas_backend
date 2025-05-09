from pydantic import BaseModel, EmailStr, Field
from typing import Any, Literal, Optional, List, Dict
from datetime import datetime
from enum import Enum

from app.models import ApprovalStatus

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

class QuestionCreate(QuestionBase):
    pass # Allow creation without assignment

class QuestionResponse(QuestionBase):
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
    question_id: int
    answer_text: str | None = None
    file_path: str | None = None
    
class FormScheduleCreate(BaseModel):
    form_id: int
    user_id: int
    frequency_type: str  # daily, weekly, monthly, periodic, specific_date
    repeat_days: Optional[list[str]] = None  # para weekly
    interval_days: Optional[int] = None      # para periodic
    specific_date: Optional[datetime] = None # para specific_date
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
    
class UpdateAnswerText(BaseModel):
    id: int
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

class ApproverSchema(BaseModel):
    user_id: int
    sequence_number: int
    is_mandatory: bool = True
    deadline_days: int | None = None

class FormApprovalCreateSchema(BaseModel):
    form_id: int
    approvers: List[ApproverSchema]
    
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
    status: ApprovalStatusEnum
    reviewed_at: datetime = None
    message: str = None
    
class FormDesignUpdate(BaseModel):
    form_design: Dict[str, Any]
    
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
    form_design: Optional[dict]
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