from datetime import datetime
import json
import os
from pathlib import Path
import uuid
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import inspect
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Union
from app.api.controllers.mail import send_reconsideration_email
from app.crud import _extract_style_config, _serialize_answers, crear_palabras_clave_service, create_answer_in_db, create_bitacora_log_simple, encrypt_object, finalizar_conversacion_completa, generate_unique_serial, get_all_bitacora_eventos, get_all_bitacora_formatos, get_bitacora_eventos_by_user, get_palabras_clave_by_form, obtener_conversacion_completa, post_create_response, process_responses_with_history, reabrir_evento_service, response_bitacora_log_simple, send_form_action_emails, send_mails_to_next_supporters
from app.api.controllers.pdf_form_exporter import generate_form_pdf
from app.database import get_db
from app.schemas import UpdateMathOperationRequest, AnswerHistoryChangeSchema, AnswerHistoryCreate, BitacoraLogsSimpleAnswer, BitacoraLogsSimpleCreate, BitacoraResponse, FileSerialCreate, FilteredAnswersResponse, GetQuestionTextsRequest, GetQuestionTextsResponse, PalabrasClaveCreate, PalabrasClaveOut, PalabrasClaveUpdate, PostCreate, QuestionAnswerDetailSchema, QuestionFilterConditionCreate, QuestionTextValue, RegisfacialAnswerResponse, RelationOperationMathCreate, RelationOperationMathOut, ResponseItem, ResponseWithAnswersAndHistorySchema, UpdateAnswerText, UpdateAnswertHistory
from app.models import Answer, AnswerFileSerial, AnswerHistory, ApprovalStatus, BitacoraLogsSimple, ClasificacionBitacoraRelacion, Form, FormAnswerEditor, FormApproval, FormCategory, FormQuestion, FormatType, PalabrasClave, Question, QuestionFilterCondition, QuestionType, RelationBitacora, RelationOperationMath, Response, ResponseApproval, ResponseApprovalRequirement, ResponseStatus, User
from app.core.security import get_current_user
from typing import Dict
from sqlalchemy import delete, cast, Text as SAText
from app.redis_client import redis_client
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
async def save_response(  # 🆕 Ahora es async
    form_id: int,
    responses: List[ResponseItem] = Body(...),
    mode: str = Query("online", enum=["online", "offline"]),
    action: str = Query("send", enum=["send", "send_and_close"]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None  # 🆕 Agregar Request
):
    """
    Guarda las respuestas de un formulario.
    
    - Si es formato cerrado: siempre se envía para aprobación
    - Si es formato abierto/semi_abierto:
        - action="send": guarda como borrador (sin aprobación)
        - action="send_and_close": envía para aprobación o cierra directamente
    """
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission")

    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    # Determinar estado y si crear aprobaciones
    if form.format_type == FormatType.cerrado:
        # Formato cerrado siempre se envía para aprobación
        response_status = ResponseStatus.submitted
        create_approvals = True
    else:
        # Formato abierto/semi_abierto depende de la acción
        if action == "send_and_close":
            response_status = ResponseStatus.submitted
            create_approvals = True
        else:  # action == "send"
            response_status = ResponseStatus.draft
            create_approvals = False

    repeated_id = extract_repeated_id(responses)
    
    # 🆕 Ahora llamamos con await y pasamos current_user y request
    result = await post_create_response(
        db=db,
        form_id=form_id,
        user_id=current_user.id,
        current_user=current_user,  # 🆕 Pasar current_user
        request=request,  # 🆕 Pasar request
        mode=mode,
        repeated_id=repeated_id,
        create_approvals=create_approvals,
        status=response_status
    )
    
    return result

def _enforce_edit_permission(response: Response, form: Form, current_user: User, db: Session) -> None:
    """Valida si el usuario actual puede modificar answers de esta response.

    Reglas (en orden):
      1. Si response.status == 'approved' → 403 (inmutable tras aprobación).
      2. Si response.status == 'submitted' (edición real, no creación inicial):
         a. Solo el propietario puede editar (current_user.id == response.user_id).
         b. Si form.format_type == 'cerrado', se respeta answer_editors_mode:
              - 'none' → 403
              - 'all'  → permitido (propietario diligenciador)
              - 'list' → solo si está en form_answer_editors.
         c. Para abierto/semi_abierto se mantiene comportamiento legacy.
      3. Para status='draft' o 'rejected' → no se aplica este chequeo
         (flujos de creación inicial y reconsideración respectivamente).
    """
    if response.status == ResponseStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta respuesta ya fue aprobada y no puede editarse."
        )

    if response.status != ResponseStatus.submitted:
        return  # draft / rejected → sin restricción aquí

    # Solo el dueño puede pedir editar.
    if response.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el propietario de la respuesta puede editarla."
        )

    if form.format_type != FormatType.cerrado:
        return  # abierto/semi_abierto: comportamiento legacy

    mode = (form.answer_editors_mode or 'none').lower()
    if mode == 'all':
        return
    if mode == 'list':
        in_list = db.query(FormAnswerEditor.id).filter(
            FormAnswerEditor.form_id == form.id,
            FormAnswerEditor.user_id == current_user.id,
        ).first()
        if in_list:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tenés permiso para editar respuestas de este formato cerrado."
        )
    # mode == 'none' o cualquier otro
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="La edición de respuestas está deshabilitada en este formato cerrado."
    )


