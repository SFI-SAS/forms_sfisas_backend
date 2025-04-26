
import os
import uuid
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from typing import List
from app.crud import create_answer_in_db, generate_unique_serial, post_create_response
from app.database import get_db
from app.schemas import FileSerialCreate, PostCreate, UpdateAnswerText
from app.models import Answer, AnswerFileSerial, User, UserType
from app.core.security import get_current_user


router = APIRouter()

        
@router.post("/save-response/{form_id}")
def save_response(
    form_id: int,
    mode: str = Query("online", enum=["online", "offline"]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to respond"
        )

    return post_create_response(db, form_id, current_user.id, mode)

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
async def upload_file(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    try:
        if current_user == None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get all questions"
            )
        else: 
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


@router.get("/download-file/{file_name}")
async def download_file(file_name: str, current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(   
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
            )
    else: 
        file_path = os.path.join(UPLOAD_FOLDER, file_name)
        if os.path.exists(file_path):
            return FileResponse(path=file_path, filename=file_name, media_type='application/octet-stream')
        else:
            raise HTTPException(status_code=404, detail="File not found")


@router.get("/db/columns/{table_name}")
def get_table_columns(table_name: str, db: Session = Depends(get_db)):
    inspector = inspect(db.bind)

    # Mapear nombre de tabla en plural a nombre de tabla en base de datos si es necesario
    special_columns = {
        "users": ["num_document", "name", "email", "telephone"]
    }

    # Si la tabla es "users", retornar solo los campos definidos manualmente
    if table_name in special_columns:
        return {"columns": special_columns[table_name]}

    # Obtener columnas desde la base de datos
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Tabla '{table_name}' no encontrada")

    column_names = [col["name"] for col in columns if col["name"] != "created_at"]

    return {"columns": column_names}


@router.put("/answers/update-answer-text")
def update_answer_text(payload: UpdateAnswerText, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(   
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
            )
    else: 
        answer = db.query(Answer).filter(Answer.id == payload.id).first()

        if not answer:
            raise HTTPException(status_code=404, detail="Respuesta no encontrada")

        answer.answer_text = payload.answer_text
        db.commit()
        db.refresh(answer)

        return {"message": "Respuesta actualiszada correctamente", "answer_id": answer.id}
    
    
    
@router.post("/file-serials/")
def create_file_serial(data: FileSerialCreate, db: Session = Depends(get_db)):
    # Verificamos si el answer existe
    answer = db.query(Answer).filter(Answer.id == data.answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")

    # Creamos y guardamos el nuevo serial
    file_serial = AnswerFileSerial(answer_id=data.answer_id, serial=data.serial)
    db.add(file_serial)
    db.commit()
    db.refresh(file_serial)

    return {
        "message": "Serial saved successfully",
        "file_serial_id": file_serial.id,
        "serial": file_serial.serial
    }
    
@router.post("/file-serials/generate")
def generate_serial(db: Session = Depends(get_db)):
    serial = generate_unique_serial(db)
    return {"serial": serial}

