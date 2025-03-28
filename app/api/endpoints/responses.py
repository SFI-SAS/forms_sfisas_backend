import boto3
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from typing import List
from app.crud import create_answer_in_db, post_create_response
from app.database import get_db
from app.schemas import PostCreate
from app.models import User, UserType
from app.core.security import get_current_user
import logging
from datetime import datetime

router = APIRouter()

CLIENT_NOT_FOUND_ERROR = "Client not found"
AWS_BUCKET = 'isometria'
s3 = boto3.client('s3')

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

async def s3_upload(contents: bytes, key: str) -> str:
    try:
        logger.info(f'Subiendo {key} a S3')
        
        s3.put_object(Bucket=AWS_BUCKET, Key=key, Body=contents)

        file_url = f"https://{AWS_BUCKET}.s3.amazonaws.com/{key}"
        logger.info(f'Archivo subido a S3 con URL: {file_url}')

        return file_url
    except Exception as e:
        logger.error(f'Error al subir {key} a S3: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Error al subir el archivo a S3'
        )
        
        
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



@router.post("/upload_document")
async def upload_document(document_number: str, file: UploadFile = None):
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe subir un archivo"
        )

    # Crear un nombre de archivo con número de documento y fecha/hora actuales
    current_time = datetime.now().strftime("%Y%m%d%H%M%S")  # Formato: YYYYMMDDHHMMSS
    file_extension = file.filename.split('.')[-1]  # Extraer la extensión del archivo
    file_key = f"{document_number}_{current_time}.{file_extension}"

    contents = await file.read()

    try:
        # Subir el archivo a S3 usando el nombre generado
        file_url = await s3_upload(contents, file_key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al subir a S3: {str(e)}"
        )

    if not file_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error: No se obtuvo URL del archivo subido"
        )

    return {"message": "Documento subido exitosamente", "document_url": file_url}
