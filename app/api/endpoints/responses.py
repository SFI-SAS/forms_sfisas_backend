
import os
import uuid
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from typing import List
from app.crud import create_answer_in_db, generate_unique_serial, post_create_response
from app.database import get_db
from app.schemas import FileSerialCreate, FilteredAnswersResponse, PostCreate, QuestionFilterConditionCreate, UpdateAnswerText
from app.models import Answer, AnswerFileSerial, Form, FormQuestion, Question, QuestionFilterCondition, QuestionTableRelation, Response, User, UserType
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

@router.post("/create_question_filter_condition/", summary="Crear condición de filtrado de preguntas")
def create_question_filter_condition(
    condition_data: QuestionFilterConditionCreate,
    db: Session = Depends(get_db)
):
    # Verificar si ya existe una condición igual
    existing = db.query(QuestionFilterCondition).filter_by(
        form_id=condition_data.form_id,
        filtered_question_id=condition_data.filtered_question_id,
        source_question_id=condition_data.source_question_id,
        condition_question_id=condition_data.condition_question_id,
        expected_value=condition_data.expected_value,
        operator=condition_data.operator
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Condición ya existe")

    # Crear la condición
    new_condition = QuestionFilterCondition(
        form_id=condition_data.form_id,
        filtered_question_id=condition_data.filtered_question_id,
        source_question_id=condition_data.source_question_id,
        condition_question_id=condition_data.condition_question_id,
        expected_value=condition_data.expected_value,
        operator=condition_data.operator,
    )

    db.add(new_condition)
    db.commit()
    db.refresh(new_condition)

    return {
        "message": "Condición registrada exitosamente",
        "id": new_condition.id
    }


@router.get("/filtered_answers/{filtered_question_id}", response_model=List[FilteredAnswersResponse], summary="Obtener respuestas filtradas por condición")
def get_filtered_answers_endpoint(
    filtered_question_id: int,
    db: Session = Depends(get_db)
):
    condition = db.query(QuestionFilterCondition).filter_by(filtered_question_id=filtered_question_id).first()
    
    if not condition:
        raise HTTPException(status_code=404, detail="Condición de filtro no encontrada.")

    # Obtener todas las respuestas del formulario relacionado
    responses = db.query(Response).filter_by(form_id=condition.form_id).all()

    valid_answers = []

    for response in responses:
        answers_dict = {a.question_id: a.answer_text for a in response.answers}
        source_val = answers_dict.get(condition.source_question_id)
        condition_val = answers_dict.get(condition.condition_question_id)

        if condition.operator == '==':
            if condition_val == condition.expected_value:
                valid_answers.append(source_val)

        elif condition.operator == '!=':
            if condition_val != condition.expected_value:
                valid_answers.append(source_val)

        elif condition.operator == '>':
            if condition_val > condition.expected_value:
                valid_answers.append(source_val)

        elif condition.operator == '<':
            if condition_val < condition.expected_value:
                valid_answers.append(source_val)

        elif condition.operator == '>=':
            if condition_val >= condition.expected_value:
                valid_answers.append(source_val)

        elif condition.operator == '<=':
            if condition_val <= condition.expected_value:
                valid_answers.append(source_val)

    # Retorna respuestas únicas, eliminando nulos
    filtered = list(filter(None, set(valid_answers)))
    return [{"answer": val} for val in filtered]

@router.get("/forms/by_question/{question_id}")
def get_forms_questions_answers_by_question(question_id: int, db: Session = Depends(get_db)):
    try:
        # Buscar los IDs únicos de formularios que contienen la pregunta
        form_ids = (
            db.query(FormQuestion.form_id)
            .filter(FormQuestion.question_id == question_id)
            .distinct()
            .all()
        )
        unique_form_ids = [f[0] for f in form_ids]

        # Buscar formularios con esas IDs
        forms = db.query(Form).filter(Form.id.in_(unique_form_ids)).all()

        result = []
        for form in forms:
            # Obtener preguntas del formulario
            questions = (
                db.query(Question)
                .join(FormQuestion, FormQuestion.question_id == Question.id)
                .filter(FormQuestion.form_id == form.id)
                .all()
            )

            question_data = []
            for q in questions:
                # Obtener respuestas de esa pregunta
                answers = (
                    db.query(Answer)
                    .filter(Answer.question_id == q.id)
                    .all()
                )

                seen_texts = set()
                answer_data = []

                for ans in answers:
                    if ans.answer_text not in seen_texts:
                        seen_texts.add(ans.answer_text)
                        answer_data.append({
                            "id": ans.id,
                            "response_id": ans.response_id,
                            "answer_text": ans.answer_text,
                            "file_path": ans.file_path
                        })

                question_data.append({
                    "id": q.id,
                    "question_text": q.question_text,
                    "question_type": q.question_type.name,
                    "required": q.required,
                    "root": q.root,
                    "answers": answer_data
                })

            result.append({
                "form_id": form.id,
                "title": form.title,
                "questions": question_data
            })

        return {
            "message": "Formularios, preguntas y respuestas encontradas",
            "data": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
