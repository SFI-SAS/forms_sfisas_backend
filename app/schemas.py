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

# Schemas for Form
class FormBase(BaseModel):
    title: str = Field(..., example="Survey Form")
    description: Optional[str] = Field(None, example="This is a survey form description.")
    status: Optional[FormStatus] = FormStatus.draft

class FormCreate(FormBase):
    pass

class FormResponse(FormBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class QuestionAdd(BaseModel):
    question_ids: List[int]

# Schemas for Question
class QuestionBase(BaseModel):
    question_text: str = Field(..., example="What is your favorite color?")
    question_type: str = Field(..., example="multiple_choice")

class QuestionCreate(QuestionBase):
    pass # Allow creation without assignment

class QuestionResponse(QuestionBase):
    id: int
    form_id: int

    class Config:
        from_attributes = True

class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    question_type: Optional[str] = None

# Schemas for Option
class OptionBase(BaseModel):
    option_text: str = Field(..., example="Blue")

class OptionCreate(OptionBase):
    pass

class OptionResponse(OptionBase):
    id: int
    question_id: int

    class Config:
        from_attributes = True

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