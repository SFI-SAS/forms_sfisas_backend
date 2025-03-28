
import os
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List
from app.crud import create_answer_in_db, post_create_response
from app.database import get_db
from app.schemas import PostCreate
from app.models import User, UserType
from app.core.security import get_current_user


router = APIRouter()

        
@router.post("/save-response/{form_id}") 
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


UPLOAD_FOLDER = "./documents"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@router.post("/upload-file/")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Generar un nombre único para el archivo usando uuid
        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        # Guardar el archivo en la carpeta "documents"
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        return JSONResponse(content={
            "message": "File uploaded successfully",
            "file_name": unique_filename
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
