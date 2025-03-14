from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.crud import create_answer_in_db, post_create_response
from app.database import get_db
from app.schemas import PostCreate
from app.models import User, UserType
from app.core.security import get_current_user

router = APIRouter()

@router.post("/save-response/{form_id}")  # Nuevo nombre para el endpoint
def save_response(form_id: int,  current_user: User = Depends(get_current_user),  db: Session = Depends(get_db)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    else: 
        return post_create_response(db, form_id, current_user.id)


@router.post("/save-answers/")  
def create_answer(answer: PostCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    else: 
        new_answer = create_answer_in_db(answer, db)
        return {"message": "Answer created", "answer": new_answer}
