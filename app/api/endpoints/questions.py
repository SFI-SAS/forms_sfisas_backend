from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import User, UserType
from app.crud import create_question, update_question, get_questions, get_question_by_id
from app.schemas import QuestionCreate, QuestionUpdate, QuestionResponse
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question_endpoint(
    question: QuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    print(question)
    # Restringir la creación de preguntas solo a usuarios permitidos (e.g., admins)
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create questions"
        )
    
    return create_question(db=db, question=question)

@router.put("/{question_id}", response_model=QuestionResponse)
def update_question_endpoint(
    question_id: int,
    question: QuestionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Restringir la actualización de preguntas solo a usuarios permitidos (e.g., admins)
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update questions"
        )
    
    db_question = get_question_by_id(db, question_id)
    if not db_question:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    return update_question(db=db, question_id=question_id, question=question)

@router.get("/", response_model=List[QuestionResponse])
def get_all_questions(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update questions"
        )
    else: 
        # Este endpoint puede ser accesible para cualquier usuario autenticado
        questions = get_questions(db, skip=skip, limit=limit)
        return questions