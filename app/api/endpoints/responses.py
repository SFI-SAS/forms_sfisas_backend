
import json
import logging
import os
import uuid
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.api.controllers.mail import send_reconsideration_email
from app.crud import create_answer_in_db, generate_unique_serial, post_create_response, process_responses_with_history
from app.database import get_db
from app.schemas import AnswerHistoryChangeSchema, AnswerHistoryCreate, FileSerialCreate, FilteredAnswersResponse, PostCreate, QuestionAnswerDetailSchema, QuestionFilterConditionCreate, ResponseItem, ResponseWithAnswersAndHistorySchema, UpdateAnswerText, UpdateAnswertHistory
from app.models import Answer, AnswerFileSerial, AnswerHistory, ApprovalStatus, Form, FormApproval, FormQuestion, Question, QuestionFilterCondition, QuestionTableRelation, Response, ResponseApproval, User, UserType
from app.core.security import get_current_user
from typing import Dict
from sqlalchemy import delete

router = APIRouter()

from fastapi import Body


def extract_repeated_id(responses: List[ResponseItem]) -> Optional[str]:
    """
    Extrae el primer repeated_id no nulo de la lista de responses.
    """
    for r in responses:
        if r.repeated_id is not None and r.repeated_id.strip() != "":
            return r.repeated_id
    return None

