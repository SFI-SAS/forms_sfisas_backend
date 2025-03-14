from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.crud import create_answer_in_db, post_create_response
from app.database import get_db
from app.schemas import PostCreate

router = APIRouter()

@router.post("/save-response/{form_id}/{user_id}")  # Nuevo nombre para el endpoint
def save_response(form_id: int, user_id: int, db: Session = Depends(get_db)):
    return post_create_response(db, form_id, user_id)


@router.post("/save-answers/")
def create_answer(answer: PostCreate, db: Session = Depends(get_db)):
    new_answer = create_answer_in_db(answer, db)
    return {"message": "Answer created", "answer": new_answer}
