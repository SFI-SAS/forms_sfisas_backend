from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

# Enum for UserType
class UserType(str, Enum):
    admin = "admin"
    respondent = "respondent"

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
    user_type: UserType = Field(default=UserType.respondent, example="respondent") 

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
    status: Optional[FormStatus] = FormStatus.draft  # Aquí corregido
    created_at: datetime
    
    
class FormBase(BaseModel):
    title: str = Field(..., example="Survey Form")
    description: Optional[str] = Field(None, example="This is a survey form description.")
    status: Optional[FormStatus] = FormStatus.draft

class FormCreate(FormBase):
    pass

class FormResponse(FormBase):
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