@router.post("/save-answers/")
async def create_answer(
    request: Request,
    payload: Union[PostCreate, List[PostCreate]] = Body(...),
    action: str = Query("send", enum=["send", "send_and_close"]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    LÓGICA SIMPLE:
    - action="send": Guarda respuestas SIN enviar emails
    - action="send_and_close": Guarda respuestas Y envía emails si corresponde
    - Para formato cerrado: IGNORA action, siempre envía emails
    """
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission")

    # ✅ CAMBIO 2: Convertir a lista si es objeto individual
    answers_list = payload if isinstance(payload, list) else [payload]

    # NOTA: /save-answers/ es el endpoint de CREACIÓN de answers. El frontend lo
    # invoca UNA VEZ POR ANSWER al diligenciar (incluyendo varias filas de
    # repeater con el mismo question_id), y en formato cerrado la response nace
    # 'submitted' antes de tener answers. Por eso NO se valida permiso de edición
    # acá: hacerlo bloqueaba el guardado (con cerrado daba 403 y solo se guardaba
    # el primer answer). El control de edición de respuestas YA EXISTENTES debe
    # vivir en los endpoints de edición real (update-answer / delete answers),
    # no en la creación. Ver _enforce_edit_permission().

    # Procesar cada respuesta
    for answer in answers_list:
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
                
                # Obtener relation_bitacora asociada al response
        relation_bitacora = db.query(RelationBitacora).filter(
            RelationBitacora.id_response == response.id
        ).first()

        if not relation_bitacora:
            raise HTTPException(
                status_code=404,
                detail="RelationBitacora not found for this response"
            )

        # Pasar id_relation_bitacora
        await create_answer_in_db(
            answer,
            db,
            current_user,
            request,
            send_emails,
            relation_bitacora.id  # 👈 NUEVO
        )

    # Retornar respuesta
    if isinstance(payload, list):
        return {"message": f"{len(answers_list)} answers created", "count": len(answers_list)}
    else:
        return {"message": "Answer created", "answer": payload}

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

    # SECURITY (fix #4 auditoría 28-may-2026): envolvemos el cambio de estado
    # + creación de ResponseApproval en try/except con rollback. Antes, si el
    # loop fallaba a la mitad, la sesión quedaba con cambios parciales (estado
    # ya seteado a submitted + aprobaciones huérfanas) y el rollback implícito
    # de FastAPI no siempre limpiaba bien — riesgo de respuesta en estado
    # inconsistente.
    try:
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
                # Hereda firm_mode y la pregunta regisfacial fuente de la plantilla
                # al momento de enviar. Fija las reglas para esta respuesta, aunque
                # luego el admin cambie el template del formato.
                firm_mode=getattr(approver, "firm_mode", "button") or "button",
                firm_source_question_id=getattr(approver, "firm_source_question_id", None),
            )
            db.add(response_approval)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al cerrar la respuesta. Cambios revertidos: {str(e)}"
        )

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
ALLOWED_UPLOAD_DIR = os.path.realpath(UPLOAD_FOLDER)

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
        if current_user is None:
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
async def download_file(
    file_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # 🔒 VALIDACIÓN DE PROPIEDAD: el archivo debe estar referenciado por alguna
    #    respuesta que el usuario actual tenga permiso de ver. Antes solo se
    #    validaba que el usuario estuviera autenticado, lo que permitía a
    #    cualquiera con un nombre de archivo descargar adjuntos ajenos.
    # ═══════════════════════════════════════════════════════════════════════════
    from app.core.permissions import can_user_view_response

    # Fuente 1: adjuntos de respuestas de formularios (tabla answers).
    answers_with_file = (
        db.query(Answer)
        .filter(
            (Answer.file_path == file_name)
            | (Answer.file_path.like(f"%/{file_name}"))
            | (Answer.file_path.like(f"%\\{file_name}"))
        )
        .all()
    )

    # Fuente 2: adjuntos de EVENTOS DE BITÁCORA. Estos se guardan en
    # BitacoraLogsSimple.archivos (JSON) y NO crean filas en answers, por lo que
    # la validación anterior (solo answers) los rechazaba con 404 y las imágenes
    # nunca cargaban. Se buscan aparte.
    # archivos es una columna JSONB (AutoJSON): un LIKE directo NO matchea, hay
    # que castear a texto para buscar el nombre dentro del array JSON.
    bitacora_events_with_file = (
        db.query(BitacoraLogsSimple)
        .filter(cast(BitacoraLogsSimple.archivos, SAText).like(f"%{file_name}%"))
        .all()
    )

    if not answers_with_file and not bitacora_events_with_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado",
        )

    # Acceso vía respuesta de formulario (modelo de permisos existente).
    user_can_access = any(
        can_user_view_response(current_user, ans.response_id, db)
        for ans in answers_with_file
    )

    # Acceso vía evento de bitácora: creador, participante, o admin/creator con
    # asign_bitacora (mismo criterio que get_bitacora_eventos_by_user). El match
    # de participantes es por token completo "- {num_document}" para no filtrar
    # entre documentos que sean substring uno del otro.
    if not user_can_access and bitacora_events_with_file:
        me_token = f"- {current_user.num_document}"
        is_bitacora_admin = (
            current_user.user_type.value in ("admin", "creator")
            and bool(getattr(current_user, "asign_bitacora", False))
        )

        def _user_in_event(ev) -> bool:
            if is_bitacora_admin:
                return True
            if (ev.registrado_por or "").strip().endswith(me_token):
                return True
            partes = [p.strip() for p in (ev.participantes or "").split(",")]
            return any(p.endswith(me_token) for p in partes)

        user_can_access = any(_user_in_event(ev) for ev in bitacora_events_with_file)

    if not user_can_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para descargar este archivo",
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # 🔒 VALIDACIÓN CONTRA PATH TRAVERSAL (defensa en capas)
    # ═══════════════════════════════════════════════════════════════════════════

    # 1. Extraer SOLO el nombre (sin rutas). Path(...).name elimina
    #    automáticamente cualquier "../" o directorio prefijado, incluso en
    #    variantes como "%2e%2e%2fpasswd" después de decodificar.
    raw = (file_name or "").strip().replace("\\", "/")
    safe_name = Path(raw).name

    # 2. Rechazar nombres peligrosos / vacíos / ocultos / con null-bytes
    if (not safe_name
            or safe_name in (".", "..")
            or safe_name.startswith(".")
            or "/" in safe_name
            or "\\" in safe_name
            or "\x00" in safe_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nombre de archivo no válido"
        )

    # 3. Construir ruta absoluta dentro del directorio permitido
    base = Path(ALLOWED_UPLOAD_DIR).resolve()
    candidate = (base / safe_name).resolve()

    # 4. Verificar que la ruta final sigue dentro del directorio base
    #    (protege contra symlinks maliciosos)
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado"
        )

    # 5. Debe existir y ser un archivo regular (no symlink ni directorio)
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if candidate.is_symlink() or not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El recurso solicitado no es un archivo válido"
        )

    # ═══════════════════════════════════════════════════════════════════════════

    return FileResponse(
        path=str(candidate),
        filename=safe_name,
        media_type='application/octet-stream'
    )

@router.get("/db/columns/{table_name}")
def get_table_columns(
    table_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
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
        # 🔥 Tablas virtuales (NO existen en BD)
    VIRTUAL_TABLES = {
        "serials": ["serial"]
    }

    # ✅ Si es tabla virtual, retornar sin inspeccionar BD
    if table_name in VIRTUAL_TABLES:
        return {"columns": VIRTUAL_TABLES[table_name]}

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
    if current_user is None:
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
def create_file_serial(
    data: FileSerialCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
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
def generate_serial(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retorna una lista de respuestas válidas filtradas según la condición asociada a la pregunta.
    
    - **filtered_question_id**: ID de la pregunta con condición de filtro.
    - **Returns**: Lista de objetos con respuestas únicas válidas (sin nulos).
    - **Raises**: HTTP 404 si no existe la condición.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
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
def get_forms_questions_answers_by_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Retorna todos los formularios que contienen la pregunta especificada, incluyendo
    sus preguntas asociadas y respuestas únicas.

    Parámetros:
    - question_id: ID de la pregunta base.

    Retorna:
    - Lista de formularios con sus preguntas y respuestas correspondientes.
    """
    try:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not authenticated"
            )
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
def set_reconsideration_true(
    response_id: int,
    mensaje_reconsideracion: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
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
    if current_user is None:
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
import logging
logger = logging.getLogger(__name__)

@router.post("/create-answers", status_code=status.HTTP_201_CREATED)
async def create_answers(
    response_id: int,
    question_id: int,
    answer_text: Optional[str] = None,
    file_path: Optional[str] = None,
    form_design_element_id: Optional[str] = None,  # ← NUEVO
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
    - form_design_element_id: ID del elemento del diseño del formulario (opcional).
    - db: Sesión de base de datos inyectada automáticamente.
    - current_user: Usuario autenticado que realiza la operación.

    Retorna:
    - Un diccionario con mensaje de éxito e ID del nuevo registro de respuesta.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create answers"
        )
    
    # Validar que existe el response_id
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
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
        # Crear la nueva respuesta con todos los campos
        new_answer = Answer(
            response_id=response_id,
            question_id=question_id,
            answer_text=answer_text,
            file_path=file_path,
            form_design_element_id=form_design_element_id  # ← NUEVO
        )
        
        db.add(new_answer)
        db.commit()
        db.refresh(new_answer)
        
        # Invalidar caché después de crear la respuesta
        cache_key = f"user_responses:{response.form_id}:{current_user.id}"
        redis_client.delete(cache_key)
        logger.info(f"🗑️ Cache invalidado: {cache_key}")
        
        logger.info(f"✅ Respuesta creada - ID: {new_answer.id}, "
              f"Question: {question_id}, "
              f"FormDesignElement: {form_design_element_id}")
        
        return {
            "message": "Answer created successfully",
            "id": new_answer.id,
            "response_id": response_id,
            "question_id": question_id,
            "form_design_element_id": form_design_element_id
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error creando respuesta: {str(e)}")
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
    if current_user is None:
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


@router.delete("/answers/{answer_id}", status_code=status.HTTP_200_OK)
async def delete_answer(
    answer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Elimina una respuesta (Answer) individual por su ID.
    Solo el dueño de la Response puede eliminar sus answers.
    Usado por EditResponseComponent cuando el usuario elimina filas de un repeater.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )
 
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Answer {answer_id} not found"
        )
 
    # Verificar que la respuesta pertenece al usuario
    response = db.query(Response).filter(Response.id == answer.response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
 
    if response.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this answer"
        )
 
    # Eliminar file_serial asociado si existe
    if answer.file_serial:
        db.delete(answer.file_serial)
 
    db.delete(answer)
    db.commit()
 
    # Invalidar caché
    cache_key = f"user_responses:{response.form_id}:{current_user.id}"
    redis_client.delete(cache_key)
 
    return {"message": f"Answer {answer_id} deleted successfully"}

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


@router.get("/{response_id}/pdf")
def download_response_pdf(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Genera un PDF con la estructura visual del formato y las respuestas de
    UN response específico (identificado por response_id).

    Autorización: el usuario debe ser uno de:
      - dueño del response
      - admin o creator
      - aprobador asignado a este response (tiene fila en response_approvals)
    """
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autenticado")

    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")

    is_owner = response.user_id == current_user.id
    is_admin_or_creator = current_user.user_type.name in ("admin", "creator")
    is_approver = (
        db.query(ResponseApproval)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.user_id == current_user.id,
        )
        .first()
        is not None
    )
    if not (is_owner or is_admin_or_creator or is_approver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para descargar esta respuesta",
        )

    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    form_design = form.form_design
    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except json.JSONDecodeError:
            form_design = None
    if not form_design or not isinstance(form_design, list):
        raise HTTPException(
            status_code=400,
            detail="Este formato no tiene diseño disponible para generar PDF",
        )

    answers_orm = (
        db.query(Answer)
        .options(joinedload(Answer.question))
        .filter(Answer.response_id == response_id)
        .all()
    )

    # _serialize_answers reconstruye repeated_id desde form_design,
    # necesario para que los repeaters se rendericen en el PDF.
    answers = _serialize_answers(answers_orm, db, form.id, form_design)

    style_config = _extract_style_config(form_design)

    submitted_at_str = str(response.submitted_at)[:19] if response.submitted_at else ""

    output = generate_form_pdf(
        form_design=form_design,
        answers=answers,
        style_config=style_config,
        form_title=form.title,
        submitted_at=submitted_at_str,
        response_id=response.id,
    )

    safe_title = (form.title or "Formato").replace(" ", "_").replace("/", "_").replace("\\", "_")
    filename = f"Respuesta_{safe_title}_{response_id}.pdf"

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to access completed forms",
        )
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


@router.get("/answers/regisfacial/my-registration")
def get_my_regisfacial_registration(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Devuelve el registro facial más reciente del usuario logueado para una
    pregunta `regisfacial` específica (la fuente configurada por el admin
    en el aprobador).

    Parámetro:
      question_id — Question.id de la pregunta regisfacial fuente. Es
                    obligatorio: distintas preguntas regisfacial conviven
                    en el sistema (ej: "Empleados", "Contratistas") y cada
                    aprobador valida contra una fuente concreta.

    Respuesta:
      200 OK → { answer_id, person_id, person_name }
      400    → la pregunta no es regisfacial
      404    → el usuario aún no tiene registro en esa pregunta
    """
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autenticado")

    # Validar que la pregunta exista y sea regisfacial.
    source_question = (
        db.query(Question)
        .filter(Question.id == question_id)
        .first()
    )
    if not source_question:
        raise HTTPException(status_code=404, detail="Pregunta fuente no encontrada.")
    if source_question.question_type != QuestionType.regisfacial:
        raise HTTPException(
            status_code=400,
            detail="La pregunta indicada no es de tipo registro facial.",
        )

    result = (
        db.query(Answer.id.label("answer_id"), Answer.answer_text)
        .join(Question, Answer.question_id == Question.id)
        .join(Response, Answer.response_id == Response.id)
        .filter(Question.id == question_id)
        .filter(Question.question_type == QuestionType.regisfacial)
        .filter(Response.user_id == current_user.id)
        .filter(Answer.answer_text.isnot(None))
        .order_by(Answer.id.desc())
        .first()
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail=(
                "Aún no has registrado tu rostro. Pide al administrador que te "
                "asigne un formato de registro facial."
            ),
        )

    try:
        parsed = json.loads(result.answer_text)
        face_data = parsed.get("faceData", {}) or {}
        person_id = face_data.get("person_id") or face_data.get("personId")
        person_name = face_data.get("personName") or face_data.get("person_name")
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=500,
            detail="El registro facial existe pero los datos están corruptos.",
        )

    if not person_id:
        raise HTTPException(
            status_code=500,
            detail="El registro facial existe pero falta person_id.",
        )

    return {
        "answer_id": result.answer_id,
        "person_id": person_id,
        "person_name": person_name,
    }


@router.post("/bitacora/logs-simple", summary="Crear registro en bitácora simple")
def create_bitacora_log_endpoint(
    log_data: BitacoraLogsSimpleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint: crea un registro en la tabla bitacora_logs_simple.
    """
    new_log = create_bitacora_log_simple(db, log_data, current_user)
    return {
        "message": "✅ Registro creado exitosamente",
        "data": new_log
    }

@router.get("/bitacora/eventos")
def get_bitacora_eventos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Devuelve todos los registros de la tabla bitacora_eventos (vista global).
    SECURITY: requiere user_type admin/creator + asign_bitacora=True.
    """
    # 🔐 SECURITY (fix #1 auditoría 28-may-2026): antes solo chequeaba el
    #    flag `asign_bitacora`, lo que permitía a cualquier `user_type='user'`
    #    con el flag activado ver la bitácora global de TODOS los usuarios
    #    (IDOR). Ahora se exige además rol admin o creator.
    is_admin_or_creator = current_user.user_type.value in ("admin", "creator")
    if not (is_admin_or_creator and current_user.asign_bitacora):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para ver los registros de bitácora."
        )

    try:
        logs = get_all_bitacora_eventos(db)
        return {
            "message": "Registros obtenidos exitosamente",
            "data": logs
        }
    except Exception as e:
        logger.error(f"⚠️ Error al obtener bitácora: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los registros de bitácora."
        )


@router.get("/bitacora/mis-eventos", summary="Obtener los eventos creados por el usuario autenticado")
def get_mis_eventos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Devuelve solo los registros de bitácora creados por el usuario autenticado.
    """
    logs = get_bitacora_eventos_by_user(db, current_user)

    return {
        "message": "✅ Registros del usuario autenticado obtenidos correctamente",
        "data": logs
    }

@router.put("/eventos/{evento_id}/reabrir", summary="Reabrir conversación del evento")
def reabrir_evento(evento_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Permite reabrir una conversación previamente finalizada.
    Cambia el estado del evento a 'pendiente' y actualiza el usuario que la reabre.
    """
    if not user.asign_bitacora:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a la bitácora de formatos."
        )
    try:
        evento = reabrir_evento_service(evento_id, user.name, user.num_document, db)
        return {"message": "🔄 Conversación reabierta correctamente", "data": evento}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al reabrir el evento: {e}")


@router.post("/eventos/{evento_id}/response", summary="Crear una respuesta a una bitácora simple")
def create_bitacora_log_endpoint(
    log_data: BitacoraLogsSimpleAnswer,
    evento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint: crea un registro en la tabla bitacora_logs_simple.
    """
    new_log = response_bitacora_log_simple(db, log_data, current_user, evento_id)
    return {
        "message": "✅ respuesta creado exitosamente",
        "data": new_log
    }

@router.get("/bitacora/conversacion/{evento_id}", response_model=BitacoraResponse)
def obtener_conversacion(
    evento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
    conversacion = obtener_conversacion_completa(db, evento_id)
    if not conversacion:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return conversacion

@router.put("/conversacion/{evento_id}/finalizar", summary="Finalizar toda la conversación")
def finalizar_conversacion_endpoint(
    evento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint para finalizar todos los eventos de una conversación.
    """
    if str(current_user.user_type.value) not in ["user", "admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para finalizar la conversación."
        )
    usuario = f"{current_user.name} - {current_user.num_document}"
    return finalizar_conversacion_completa(db, evento_id, usuario)

@router.get("/bitacora/formatos")
def get_bitacora_formatos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Devuelve la bitácora de formatos con:
    - Formato (título)
    - Usuario que respondió
    - Preguntas y respuestas asociadas

    ⚠️ Solo los usuarios con asign_bitacora = True pueden acceder.
    """
    # ✅ Verificar si el usuario tiene permiso para ver la bitácora
    if not current_user.asign_bitacora:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a la bitácora de formatos."
        )

    try:
        results = get_all_bitacora_formatos(db)
        return {"message": "Bitácora de formatos obtenida exitosamente", "data": results}

    except Exception as e:
        logger.error(f"⚠️ Error al obtener bitácora de formatos: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la bitácora de formatos."
        )

@router.post("/crear-palabras-clave", summary="Crear palabras clave")
def crear_palabras_clave(
    data: PalabrasClaveCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ✅ Se valida el token
):
    """
    Crea un nuevo registro de palabras clave (solo para admin o creator).
    """

    if str(current_user.user_type.value) not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para crear palabras clave."
        )

    
    try:
        nueva_palabra = crear_palabras_clave_service(data, db)
        return {
            "message": "✅ Palabras clave registradas correctamente",
            "data": {
                "id": nueva_palabra.id,
                "form_id": nueva_palabra.form_id,
                "keywords": nueva_palabra.keywords.split(",")
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al registrar palabras clave: {e}")
    
@router.get("/obtener-palabras-clave", summary="Obtener todas las palabras clave")
def obtener_palabras_clave(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # 👈 valida el token
):
    """
    Retorna todas las palabras clave con su formulario y categoría asociada.
    Solo accesible para usuarios autenticados con roles 'user', 'admin' o 'creator'.
    """
    # 🔐 Validar roles permitidos
    if str(current_user.user_type.value) not in ["user", "admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para acceder a las palabras clave."
        )

    try:
        # 🔹 Join con Form y FormCategory
        palabras = (
            db.query(PalabrasClave, Form, FormCategory)
            .join(Form, Form.id == PalabrasClave.form_id)
            .outerjoin(FormCategory, Form.id_category == FormCategory.id)  # outer join por si no tiene categoría
            .all()
        )

        data = [
            {
                "id": p.PalabrasClave.id,
                "form_id": p.PalabrasClave.form_id,
                "titulo": p.Form.title,
                "categoria": p.FormCategory.name if p.FormCategory else "Sin categoría",
                "palabras_clave": [
                    kw.strip()
                    for kw in p.PalabrasClave.keywords.split(",")
                    if kw.strip()
                ],
            }
            for p in palabras
        ]

        return {
            "message": "✅ Palabras clave obtenidas correctamente",
            "data": data,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener palabras clave: {e}"
        )


@router.get("/by-form-question", summary="Obtener respuestas por formato y pregunta")
def get_answers_by_form_and_question(
    form_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # 👈 valida el token

):
    """
    Devuelve todas las respuestas (answer_text y archivos si existen)
    asociadas a un formato (form_id) y una pregunta (question_id).
    """
       # 🔐 Validar roles permitidos
    if str(current_user.user_type.value) not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para acceder a las palabras clave."
        )
    # Verificar existencia del formato
    form = db.get(Form, form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    # Verificar existencia de la pregunta
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")

    # Buscar las respuestas correspondientes
    stmt = (
        select(Answer)
        .join(Response, Response.id == Answer.response_id)
        .where(Response.form_id == form_id, Answer.question_id == question_id)
        .order_by(Response.submitted_at.desc())
    )

    answers = db.scalars(stmt).all()

    if not answers:
        return {"message": "No hay respuestas para esta pregunta en el formato seleccionado.", "results": []}

    # Estructurar respuesta
    results = [
        {
            "response_id": ans.response_id,
            "question_id": ans.question_id,
            "answer_text": ans.answer_text,
            "file_path": ans.file_path,
            "submitted_at": ans.response.submitted_at,
            "user_id": ans.response.user_id,
            "mode": ans.response.mode,
        }
        for ans in answers
    ]

    return {"count": len(results), "results": results}


# 🧠 Endpoint protegido para crear relaciones
@router.post("/crear-clasification-relation", summary="Crear relación entre formulario y pregunta")
def crear_clasificacion_relacion(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 🔐 Verificar permisos
    if str(current_user.user_type.value) not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para crear relaciones."
        )

    form_id = data.get("form_id")
    question_id = data.get("question_id")

    if not form_id or not question_id:
        raise HTTPException(status_code=400, detail="Faltan form_id o question_id.")

    # 🧭 Obtener el último registro global (el más reciente en la tabla)
    ultima_relacion = (
        db.query(ClasificacionBitacoraRelacion)
        .order_by(ClasificacionBitacoraRelacion.created_at.desc())
        .first()
    )

    # 🔍 Si existe y ambos IDs coinciden => es la relación activa
    if (
        ultima_relacion
        and ultima_relacion.form_id == form_id
        and ultima_relacion.question_id == question_id
    ):
        return {
            "message": "Esta es la relación actualmente activa.",
            "exists": True,
            "data": {
                "id": ultima_relacion.id,
                "form_id": ultima_relacion.form_id,
                "question_id": ultima_relacion.question_id,
                "created_at": ultima_relacion.created_at,
            },
        }

    # 🚀 Si no coincide, crear una nueva relación
    nueva = ClasificacionBitacoraRelacion(
        form_id=form_id,
        question_id=question_id
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    return {
        "message": "✅ Relación creada correctamente",
        "exists": False,
        "data": {
            "id": nueva.id,
            "form_id": nueva.form_id,
            "question_id": nueva.question_id,
            "created_at": nueva.created_at,
        },
    }

@router.get("/obtener-ultima-relacion", summary="Obtener la última pregunta relacionada en Clasificación Bitácora")
def obtener_ultima_relacion(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Devuelve la última relación creada entre formulario y pregunta
    en la tabla 'clasificacion_bitacora_relacion'.
    """
    if str(current_user.user_type.value) not in ["admin", "creator", "user"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para crear relaciones."
        )

    try:
        # Buscar la última relación (orden descendente por ID)
        ultima_relacion = (
            db.query(ClasificacionBitacoraRelacion)
            .order_by(ClasificacionBitacoraRelacion.id.desc())
            .first()
        )

        if not ultima_relacion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No hay relaciones registradas aún."
            )

        # Buscar el texto de la pregunta asociada (en tu modelo Question)
        pregunta = (
            db.query(Question)
            .filter(Question.id == ultima_relacion.question_id)
            .first()
        )

        if not pregunta:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la pregunta asociada a la relación."
            )

        return {
            "message": "✅ Última relación encontrada correctamente.",
            "data": {
                "relacion_id": ultima_relacion.id,
                "form_id": ultima_relacion.form_id,
                "question_id": ultima_relacion.question_id,
                "question_text": pregunta.question_text
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener la última relación: {e}"
        )

@router.get(
    "/forms/{form_id}/palabras-clave",
    response_model=PalabrasClaveOut,
    summary="Obtener palabras clave por form_id"
)
def obtener_palabras_clave(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if str(current_user.user_type.value) not in ["admin", "creator", "user"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para crear relaciones."
        )
    palabras = get_palabras_clave_by_form(db, form_id)

    if not palabras:
        raise HTTPException(
            status_code=404,
            detail="No existen palabras clave para este formulario."
        )

    return palabras


@router.delete(
    "/forms/{form_id}/delete-palabra-clave/{keyword}",
    summary="Eliminar una palabra clave del formulario"
)
def eliminar_palabra_clave(
    form_id: int,
    keyword: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if str(current_user.user_type.value) not in ["admin", "creator"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para crear relaciones."
            )
    registro = db.query(PalabrasClave).filter(PalabrasClave.form_id == form_id).first()

    if not registro:
        raise HTTPException(404, "Este formulario no tiene palabras clave.")

    palabras = registro.keywords.split(",")
    
    if keyword not in palabras:
        raise HTTPException(404, "La palabra clave no existe en este formulario.")

    palabras.remove(keyword)

    registro.keywords = ",".join(palabras)
    registro.updated_at = datetime.now()

    db.commit()

    return {"message": f"Palabra clave '{keyword}' eliminada."}


@router.delete(
    "/forms/{form_id}/delete-palabras-clave",
    summary="Eliminar todas las palabras clave de un formulario"
)
def eliminar_todas_palabras_clave(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if str(current_user.user_type.value) not in ["admin", "creator"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para eliminar palabras clave."
            )
    registro = db.query(PalabrasClave).filter(PalabrasClave.form_id == form_id).first()

    if not registro:
        raise HTTPException(404, "Este formulario no tiene palabras clave.")

    db.delete(registro)
    db.commit()

    return {"message": "Todas las palabras clave fueron eliminadas."}


@router.put("/forms/{form_id}/update-palabras-clave", summary="Agregar una palabra clave")
def update_palabras_clave(
    form_id: int,
    data: PalabrasClaveUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Agrega UNA única palabra clave al formulario, evitando duplicados.
    Si el registro no existe, lo crea.
    """
    # Validación de permisos
    if str(current_user.user_type.value) not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar palabras clave."
        )

    # Normalizar palabra
    nueva = data.palabra.strip().lower()

    if not nueva:
        raise HTTPException(status_code=400, detail="La palabra clave no es válida.")

    # Buscar registro existente
    registro = db.query(PalabrasClave).filter(PalabrasClave.form_id == form_id).first()

    if registro:
        # Convertir palabras actuales a lista
        actuales = [
            p.strip().lower()
            for p in registro.keywords.split(",")
            if p.strip()
        ]

        # Verificar duplicado
        if nueva in actuales:
            return {
                "message": "La palabra clave ya existe.",
                "keywords": registro.keywords
            }

        # Agregar palabra
        actuales.append(nueva)
        registro.keywords = ", ".join(actuales)

    else:
        # Crear nuevo registro con UNA sola palabra
        registro = PalabrasClave(
            form_id=form_id,
            keywords=nueva
        )
        db.add(registro)

    db.commit()

    return {
        "message": "Palabra clave agregada correctamente.",
        "keywords": registro.keywords
    }


@router.post(
    "/{form_id}/math-operations",
    response_model=RelationOperationMathOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una relación de operación matemática"
)
def crear_operacion_matematica(
    form_id: int,
    data: RelationOperationMathCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea una nueva relación de operación matemática para un formulario.
    
    **Parámetros:**
    - form_id: ID del formulario (en la URL)
    - id_questions: Lista de IDs de preguntas involucradas
    - operations: Fórmula matemática (ej: "Q1 + Q2 * Q3")
    """
    
    # Validación de permisos
    if str(current_user.user_type.value) not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para crear operaciones matemáticas."
        )
    
    # Validar que form_id de la URL coincida con el del body
    if data.id_form != form_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El id_form en la URL no coincide con el del cuerpo de la solicitud."
        )
    
    # Verificar que el formulario existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El formulario no existe."
        )
    
    # Verificar que las preguntas existen y pertenecen al formulario
    # ✅ FORMA 1: Usar join con la tabla intermedia form_questions
    if data.id_questions:
        preguntas = db.query(Question).join(
            FormQuestion,
            FormQuestion.question_id == Question.id
        ).filter(
            Question.id.in_(data.id_questions),
            FormQuestion.form_id == form_id
        ).all()
        
        if len(preguntas) != len(data.id_questions):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Una o más preguntas no existen o no pertenecen a este formulario."
            )
    
    # Crear nuevo registro
    nueva_operacion = RelationOperationMath(
        id_form=form_id,
        id_questions=data.id_questions,
        operations=data.operations.strip()
    )
    
    db.add(nueva_operacion)
    db.commit()
    db.refresh(nueva_operacion)
    
    return nueva_operacion


@router.put("/update-answer/{answer_id}", status_code=status.HTTP_200_OK)
async def update_answer(
    answer_id: int,
    answer_text: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza el texto de una respuesta existente.
    
    Este endpoint se usa en formato "abierto" para modificar respuestas 
    sin crear historial ni duplicados.
    
    Parámetros:
    - answer_id: ID de la respuesta a actualizar
    - answer_text: Nuevo texto de la respuesta
    - db: Sesión de base de datos
    - current_user: Usuario autenticado
    
    Retorna:
    - Respuesta actualizada con mensaje de éxito
    """
    
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update answers"
        )
    
    try:
        # 1️⃣ Buscar la respuesta
        answer = db.query(Answer).filter(Answer.id == answer_id).first()
        
        if not answer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Answer with id {answer_id} not found"
            )
        
        # 2️⃣ Verificar permisos (que la respuesta pertenezca a una Response del usuario)
        response = db.query(Response).filter(Response.id == answer.response_id).first()
        
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Response with id {answer.response_id} not found"
            )
        
        # Opcional: Verificar que el usuario sea dueño de la respuesta
        if response.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to modify this answer"
            )
        
        # 3️⃣ Actualizar el texto de la respuesta
        old_text = answer.answer_text
        answer.answer_text = answer_text
        
        db.commit()
        db.refresh(answer)
        
        # 4️⃣ Invalidar caché
        cache_key = f"user_responses:{response.form_id}:{current_user.id}"
        redis_client.delete(cache_key)
        logger.info(f"🗑️ Cache invalidado: {cache_key}")
        
        logger.info(f"✅ Respuesta actualizada - ID: {answer_id}")
        logger.info(f"   Texto anterior: '{old_text}'")
        logger.info(f"   Texto nuevo: '{answer_text}'")
        
        return {
            "message": "Answer updated successfully",
            "id": answer.id,
            "question_id": answer.question_id,
            "response_id": answer.response_id,
            "form_design_element_id": answer.form_design_element_id,
            "old_value": old_text,
            "new_value": answer_text
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error actualizando respuesta {answer_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating answer: {str(e)}"
        )
        
    
@router.post(
    "/get-question-texts",
    response_model=GetQuestionTextsResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener textos de preguntas por IDs"
)
def obtener_textos_preguntas(
    data: GetQuestionTextsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene los textos de las preguntas para un conjunto de IDs.
    """
    
    # Obtener las preguntas
    questions = db.query(Question).filter(
        Question.id.in_(data.question_ids)
    ).all()
    
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontraron preguntas con los IDs proporcionados."
        )
    
    # Construir la respuesta
    question_values = [
        QuestionTextValue(
            question_id=q.id,
            question_text=q.question_text
        )
        for q in questions
    ]
    
    return GetQuestionTextsResponse(questions=question_values)



@router.get(
    "/{form_id}/math-operations/check",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Verificar si un formulario tiene operaciones matemáticas"
)
def verificar_operaciones_matematicas(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verifica si un formulario tiene operaciones matemáticas registradas.
    
    **Parámetros:**
    - form_id: ID del formulario (en la URL)
    
    **Retorna:**
    - has_operations: boolean indicando si tiene operaciones
    - operations: lista de operaciones con sus id_questions si existen
    """
    
    # Verificar que el formulario existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El formulario no existe."
        )
    
    # Buscar operaciones matemáticas para este formulario
    operaciones = db.query(RelationOperationMath).filter(
        RelationOperationMath.id_form == form_id
    ).all()
    
    if not operaciones:
        return {
            "has_operations": False,
            "operations": []
        }
    
    # Formatear respuesta con las operaciones encontradas
    operations_list = [
        {
            "id": op.id,
            "id_questions": op.id_questions,
            "operations": op.operations,
            "created_at": op.created_at.isoformat() if op.created_at else None
        }
        for op in operaciones
    ]
    
    return {
        "has_operations": True,
        "operations": operations_list
    }


@router.get(
    "/{form_id}/math-operations/by-questions",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Obtener operaciones matemáticas por IDs de preguntas"
)
def obtener_operaciones_por_preguntas(
    form_id: int,
    question_ids: str = Query(..., description="IDs de preguntas separados por comas (ej: 1,2,3)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene las operaciones matemáticas que contengan las preguntas especificadas.
    
    **Parámetros:**
    - form_id: ID del formulario (en la URL)
    - question_ids: IDs de preguntas separados por comas en query params
    
    **Retorna:**
    - operations: lista de operaciones que contienen esas preguntas
    """
    
    # Verificar que el formulario existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El formulario no existe."
        )
    
    # Convertir string de IDs a lista de enteros
    try:
        ids_list = [int(id.strip()) for id in question_ids.split(",")]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Los IDs de preguntas deben ser números válidos separados por comas."
        )
    
    if not ids_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar al menos un ID de pregunta."
        )
    
    # Buscar todas las operaciones del formulario
    todas_operaciones = db.query(RelationOperationMath).filter(
        RelationOperationMath.id_form == form_id
    ).all()
    
    # Filtrar operaciones que contengan AL MENOS UNA de las preguntas especificadas
    operaciones_filtradas = []
    for op in todas_operaciones:
        # Verificar si alguno de los IDs buscados está en id_questions de la operación
        if any(qid in op.id_questions for qid in ids_list):
            operaciones_filtradas.append({
                "id": op.id,
                "id_questions": op.id_questions,
                "operations": op.operations,
                "created_at": op.created_at.isoformat() if op.created_at else None,
                "updated_at": op.updated_at.isoformat() if op.updated_at else None
            })
    
    if not operaciones_filtradas:
        return {
            "found": False,
            "message": f"No se encontraron operaciones que incluyan las preguntas: {ids_list}",
            "operations": []
        }
    
    return {
        "found": True,
        "message": f"Se encontraron {len(operaciones_filtradas)} operación(es)",
        "operations": operaciones_filtradas
    }

 
 