@router.post("/save-response/{form_id}")
def save_response(
    form_id: int,
    responses: List[ResponseItem] = Body(...),
    mode: str = Query("online", enum=["online", "offline"]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to respond"
        )
    
    # Imprimir para debug el repeated_id recibido en cada respuesta
    for r in responses:
        logging.info(f"Repeated_id recibido: '{r.repeated_id}' (length: {len(r.repeated_id) if r.repeated_id else 0})")

    repeated_id = extract_repeated_id(responses)
    
    logging.info(f"Repeated_id extraído para guardar: '{repeated_id}' (length: {len(repeated_id) if repeated_id else 0})")

    return post_create_response(db, form_id, current_user.id, mode, repeated_id)

@router.post("/save-answers/")  
async def create_answer(
    answer: PostCreate, 
    request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    else: 
        new_answer = await create_answer_in_db(answer, db, current_user, request)
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


@router.put("/set_reconsideration/{response_id}")
def set_reconsideration_true(response_id: int, mensaje_reconsideracion: str, db: Session = Depends(get_db)):
    try:
        # Buscar la respuesta por ID
        response = db.query(Response).filter(Response.id == response_id).first()
        if not response:
            raise HTTPException(status_code=404, detail="Respuesta no encontrada")
        
        # Obtener información del usuario que solicita reconsideración
        usuario_solicita = db.query(User).filter(User.id == response.user_id).first()
        if not usuario_solicita:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        # Obtener información del formulario
        formato = db.query(Form).filter(Form.id == response.form_id).first()
        if not formato:
            raise HTTPException(status_code=404, detail="Formulario no encontrado")
        
        # Obtener el creador del formulario
        creador_formato = db.query(User).filter(User.id == formato.user_id).first()
        
        # Obtener todas las aprobaciones de esta respuesta
        approvals = db.query(ResponseApproval).filter(ResponseApproval.response_id == response_id).all()
        if not approvals:
            raise HTTPException(status_code=404, detail="No se encontraron aprobaciones para esta respuesta")
        
        # Buscar el aprobador que rechazó
        aprobador_que_rechazo = None
        for approval in approvals:
            if approval.status == ApprovalStatus.rechazado:  # Asumiendo que tienes un enum ApprovalStatus
                aprobador_rechazo_user = db.query(User).filter(User.id == approval.user_id).first()
                if aprobador_rechazo_user:
                    aprobador_que_rechazo = {
                        'nombre': aprobador_rechazo_user.name,
                        'email': aprobador_rechazo_user.email,
                        'mensaje': approval.message,
                        'reviewed_at': approval.reviewed_at.strftime("%d/%m/%Y %H:%M") if approval.reviewed_at else 'No disponible'
                    }
                break
        
        # Obtener todos los aprobadores del formulario
        form_approvals = db.query(FormApproval).filter(
            FormApproval.form_id == response.form_id,
            FormApproval.is_active == True
        ).order_by(FormApproval.sequence_number).all()
        
        # Preparar información de todos los aprobadores
        todos_los_aprobadores = []
        aprobadores_emails = []
        
        for form_approval in form_approvals:
            aprobador_user = db.query(User).filter(User.id == form_approval.user_id).first()
            if aprobador_user:
                # Buscar el estado actual de este aprobador para esta respuesta
                current_approval = db.query(ResponseApproval).filter(
                    ResponseApproval.response_id == response_id,
                    ResponseApproval.user_id == form_approval.user_id
                ).first()
                
                todos_los_aprobadores.append({
                    'secuencia': form_approval.sequence_number,
                    'nombre': aprobador_user.name,
                    'email': aprobador_user.email,
                    'status': current_approval.status if current_approval else 'pending',
                    'mensaje': current_approval.message if current_approval else 'Sin mensaje',
                    'reviewed_at': current_approval.reviewed_at.strftime("%d/%m/%Y %H:%M") if current_approval and current_approval.reviewed_at else 'No disponible'
                })
                
                aprobadores_emails.append({
                    'email': aprobador_user.email,
                    'nombre': aprobador_user.name
                })
        
        # Preparar información del formato
        formato_info = {
            'titulo': formato.title,
            'descripcion': formato.description,
            'creado_por': {
                'nombre': creador_formato.name if creador_formato else 'No disponible',
                'email': creador_formato.email if creador_formato else 'No disponible'
            }
        }
        
        # Preparar información del usuario que solicita
        usuario_info = {
            'nombre': usuario_solicita.name,
            'email': usuario_solicita.email,
            'telefono': usuario_solicita.telephone,
            'num_documento': usuario_solicita.num_document
        }
        
        # Actualizar el campo reconsideration_requested
        for approval in approvals:
            approval.reconsideration_requested = True
        
        db.commit()
        
        # Enviar correos a todos los aprobadores
        correos_enviados = 0
        for aprobador in aprobadores_emails:
            if send_reconsideration_email(
                to_email=aprobador['email'],
                to_name=aprobador['nombre'],
                formato=formato_info,
                usuario_solicita=usuario_info,
                mensaje_reconsideracion=mensaje_reconsideracion,
                aprobador_que_rechazo=aprobador_que_rechazo,
                todos_los_aprobadores=todos_los_aprobadores
            ):
                correos_enviados += 1
        
        return {
            "message": "Reconsideración solicitada exitosamente",
            "correos_enviados": correos_enviados,
            "total_aprobadores": len(aprobadores_emails),
            "aprobaciones_actualizadas": len(approvals)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al procesar la reconsideración: {str(e)}")
    
    
@router.post("/answer-history", status_code=201)
def create_answer_history(data: AnswerHistoryCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    else: 
        new_history = AnswerHistory(
            response_id=data.response_id,
            previous_answer_id=data.previous_answer_id,
            current_answer_id=data.current_answer_id
        )

        db.add(new_history)
        db.commit()
        db.refresh(new_history)

        return {"message": "Historial de respuesta guardado", "id": new_history.id}

from sqlalchemy import select


@router.post("/create-answers", status_code=status.HTTP_201_CREATED)
async def create_answers(
    response_id: int,
    question_id: int,
    answer_text: Optional[str] = None,
    file_path: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Registrar un nuevo Answer"""
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    # Validar que existe el response_id
    if not db.query(Response).filter(Response.id == response_id).first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response with id {response_id} not found"
        )
    
    # Validar que existe el question_id
    if not db.query(Question).filter(Question.id == question_id).first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with id {question_id} not found"
        )
    
    try:
        new_answer = Answer(
            response_id=response_id,
            question_id=question_id,
            answer_text=answer_text,
            file_path=file_path
        )
        
        db.add(new_answer)
        db.commit()
        db.refresh(new_answer)
        
        return {"message": "Answer created successfully", "id": new_answer.id}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating answer: {str(e)}"
        )
@router.put("/update_answer_text/")
def update_answer_text(data: UpdateAnswertHistory, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    answer = db.query(Answer).filter(Answer.id == data.id_answer).first()
    
    if not answer:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")

    answer.answer_text = data.answer_text
    db.commit()
    db.refresh(answer)

    return {
        "message": "Respuesta actualizada correctamente",
        "id_answer": answer.id,
        "answer_text": answer.answer_text
    }

@router.get("/{response_id}/answers_and_history", response_model=ResponseWithAnswersAndHistorySchema)
async def get_response_with_complete_answers_and_history(
    response_id: int,
    db: Session = Depends(get_db),
):
    """
    Obtiene todas las respuestas actuales y el historial de un response específico
    """

    # Buscar el response con sus respuestas actuales
    response = db.query(Response).options(
        joinedload(Response.answers).joinedload(Answer.question)
    ).filter(Response.id == response_id).first()

    if not response:
        raise HTTPException(status_code=404, detail="Response not found")

    # Obtener el historial de respuestas para este response
    answer_history = db.query(AnswerHistory).filter(
        AnswerHistory.response_id == response_id
    ).order_by(AnswerHistory.updated_at.desc()).all()

    # Obtener todas las respuestas mencionadas en el historial
    all_answer_ids_in_history = set()
    replaced_answer_ids = set()
    for hist in answer_history:
        if hist.previous_answer_id:
            all_answer_ids_in_history.add(hist.previous_answer_id)
            replaced_answer_ids.add(hist.previous_answer_id)
        all_answer_ids_in_history.add(hist.current_answer_id)

    # Obtener todas las respuestas del historial con sus preguntas
    historical_answers_with_questions = {}
    if all_answer_ids_in_history:
        historical_answers = db.query(Answer).options(
            joinedload(Answer.question)
        ).filter(Answer.id.in_(all_answer_ids_in_history)).all()

        for answer in historical_answers:
            historical_answers_with_questions[answer.id] = answer

    # Construir las respuestas actuales (excluyendo las reemplazadas)
    current_answers_list = []
    for answer in response.answers:
        if answer.id not in replaced_answer_ids:
            current_answers_list.append(QuestionAnswerDetailSchema(
                id=answer.id,
                question_id=answer.question_id,
                question_text=answer.question.question_text,
                answer_text=answer.answer_text,
                file_path=answer.file_path
            ))

    # Construir el historial de cambios
    history_changes_list = []
    for history_item in answer_history:
        previous_answer_detail = None
        if history_item.previous_answer_id and history_item.previous_answer_id in historical_answers_with_questions:
            prev_answer = historical_answers_with_questions[history_item.previous_answer_id]
            previous_answer_detail = QuestionAnswerDetailSchema(
                id=prev_answer.id,
                question_id=prev_answer.question_id,
                question_text=prev_answer.question.question_text,
                answer_text=prev_answer.answer_text,
                file_path=prev_answer.file_path
            )

        current_answer_detail = None
        if history_item.current_answer_id in historical_answers_with_questions:
            curr_answer = historical_answers_with_questions[history_item.current_answer_id]
            current_answer_detail = QuestionAnswerDetailSchema(
                id=curr_answer.id,
                question_id=curr_answer.question_id,
                question_text=curr_answer.question.question_text,
                answer_text=curr_answer.answer_text,
                file_path=curr_answer.file_path
            )

        # Solo agregar si encontramos la respuesta actual
        if current_answer_detail:
            history_changes_list.append(AnswerHistoryChangeSchema(
                id=history_item.id,
                previous_answer_id=history_item.previous_answer_id,
                current_answer_id=history_item.current_answer_id,
                updated_at=history_item.updated_at,
                previous_answer=previous_answer_detail,
                current_answer=current_answer_detail
            ))

    return ResponseWithAnswersAndHistorySchema(
        id=response.id,
        form_id=response.form_id,
        user_id=response.user_id,
        mode=response.mode,
        mode_sequence=response.mode_sequence,
        repeated_id=response.repeated_id,
        submitted_at=response.submitted_at,
        current_answers=current_answers_list,
        answer_history=history_changes_list
    )

@router.get("/get_responses/")
def get_responses_with_answers(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene todas las respuestas completadas por el usuario autenticado para un formulario específico,
    incluyendo sus respuestas, aprobaciones, estado de revisión y historial de cambios.
     
    Args:
        form_id (int): ID del formulario del cual se desean obtener las respuestas.
        db (Session): Sesión activa de la base de datos.
        current_user (User): Usuario autenticado.
     
    Returns:
        List[dict]: Lista de respuestas con sus respectivos detalles de aprobación y respuestas a preguntas,
                   incluyendo historial de cambios cuando aplique.
     
    Raises:
        HTTPException: 403 si no hay un usuario autenticado.
        HTTPException: 404 si no se encuentran respuestas.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    # Obtener respuestas principales
    stmt = (
        select(Response)
        .where(Response.form_id == form_id, Response.user_id == current_user.id)
        .options(
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.approvals).joinedload(ResponseApproval.user)
        )
    )
    
    responses = db.execute(stmt).unique().scalars().all()

    if not responses:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    # Procesar respuestas con historial
    result = process_responses_with_history(responses, db)

    return result


@router.delete("/responses_delete/{response_id}")
async def delete_response(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Elimina una respuesta y todas sus relaciones asociadas.
    
    Args:
        response_id: ID de la respuesta a eliminar
        db: Sesión de base de datos
        
    Returns:
        Dict con mensaje de confirmación
        
    Raises:
        HTTPException: Si la respuesta no existe o hay error en la eliminación
    """
    try:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to access completed forms",
            )
            # Verificar que la respuesta existe
        response = db.query(Response).filter(Response.id == response_id).first()
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Response with id {response_id} not found"
            )
        
        # 1. Obtener IDs de las respuestas para eliminar file_serials
        answer_ids = db.query(Answer.id).filter(Answer.response_id == response_id).all()
        answer_ids_list = [answer.id for answer in answer_ids]
        
        # 2. Eliminar AnswerFileSerial relacionados
        if answer_ids_list:
            db.execute(
                delete(AnswerFileSerial).where(
                    AnswerFileSerial.answer_id.in_(answer_ids_list)
                )
            )
        
        # 3. Eliminar AnswerHistory relacionados
        db.execute(
            delete(AnswerHistory).where(AnswerHistory.response_id == response_id)
        )
        
        # 4. Eliminar todas las respuestas (Answer) asociadas
        db.execute(
            delete(Answer).where(Answer.response_id == response_id)
        )
        
        # 5. Eliminar ResponseApproval si existe
        try:
            db.execute(
                delete(ResponseApproval).where(ResponseApproval.response_id == response_id)
            )
        except Exception:
            # Si la tabla ResponseApproval no existe, continuamos
            pass
        
        # 6. Finalmente eliminar la Response
        db.execute(
            delete(Response).where(Response.id == response_id)
        )
        
        # Confirmar todos los cambios
        db.commit()
        
        return {"message": f"Response {response_id} and all related data deleted successfully"}
        
    except HTTPException:
        # Re-lanzar HTTPExceptions
        db.rollback()
        raise
    except Exception as e:
        # Rollback en caso de error
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting response: {str(e)}"
        )