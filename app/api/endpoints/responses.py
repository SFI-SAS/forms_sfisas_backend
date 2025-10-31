
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
from app.crud import create_answer_in_db, encrypt_object, generate_unique_serial, post_create_response, process_responses_with_history, send_form_action_emails, send_mails_to_next_supporters
from app.database import get_db
from app.schemas import AnswerHistoryChangeSchema, AnswerHistoryCreate, FileSerialCreate, FilteredAnswersResponse, PostCreate, QuestionAnswerDetailSchema, QuestionFilterConditionCreate, RegisfacialAnswerResponse, ResponseItem, ResponseWithAnswersAndHistorySchema, UpdateAnswerText, UpdateAnswertHistory
from app.models import Answer, AnswerFileSerial, AnswerHistory, ApprovalStatus, Form, FormApproval, FormQuestion, FormatType, Question, QuestionFilterCondition, QuestionTableRelation, QuestionType, Response, ResponseApproval, ResponseApprovalRequirement, ResponseStatus, User, UserType
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
    action: str = Query("send", enum=["send", "send_and_close"]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission")

    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    # Determinar estado y si crear aprobaciones
    if form.format_type == FormatType.cerrado:
        # Formato cerrado siempre se envía para aprobación
        status = ResponseStatus.submitted
        create_approvals = True
    else:
        # Formato abierto/semi_abierto depende de la acción
        if action == "send_and_close":
            status = ResponseStatus.submitted
            create_approvals = True
        else:  # action == "send"
            status = ResponseStatus.draft
            create_approvals = False

    repeated_id = extract_repeated_id(responses)
    return post_create_response(db, form_id, current_user.id, mode, repeated_id, create_approvals, status)


@router.post("/save-answers/")
async def create_answer(
        request: Request,
    answer: PostCreate,
    action: str = Query("send", enum=["send", "send_and_close"]),  # NUEVO

    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    LÓGICA SIMPLE:
    - action="send": Guarda respuestas SIN enviar emails
    - action="send_and_close": Guarda respuestas Y envía emails si corresponde
    - Para formato cerrado: IGNORA action, siempre envía emails
    """
    if current_user == None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission")

    # Obtener formato del formulario
    response = db.query(Response).filter(Response.id == answer.response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
    
    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    # REGLA SIMPLE:
    # - Cerrado = siempre enviar emails
    # - Abierto/Semi_abierto = enviar solo si action="send_and_close"
    send_emails = (form.format_type == FormatType.cerrado) or (action == "send_and_close")

    new_answer = await create_answer_in_db(answer, db, current_user, request, send_emails)
    return {"message": "Answer created", "answer": new_answer}


@router.post("/close-response/{response_id}")
async def close_response(
    response_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission")

    # Verificar que la respuesta existe, es del usuario Y está en draft
    response = db.query(Response).filter(
        Response.id == response_id, 
        Response.user_id == current_user.id,
        Response.status == ResponseStatus.draft  # NUEVA VALIDACIÓN
    ).first()
    
    if not response:
        raise HTTPException(
            status_code=404, 
            detail="Response not found or already submitted"
        )

    # Verificar el formato
    form = db.query(Form).filter(Form.id == response.form_id).first()
    if form.format_type == FormatType.cerrado:
        raise HTTPException(
            status_code=400, 
            detail="Closed formats are automatically submitted"
        )

    # Cambiar estado a submitted
    response.status = ResponseStatus.submitted
    
    # Crear aprobaciones
    form_approvals = db.query(FormApproval).filter(
        FormApproval.form_id == form.id, 
        FormApproval.is_active == True
    ).all()

    for approver in form_approvals:
        response_approval = ResponseApproval(
            response_id=response_id,
            user_id=approver.user_id,
            sequence_number=approver.sequence_number,
            is_mandatory=approver.is_mandatory,
            status=ApprovalStatus.pendiente,
        )
        db.add(response_approval)

    db.commit()

    # Enviar notificaciones
    send_mails_to_next_supporters(response_id, db)
    await send_form_action_emails(form.id, db, current_user, request)

    return {
        "message": "Response submitted for approval successfully", 
        "response_id": response_id,
        "new_status": "submitted"
    }

UPLOAD_FOLDER = "./documents"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@router.post("/upload-file/")
async def upload_file(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    """
    Sube un archivo al servidor, generando un nombre único.

    Este endpoint permite a un usuario autenticado subir un archivo (por ejemplo, PDF, imagen, etc.)
    al servidor. El archivo se guarda en la carpeta predefinida `UPLOAD_FOLDER` con un nombre
    único generado con `uuid`.

    Requisitos:
    -----------
    - El usuario debe estar autenticado.
    - El archivo debe ser enviado como `form-data` con la clave `file`.

    Parámetros:
    -----------
    file : UploadFile (obligatorio)
        Archivo a subir (formato `multipart/form-data`).
    
    current_user : User
        Usuario autenticado extraído del token JWT.

    Retorna:
    --------
    JSON con:
    - `message`: confirmación del éxito.
    - `file_name`: nombre único generado del archivo guardado.

    Errores:
    --------
    - 403: Si el usuario no está autenticado.
    - 500: Si ocurre un error al guardar el archivo.
    """
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
    """
    Descarga un archivo previamente subido al servidor.

    Este endpoint permite a un usuario autenticado descargar un archivo que fue previamente
    subido y almacenado en la carpeta `UPLOAD_FOLDER`.

    Parámetros:
    -----------
    file_name : str
        Nombre del archivo a descargar (incluye extensión).

    current_user : User
        Usuario autenticado obtenido desde el token JWT.

    Retorna:
    --------
    FileResponse:
        Archivo descargado como `application/octet-stream`.

    Errores:
    --------
    - 403: Si el usuario no está autenticado.
    - 404: Si el archivo no existe en la ruta especificada.
    """
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
    """
    Obtiene las columnas de una tabla específica de la base de datos.

    Este endpoint inspecciona dinámicamente la estructura de una tabla en la base de datos
    y devuelve una lista con los nombres de sus columnas, excluyendo columnas como `created_at`.

    También permite definir manualmente columnas para ciertas tablas como `users`.

    Parámetros:
    -----------
    table_name : str
        Nombre de la tabla a consultar.

    db : Session
        Sesión activa de base de datos inyectada mediante dependencia.

    Retorna:
    --------
    dict:
        Diccionario con la clave `columns` y una lista de nombres de columnas.

    Lanza:
    ------
    HTTPException:
        - 404: Si la tabla no existe o no se puede inspeccionar.
    """
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
    
    """
    Actualiza el texto (`answer_text`) de una respuesta específica en la base de datos.

    Este endpoint permite a un usuario autenticado modificar el contenido de una respuesta 
    previamente registrada, validando primero que la respuesta exista.

    Parámetros:
    -----------
    payload : UpdateAnswerText
        Objeto que contiene el `id` de la respuesta a actualizar y el nuevo `answer_text`.

    db : Session
        Sesión activa de base de datos inyectada mediante dependencia.

    current_user : User
        Usuario autenticado extraído del token JWT.

    Retorna:
    --------
    dict:
        Diccionario con mensaje de éxito y el ID de la respuesta actualizada.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
        - 404: Si la respuesta con el ID dado no existe.
    """
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
    """
    Crea un nuevo serial asociado a una respuesta (`Answer`) existente.

    Este endpoint permite registrar un serial relacionado con una respuesta específica. 
    Se valida primero que la respuesta exista antes de crear el registro.

    Parámetros:
    -----------
    data : FileSerialCreate
        Objeto que contiene:
        - `answer_id`: ID de la respuesta asociada.
        - `serial`: Serial a registrar.

    db : Session
        Sesión activa de la base de datos proporcionada mediante dependencia.

    Retorna:
    --------
    dict:
        Mensaje de confirmación junto con el ID del nuevo serial creado y su valor.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentra la respuesta asociada (`Answer`).
    """
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
    """
    Genera un serial aleatorio único que no exista previamente en la base de datos.

    Este endpoint utiliza letras mayúsculas y dígitos para construir un serial de longitud fija (por defecto 5).
    Garantiza unicidad antes de retornarlo.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos proporcionada por la dependencia.

    Retorna:
    --------
    dict:
        - `serial`: El serial generado que no existe previamente en la base de datos.
    """
    serial = generate_unique_serial(db)
    return {"serial": serial}

@router.post("/create_question_filter_condition/", summary="Crear condición de filtrado de preguntas")
def create_question_filter_condition(
    condition_data: QuestionFilterConditionCreate,
    db: Session = Depends(get_db)
):
    """
    Crea una nueva condición de filtrado para una pregunta en un formulario.

    Este endpoint permite registrar una regla que evalúa una condición sobre una pregunta determinada
    y devuelve un subconjunto de respuestas basado en dicha lógica.

    La condición se define con base en:
    - El formulario (`form_id`)
    - La pregunta a filtrar (`filtered_question_id`)
    - La pregunta origen (`source_question_id`)
    - La pregunta que define la condición (`condition_question_id`)
    - El operador lógico (`operator`) entre el valor esperado y la respuesta
    - El valor esperado (`expected_value`)

    Validaciones:
    -------------
    - Verifica que no exista previamente una condición con los mismos parámetros antes de crearla.

    Parámetros:
    -----------
    - condition_data: `QuestionFilterConditionCreate`
        Objeto con los datos requeridos para crear la condición.
    - db: `Session`
        Sesión activa de la base de datos (inyectada automáticamente por FastAPI).

    Retorna:
    --------
    dict:
        - `message`: Mensaje de éxito.
        - `id`: ID de la condición recién creada.

    Errores:
    --------
    - 400: Si ya existe una condición con los mismos campos.
    """
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
    """
    Retorna una lista de respuestas válidas filtradas según la condición asociada a la pregunta.
    
    - **filtered_question_id**: ID de la pregunta con condición de filtro.
    - **Returns**: Lista de objetos con respuestas únicas válidas (sin nulos).
    - **Raises**: HTTP 404 si no existe la condición.
    """
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
    """
    Retorna todos los formularios que contienen la pregunta especificada, incluyendo
    sus preguntas asociadas y respuestas únicas.

    Parámetros:
    - question_id: ID de la pregunta base.

    Retorna:
    - Lista de formularios con sus preguntas y respuestas correspondientes.
    """
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
    """
    Marca una respuesta como reconsiderada, notifica a todos los aprobadores
    y envía un correo con los detalles de la solicitud.

    Parámetros:
    - response_id: ID de la respuesta rechazada.
    - mensaje_reconsideracion: Mensaje que justifica la solicitud de reconsideración.

    Retorna:
    - Detalle del proceso de notificación y actualización de aprobaciones.
    """
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
    """
    Crea un registro de historial que documenta el cambio de una respuesta anterior a una nueva.

    Parámetros:
    - data: Objeto con los IDs de la respuesta actual, anterior y del formulario.
    - db: Sesión de base de datos inyectada automáticamente.
    - current_user: Usuario autenticado realizando la acción.

    Retorna:
    - Mensaje de éxito y el ID del historial creado.
    """
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
    """
    Crea una nueva respuesta (`Answer`) asociada a una pregunta específica dentro de una respuesta general (`Response`).

    Parámetros:
    - response_id: ID de la respuesta general a la que pertenece esta respuesta.
    - question_id: ID de la pregunta que se está respondiendo.
    - answer_text: Texto de la respuesta (opcional).
    - file_path: Ruta del archivo adjunto, si aplica (opcional).
    - db: Sesión de base de datos inyectada automáticamente.
    - current_user: Usuario autenticado que realiza la operación.

    Retorna:
    - Un diccionario con mensaje de éxito e ID del nuevo registro de respuesta.
    """
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
    """
    Actualiza el contenido de texto (`answer_text`) de una respuesta existente.

    Parámetros:
    - data: Objeto con el ID de la respuesta y el nuevo texto (modelo `UpdateAnswertHistory`).
    - db: Sesión de base de datos inyectada automáticamente.
    - current_user: Usuario autenticado que realiza la operación.

    Retorna:
    - Un diccionario con un mensaje de éxito, el ID de la respuesta y el texto actualizado.

    Errores:
    - 403: Si el usuario no está autenticado.
    - 404: Si no se encuentra la respuesta con el ID especificado.
    """
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
    Obtiene todas las respuestas actuales y el historial de cambios de un `response` específico.

    Este endpoint devuelve:
    - Las respuestas actuales asociadas al `response` (excluyendo aquellas que han sido reemplazadas).
    - El historial de cambios, incluyendo respuestas anteriores y actuales relacionadas.

    Parámetros:
    - response_id (int): ID del `response` a consultar.
    - db (Session): Sesión de base de datos proporcionada por la dependencia.

    Retorna:
    - Un esquema con información del response, sus respuestas activas y su historial de cambios.

    Errores:
    - 404: Si el `response` no existe.
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
    
@router.get("/get_responses/all")
def get_all_user_responses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene TODAS las respuestas completadas por el usuario autenticado en TODOS sus formularios,
    incluyendo respuestas, aprobaciones, estado de revisión y historial de cambios.
     
    Args:
        db (Session): Sesión activa de la base de datos.
        current_user (User): Usuario autenticado.
     
    Returns:
        dict: Diccionario con:
            - total_forms (int): Número total de formularios con respuestas
            - total_responses (int): Número total de respuestas
            - forms (List[dict]): Lista de formularios con sus respuestas, cada uno contiene:
                - form_id (int): ID del formulario
                - form_title (str): Título del formulario
                - form_description (str): Descripción del formulario
                - response_count (int): Cantidad de respuestas en este formulario
                - responses (List[dict]): Lista de respuestas con historial
     
    Raises:
        HTTPException: 403 si no hay un usuario autenticado.
        HTTPException: 404 si no se encuentran respuestas.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )

    # Obtener todas las respuestas del usuario con sus formularios
    stmt = (
        select(Response)
        .where(Response.user_id == current_user.id)
        .options(
            joinedload(Response.form),
            joinedload(Response.answers).joinedload(Answer.question),
            joinedload(Response.approvals).joinedload(ResponseApproval.user)
        )
    )
    
    all_responses = db.execute(stmt).unique().scalars().all()

    if not all_responses:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    # Agrupar respuestas por formulario
    forms_dict = {}
    
    for response in all_responses:
        form_id = response.form_id
        
        if form_id not in forms_dict:
            forms_dict[form_id] = {
                "form_id": form_id,
                "form_title": response.form.title if response.form else "Sin título",
                "form_description": response.form.description if response.form else "",
                "format_type": response.form.format_type.name if response.form and response.form.format_type else None,
                "responses": []
            }
        
        forms_dict[form_id]["responses"].append(response)
    
    # Procesar cada formulario con sus respuestas
    result_forms = []
    total_responses = 0
    
    for form_id, form_data in forms_dict.items():
        # Procesar respuestas con historial
        processed_responses = process_responses_with_history(form_data["responses"], db)
        
        result_forms.append({
            "form_id": form_data["form_id"],
            "form_title": form_data["form_title"],
            "form_description": form_data["form_description"],
            "format_type": form_data["format_type"],
            "response_count": len(processed_responses),
            "responses": processed_responses
        })
        
        total_responses += len(processed_responses)
    
    # Ordenar formularios por ID (o por título si lo prefieres)
    result_forms.sort(key=lambda x: x["form_id"])
    
    return {
        "total_forms": len(result_forms),
        "total_responses": total_responses,
        "forms": result_forms
    }

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

        # 1. Obtener IDs de las respuestas (Answer)
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

        # 4. Eliminar Answer relacionados
        db.execute(
            delete(Answer).where(Answer.response_id == response_id)
        )

        # 5. Eliminar registros en ResponseApprovalRequirements
        db.execute(
            delete(ResponseApprovalRequirement).where(
                (ResponseApprovalRequirement.response_id == response_id) |
                (ResponseApprovalRequirement.fulfilling_response_id == response_id)
            )
        )

        # 6. Eliminar registros en ResponseApproval
        db.execute(
            delete(ResponseApproval).where(ResponseApproval.response_id == response_id)
        )

        # 7. Finalmente eliminar la Response
        db.execute(
            delete(Response).where(Response.id == response_id)
        )

        # Confirmar cambios
        db.commit()

        return {"message": f"Response {response_id} and all related data deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting response: {str(e)}"
        )

        
        

@router.put("/approvals/{response_id}/reset-reconsideration")
def reset_reconsideration_requested(
    response_id: int,  # Cambiar de approval_id a response_id
    db: Session = Depends(get_db)
):
    # Buscar la aprobación por response_id
    approval = db.query(ResponseApproval).filter(
        ResponseApproval.response_id == response_id
    ).first()
    
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    approval.reconsideration_requested = None
    db.commit()
    
    return {"message": "Reconsideration field set to null", "id": approval.id}


@router.get("/answers/regisfacial", response_model=List[RegisfacialAnswerResponse])
async def get_regisfacial_answers(db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    """
    Obtiene todas las respuestas de preguntas tipo 'regisfacial' sin duplicar person_id
    y genera un hash encriptado con la información específica
    """
    try:
        # Obtener todas las respuestas de preguntas tipo regisfacial
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get categories"
            )
        results = (
            db.query(
                Answer.id,
                Answer.response_id,
                Answer.question_id,
                Question.question_text,
                Answer.answer_text,
                Response.user_id,
                User.name.label('user_name'),
                User.email.label('user_email'),
                Response.submitted_at
            )
            .join(Question, Answer.question_id == Question.id)
            .join(Response, Answer.response_id == Response.id)
            .join(User, Response.user_id == User.id)
            .filter(Question.question_type == QuestionType.regisfacial)
            .filter(Answer.answer_text.isnot(None))
            .order_by(Answer.id)
            .all()
        )
        
        # Filtrar por person_id único
        seen_person_ids = set()
        unique_results = []
        
        for result in results:
            try:
                face_data = json.loads(result.answer_text)
                person_id = face_data.get('faceData', {}).get('person_id')
                
                if person_id and person_id not in seen_person_ids:
                    seen_person_ids.add(person_id)
                    
                    # Crear el objeto con los datos específicos para encriptar
                    data_to_encrypt = {
                        "id": result.id,
                        "question_id": result.question_id,
                        "user_name": result.user_name,
                        "user_email": result.user_email,
                        "submitted_at": result.submitted_at.isoformat() if result.submitted_at else ""
                    }
                    
                    # Encriptar los datos
                    encrypted_hash = encrypt_object(data_to_encrypt)
                    
                    unique_results.append(RegisfacialAnswerResponse(
                        answer_text=result.answer_text,
                        encrypted_hash=encrypted_hash
                    ))
            except (json.JSONDecodeError, KeyError):
                continue
                
        return unique_results
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error al obtener las respuestas: {str(e)}"
        )