@router.put(
    "/{form_id}/math-operations/{operation_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Editar una operación matemática existente"
)
def editar_operacion_matematica(
    form_id: int,
    operation_id: int,
    body: UpdateMathOperationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza la fórmula de una operación matemática existente.
 
    **Parámetros:**
    - form_id: ID del formulario (en la URL)
    - operation_id: ID del registro en relation_operation_math
    - body.operations: nueva fórmula (ej: "{12}*{13}", "+{139}")
    """
 
    # Verificar que el formulario existe
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El formulario no existe."
        )
 
    # Buscar la operación
    operacion = db.query(RelationOperationMath).filter(
        RelationOperationMath.id == operation_id,
        RelationOperationMath.id_form == form_id
    ).first()
 
    if not operacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operación matemática no encontrada para este formulario."
        )
 
    # Actualizar la fórmula
    operacion.operations = body.operations
    db.commit()
    db.refresh(operacion)
 
    return {
        "id": operacion.id,
        "id_form": operacion.id_form,
        "id_questions": operacion.id_questions,
        "operations": operacion.operations,
        "updated_at": operacion.updated_at.isoformat() if operacion.updated_at else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3 ArIA-coverage: búsqueda y agregación de respuestas
#
# Endpoints diseñados para que ArIA pueda responder consultas tipo:
#   "respuestas del formato 21 aprobadas el último mes"
#   "promedio de días de aprobación por categoría"
#   "cuántas respuestas pendientes tiene cada usuario"
#
# Scope: el usuario solo ve respuestas de formularios donde sea dueño, moderador,
# aprobador o respondiente. Misma lógica IDOR que el resto del módulo.
# ═══════════════════════════════════════════════════════════════════════════════

from sqlalchemy import and_, or_, func as sa_func

class ResponseSearchRequest(__import__("pydantic").BaseModel):
    form_id: Optional[int] = None
    user_id: Optional[int] = None
    status: Optional[str] = None  # draft|submitted|approved|rejected
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    text_match: Optional[str] = None  # buscar texto en answer_text
    limit: int = 50
    offset: int = 0


def _user_visible_form_ids(db: Session, user: User) -> List[int]:
    """Calcula qué form_ids puede ver el user: propios, moderador, aprobador, respondiente.
    Simplificado para el endpoint search; suficiente para casos comunes."""
    own_q = db.query(Form.id).filter(Form.user_id == user.id)
    moderator_q = db.query(FormQuestion.form_id).filter(False)  # placeholder
    # Aprobador
    approver_q = db.query(FormApproval.form_id).filter(FormApproval.user_id == user.id)
    # Respondiente: forms donde tenga respuestas
    responder_q = db.query(Response.form_id).filter(Response.user_id == user.id)
    ids = set()
    for q in (own_q, approver_q, responder_q):
        for (fid,) in q.all():
            ids.add(fid)
    # admin/creator ven todo
    if str(getattr(user, "user_type", "") or "").lower() in ("admin", "creator"):
        return None  # marker para sin filtro
    return list(ids)


@router.post("/search")
def search_responses(
    payload: ResponseSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Búsqueda con filtros sobre respuestas. Devuelve metadata, no payload completo
    (usar GET /responses/{id} para el detalle).

    Filtros disponibles: form_id, user_id, status (draft|submitted|approved|rejected),
    date_from, date_to (rango sobre submitted_at), text_match (LIKE en answer_text).
    """
    visible = _user_visible_form_ids(db, current_user)
    q = db.query(Response)
    if visible is not None:  # no es admin/creator
        if not visible:
            return {"total": 0, "items": []}
        q = q.filter(Response.form_id.in_(visible))

    if payload.form_id is not None:
        q = q.filter(Response.form_id == payload.form_id)
    if payload.user_id is not None:
        q = q.filter(Response.user_id == payload.user_id)
    if payload.status:
        try:
            st_enum = ResponseStatus(payload.status.lower())
            q = q.filter(Response.status == st_enum)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"status inválido. Valores: {[s.value for s in ResponseStatus]}",
            )
    if payload.date_from:
        q = q.filter(Response.submitted_at >= payload.date_from)
    if payload.date_to:
        q = q.filter(Response.submitted_at <= payload.date_to)
    if payload.text_match:
        match_ids = (
            db.query(Answer.response_id)
            .filter(Answer.answer_text.ilike(f"%{payload.text_match}%"))
            .distinct()
            .subquery()
        )
        q = q.filter(Response.id.in_(match_ids))

    total = q.count()
    items = (
        q.order_by(Response.submitted_at.desc())
        .offset(max(0, payload.offset))
        .limit(min(200, max(1, payload.limit)))
        .all()
    )
    # Cargar títulos de formato + usuario en batch
    form_ids = {r.form_id for r in items}
    user_ids = {r.user_id for r in items}
    forms_map = {
        f.id: f.title for f in db.query(Form.id, Form.title).filter(Form.id.in_(form_ids)).all()
    } if form_ids else {}
    users_map = {
        u.id: u.name for u in db.query(User.id, User.name).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    out = []
    for r in items:
        out.append({
            "response_id": r.id,
            "form_id": r.form_id,
            "form_title": forms_map.get(r.form_id),
            "user_id": r.user_id,
            "user_name": users_map.get(r.user_id),
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "mode": r.mode,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        })
    return {"total": total, "items": out}


class ResponseAggregateRequest(__import__("pydantic").BaseModel):
    form_id: Optional[int] = None
    group_by: str  # "status" | "user" | "month" | "day" | "form"
    metric: str = "count"  # "count" | "avg_approval_hours"
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


@router.post("/aggregate")
def aggregate_responses(
    payload: ResponseAggregateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agregaciones sobre respuestas. group_by determina la dimensión y metric el valor."""
    visible = _user_visible_form_ids(db, current_user)
    base = db.query(Response)
    if visible is not None:
        if not visible:
            return {"group_by": payload.group_by, "metric": payload.metric, "buckets": []}
        base = base.filter(Response.form_id.in_(visible))
    if payload.form_id is not None:
        base = base.filter(Response.form_id == payload.form_id)
    if payload.date_from:
        base = base.filter(Response.submitted_at >= payload.date_from)
    if payload.date_to:
        base = base.filter(Response.submitted_at <= payload.date_to)

    # Group by
    if payload.group_by == "status":
        key_col = Response.status
        key_label = "status"
    elif payload.group_by == "user":
        key_col = Response.user_id
        key_label = "user_id"
    elif payload.group_by == "form":
        key_col = Response.form_id
        key_label = "form_id"
    elif payload.group_by in ("month", "day"):
        trunc = "month" if payload.group_by == "month" else "day"
        key_col = sa_func.date_trunc(trunc, Response.submitted_at)
        key_label = payload.group_by
    else:
        raise HTTPException(
            status_code=422,
            detail="group_by inválido. Valores: status | user | form | month | day",
        )

    # Metric
    if payload.metric == "count":
        q = base.with_entities(key_col.label("key"), sa_func.count(Response.id).label("value")).group_by(key_col)
    elif payload.metric == "avg_approval_hours":
        # Aproximamos avg de horas entre submitted_at y última aprobación
        last_rev = (
            db.query(
                ResponseApproval.response_id,
                sa_func.max(ResponseApproval.reviewed_at).label("last_rev"),
            )
            .filter(ResponseApproval.reviewed_at.isnot(None))
            .group_by(ResponseApproval.response_id)
            .subquery()
        )
        joined = base.join(last_rev, Response.id == last_rev.c.response_id)
        delta_seconds = sa_func.extract(
            "epoch", last_rev.c.last_rev - Response.submitted_at
        )
        q = (
            joined.with_entities(key_col.label("key"), (sa_func.avg(delta_seconds) / 3600.0).label("value"))
            .group_by(key_col)
        )
    else:
        raise HTTPException(
            status_code=422,
            detail="metric inválido. Valores: count | avg_approval_hours",
        )

    rows = q.all()
    buckets = []
    for row in rows:
        k = row.key
        if hasattr(k, "value"):
            k = k.value
        elif hasattr(k, "isoformat"):
            k = k.isoformat()
        v = row.value
        try:
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            pass
        buckets.append({key_label: k, "value": v})

    # Enriquecer con nombres si group_by es user o form
    if payload.group_by == "user" and buckets:
        ids = [b["user_id"] for b in buckets if b.get("user_id") is not None]
        names = {
            u.id: u.name for u in db.query(User.id, User.name).filter(User.id.in_(ids)).all()
        }
        for b in buckets:
            b["user_name"] = names.get(b.get("user_id"))
    elif payload.group_by == "form" and buckets:
        ids = [b["form_id"] for b in buckets if b.get("form_id") is not None]
        titles = {
            f.id: f.title for f in db.query(Form.id, Form.title).filter(Form.id.in_(ids)).all()
        }
        for b in buckets:
            b["form_title"] = titles.get(b.get("form_id"))

    # Sort descendente por value
    buckets.sort(key=lambda x: (x.get("value") or 0), reverse=True)
    return {
        "group_by": payload.group_by,
        "metric": payload.metric,
        "filters": {
            "form_id": payload.form_id,
            "date_from": payload.date_from.isoformat() if payload.date_from else None,
            "date_to": payload.date_to.isoformat() if payload.date_to else None,
        },
        "buckets": buckets,
    }