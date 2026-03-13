from ast import Dict
from collections import defaultdict
from difflib import SequenceMatcher, diff_bytes
import io
import json
from fastapi import APIRouter, Depends, File, Form as FastAPIForm, HTTPException, Request, UploadFile, status, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Any, List, Optional
from app import models
from app.api.controllers.mail import send_welcome_email
# from app.api.endpoints.pdf_router import generate_pdf_from_form_id
from app.api.controllers.pdf_form_exporter import FormPdfExporter, generate_form_pdf
from app.database import get_db

from app.models import Answer, EmailConfig, Form, Question, Response, User, UserCategory, UserType
from app.crud import _extract_style_config, _serialize_answers, create_email_config, create_user, create_user_category, create_user_with_random_password, decrypt_object, delete_user_category_by_id, encrypt_object, fetch_all_users, get_all_email_configs, get_all_user_categories, get_response_details_logic, get_user, get_user_by_document, prepare_and_send_file_to_emails, update_user, get_user_by_email, get_users, update_user_info_in_db
from app.schemas import EmailConfigCreate, EmailConfigResponse, EmailConfigUpdate, EmailStatusUpdate, UpdateRecognitionId, UpdateUserCategory, UserBaseCreate, UserCategoryCreate, UserCategoryResponse, UserCreate, UserResponse, UserUpdate, UserUpdateInfo
from app.core.security import get_current_user, hash_password

router = APIRouter()

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    """
    Endpoint para registrar un nuevo usuario en el sistema.

    Esta función recibe los datos necesarios para crear un usuario,
    encripta la contraseña y guarda el usuario en la base de datos.

    Parámetros:
    -----------
    user : UserCreate
        Objeto con la información del usuario a crear (nombre, email, documento, teléfono y contraseña).

    db : Session
        Sesión activa de la base de datos proporcionada por FastAPI.

    Retorna:
    --------
    UserResponse
        Objeto del usuario creado (excluyendo la contraseña).
    """
    hashed_password = hash_password(user.password)
    user_data = user.model_copy(update={"password": hashed_password})
    
    return create_user(db=db, user=user_data)

@router.get("/{user_id}", response_model=UserResponse)
def get_user_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene la información detallada de un usuario específico.

    Este endpoint permite:
    - A cualquier usuario consultar su propio perfil.
    - A usuarios con tipo `creator` o `admin` consultar el perfil de otros usuarios.

    Parámetros:
    -----------
    user_id : int
        ID del usuario que se desea consultar.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    UserResponse
        Información del usuario solicitado.

    Lanza:
    ------
    HTTPException 403:
        Si el usuario autenticado no tiene permisos para ver el perfil solicitado.

    HTTPException 404:
        Si el usuario no existe.
    """
    # Los usuarios pueden ver su propio perfil, pero solo los creators pueden ver otros perfiles

    if current_user.id != user_id and current_user.user_type not in [UserType.creator, UserType.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update this user"
        )

    user = get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user



@router.get("/{form_id}/questions-answers/pdf/user")
def download_user_responses_pdf(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Genera un PDF con el diseño del formulario y las respuestas del usuario.
    """
    from sqlalchemy.orm import joinedload


    # 1. Obtener formulario
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    # 2. Obtener form_design
    form_design = form.form_design
    if isinstance(form_design, str):
        import json
        try:
            form_design = json.loads(form_design)
        except json.JSONDecodeError:
            form_design = None

    if not form_design or not isinstance(form_design, list) or len(form_design) == 0:
        raise HTTPException(
            status_code=400,
            detail="Este formulario no tiene diseño disponible para generar PDF"
        )

    # 3. Obtener respuestas del usuario
    responses = (
        db.query(Response)
        .filter(Response.form_id == form_id, Response.user_id == current_user.id)
        .order_by(Response.submitted_at.desc())
        .all()
    )

    if not responses:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron respuestas para este usuario"
        )

    latest = responses[0]

    # 4. Serializar answers
    answers_orm = (
        db.query(Answer)
        .options(joinedload(Answer.question))
        .filter(Answer.response_id == latest.id)
        .all()
    )

    answers = []
    for ans in answers_orm:
        answers.append({
            "id_answer":               ans.id,
            "question_id":             ans.question_id,
            "question_text":           ans.question.question_text if ans.question else "",
            "question_type":           ans.question.question_type.value if (
                                           ans.question and ans.question.question_type
                                       ) else "text",
            "answer_text":             ans.answer_text or "",
            "file_path":               ans.file_path or "",
"repeated_id":             getattr(ans, "repeated_id", None),
            "form_design_element_id":  getattr(ans, "form_design_element_id", None),
            "repeater_row_index":      getattr(ans, "repeater_row_index", None),
            "parent_row_index":        getattr(ans, "parent_row_index", None),
            "parent_repeated_id":      getattr(ans, "parent_repeated_id", None),
        })

    # 5. Extraer style_config
    style_config = None
    for item in form_design:
        props = item.get("props") or {}
        if props.get("styleConfig"):
            style_config = props["styleConfig"]
            break
        if item.get("headerTable") and not item.get("type"):
            style_config = item
            break

    # 6. Generar PDF
    output = generate_form_pdf(
        form_design=form_design,
        answers=answers,
        style_config=style_config,
        form_title=form.title,
        response_id=latest.id,
    )

    filename = f"Formato_{form.title.replace(' ', '_')}_{form_id}.pdf"

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ═══════════════════════════════════════════════════════
# VARIANTE: PDF de un usuario específico (admin/creator)
# ═══════════════════════════════════════════════════════

@router.get("/{form_id}/questions-answers/pdf/user/{id_user}")
def download_user_responses_pdf_by_admin(
    form_id: int,
    id_user: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Genera PDF con las respuestas de un usuario específico.
    Solo para admin/creator.
    """
    from sqlalchemy.orm import joinedload


    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos"
        )

    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    form_design = form.form_design
    if isinstance(form_design, str):
        import json
        try:
            form_design = json.loads(form_design)
        except json.JSONDecodeError:
            form_design = None

    if not form_design or not isinstance(form_design, list) or len(form_design) == 0:
        raise HTTPException(status_code=400, detail="Formulario sin diseño disponible")

    responses = (
        db.query(Response)
        .filter(Response.form_id == form_id, Response.user_id == id_user)
        .order_by(Response.submitted_at.desc())
        .all()
    )

    if not responses:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    latest = responses[0]

    answers_orm = (
        db.query(Answer)
        .options(joinedload(Answer.question))
        .filter(Answer.response_id == latest.id)
        .all()
    )

    answers = []
    for ans in answers_orm:
        answers.append({
            "id_answer":               ans.id,
            "question_id":             ans.question_id,
            "question_text":           ans.question.question_text if ans.question else "",
            "question_type":           ans.question.question_type.value if (
                                           ans.question and ans.question.question_type
                                       ) else "text",
            "answer_text":             ans.answer_text or "",
            "file_path":               ans.file_path or "",
"repeated_id":             getattr(ans, "repeated_id", None),
            "form_design_element_id":  getattr(ans, "form_design_element_id", None),
            "repeater_row_index":      getattr(ans, "repeater_row_index", None),
            "parent_row_index":        getattr(ans, "parent_row_index", None),
            "parent_repeated_id":      getattr(ans, "parent_repeated_id", None),
        })

    style_config = None
    for item in form_design:
        props = item.get("props") or {}
        if props.get("styleConfig"):
            style_config = props["styleConfig"]
            break
        if item.get("headerTable") and not item.get("type"):
            style_config = item
            break

    target_user = db.query(User).filter(User.id == id_user).first()
    user_name = target_user.name if target_user else f"Usuario_{id_user}"

    output = generate_form_pdf(
        form_design=form_design,
        answers=answers,
        style_config=style_config,
        form_title=form.title,
        response_id=latest.id,
    )

    safe_name = "".join(c for c in user_name if c.isalnum() or c in " _-")
    filename = f"Respuesta_{safe_name}_{form.title.replace(' ', '_')}_{form_id}.pdf"

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ═══════════════════════════════════════════════════════
# VARIANTE: PDF de TODAS las respuestas (all-users)
# ═══════════════════════════════════════════════════════
@router.get("/{form_id}/questions-answers/pdf/all-users")
def download_all_responses_pdf(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Genera un PDF con TODAS las respuestas de todos los usuarios.
    Cada respuesta ocupa una página separada.
    """
    from sqlalchemy.orm import joinedload
    from weasyprint import HTML as WH  # ← reemplaza xhtml2pdf

    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")

    form_design = form.form_design
    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except json.JSONDecodeError:
            form_design = None

    if not form_design or not isinstance(form_design, list) or len(form_design) == 0:
        raise HTTPException(status_code=400, detail="Formulario sin diseño disponible")

    all_responses = (
        db.query(Response)
        .filter(Response.form_id == form_id)
        .order_by(Response.submitted_at.desc())
        .all()
    )

    if not all_responses:
        raise HTTPException(status_code=404, detail="No se encontraron respuestas")

    style_config = _extract_style_config(form_design)

    sc = style_config or {}
    font_family = (
        sc.get("font", {}).get("family", "Arial, sans-serif")
        if isinstance(sc, dict) else "Arial, sans-serif"
    )
    bg_color = sc.get("backgroundColor", "#ffffff") if isinstance(sc, dict) else "#ffffff"

    # ── Construir HTML de cada respuesta ─────────────────────────────────────
    pages_html = []

    for resp in all_responses:
        answers_orm = (
            db.query(Answer)
            .options(joinedload(Answer.question))
            .filter(Answer.response_id == resp.id)
            .all()
        )

        user = db.query(User).filter(User.id == resp.user_id).first()
        user_name = user.name if user else f"Usuario_{resp.user_id}"

        answers = _serialize_answers(answers_orm, db, form_id, form_design)

        exporter = FormPdfExporter(
            form_design=form_design,
            answers=answers,
            style_config=style_config,
            form_title=form.title,
            response_id=resp.id,
        )

        import html as _html_mod
        fecha_str = str(resp.submitted_at)[:19]
        user_name_esc = _html_mod.escape(user_name)

        user_info_html = (
            f'<div style="margin-bottom:8px;padding:6px 10px;'
            f'background-color:#EFF6FF;border:1px solid #BFDBFE;'
            f'border-radius:4px;font-size:10px;color:#1E40AF;">'
            f'<b>Usuario:</b> {user_name_esc} &nbsp;|&nbsp;'
            f'<b>Fecha:</b> {fecha_str}'
            f'</div>'
        )

        page_html = (
            exporter._header_html()
            + user_info_html
            + exporter._render_all_fields()
            + exporter._footer_html()
        )
        pages_html.append(page_html)

    # ── Unir todas las páginas en un solo HTML ────────────────────────────────
    # weasyprint usa @page y print-page-break, soporta calc() sin problema
    combined_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
@page {{
    size: letter landscape;
    margin: 12mm 14mm;
}}
body {{
    font-family: {font_family};
    font-size: 10px;
    color: #333333;
    background: #f0f2f5;
    line-height: 1.5;
}}
.page-section {{
    background: {bg_color};
    page-break-after: always;
    padding: 12px 14px;
}}
.page-section:last-child {{
    page-break-after: auto;
}}
/* ── field-row (igual que FormPdfExporter) ── */
.field-row {{
    display: flex;
    align-items: stretch;
    margin-bottom: 8px;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #e5e7eb;
}}
.field-label {{
    flex: 0 0 32%;
    max-width: 32%;
    padding: 7px 10px;
    background: #f8fafc;
    border-right: 1px solid #e5e7eb;
    font-weight: 600;
    font-size: 9.5px;
    color: #374151;
    word-break: break-word;
    display: flex;
    align-items: center;
}}
.field-label .req {{ color: #ef4444; margin-left: 3px; }}
.field-value {{
    flex: 1;
    padding: 7px 10px;
    font-size: 10px;
    color: #1f2937;
    background: #ffffff;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
}}
.field-empty {{ color: #9ca3af; font-style: italic; font-size: 9px; }}
.repeater-wrap {{
    margin-bottom: 14px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    overflow: hidden;
}}
.repeater-header {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 7px 12px;
    background: #0f8594;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}}
.rep-table {{ width: 100%; border-collapse: collapse; }}
.sub-wrap {{
    margin: 6px 0;
    border-left: 3px solid #0f8594;
    border-radius: 0 6px 6px 0;
    background: #f8fafc;
}}
.sub-header {{
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    background: #e6f7f8;
    color: #0f8594;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    border-bottom: 1px solid #b2e8ec;
}}
.sub-table {{ width: 100%; border-collapse: collapse; }}
.sub-td {{
    padding: 6px 10px 10px 18px;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
}}
.file-badge {{
    font-size: 8.5px;
    color: #2563eb;
    background: #eff6ff;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid #bfdbfe;
}}
.cell-empty {{ color: #9ca3af; font-style: italic; }}
table {{ border-collapse: collapse; }}
img {{ max-width: 100%; }}
</style>
</head>
<body>
{"".join(f'<div class="page-section">{p}</div>' for p in pages_html)}
</body>
</html>"""

    # ── Generar PDF con weasyprint ────────────────────────────────────────────
    output = io.BytesIO()
    WH(string=combined_html).write_pdf(output)
    output.seek(0)

    filename = f"Todas_Respuestas_{form.title.replace(' ', '_')}_{form_id}.pdf"

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/{user_id}", response_model=UserResponse)
def update_user_endpoint(
    user_id: int,
    user: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza los datos de un usuario específico.

    Este endpoint permite:
    - Que un usuario actualice su propio perfil.
    - Que un usuario con tipo `creator` o `admin` actualice cualquier perfil.

    Parámetros:
    -----------
    user_id : int
        ID del usuario que se desea actualizar.

    user : UserUpdate
        Objeto con los campos a modificar (nombre, correo, teléfono, etc.).

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    UserResponse
        Información del usuario actualizado.

    Lanza:
    ------
    HTTPException 403:
        Si el usuario autenticado no tiene permisos para actualizar este perfil.

    HTTPException 404:
        Si el usuario no existe.
    """
    # Solo los creators pueden actualizar usuarios, o el propio usuario puede actualizar su perfil

    if current_user.id != user_id and current_user.user_type not in [UserType.creator, UserType.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update this user"
        )

    updated_user = update_user(db=db, user_id=user_id, user=user)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return updated_user

    
@router.get("/by-email/{email}", response_model=UserResponse)
def get_user_by_email_endpoint(
    email: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene la información de un usuario a partir de su correo electrónico.

    Solo los usuarios con rol `creator` o `admin` pueden utilizar este endpoint para buscar
    otros usuarios por su email.

    Parámetros:
    -----------
    email : str
        Correo electrónico del usuario que se desea buscar.

    db : Session
        Sesión activa de base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    UserResponse
        Objeto con la información del usuario encontrado.

    Lanza:
    ------
    HTTPException 403:
        Si el usuario autenticado no tiene permisos para buscar por correo.

    HTTPException 404:
        Si no se encuentra un usuario con el correo especificado.
    """
    # Los creators pueden buscar usuarios por correo electrónico
    if current_user.user_type not in [UserType.creator, UserType.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to search for users by email"
        )

    user = get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user

@router.get("/", response_model=List[UserResponse])
def list_users_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lista todos los usuarios registrados en el sistema con paginación.

    Solo los usuarios con rol `creator` o `admin` pueden acceder a este endpoint para visualizar
    la lista completa de usuarios.

    Parámetros:
    -----------
    skip : int (por defecto 0)
        Número de registros a omitir (para paginación).

    limit : int (por defecto 10)
        Número máximo de usuarios a devolver. Máximo permitido: 100.

    db : Session
        Sesión activa de base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    List[UserResponse]
        Lista de usuarios en formato `UserResponse`.

    Lanza:
    ------
    HTTPException 403:
        Si el usuario autenticado no tiene permisos para listar usuarios.
    """
    # Los creator pueden listar usuarios, otros usuarios pueden listar sólo su propio perfil

    if current_user.user_type not in [UserType.creator, UserType.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to search for users by email"
        )

    users = get_users(db, skip=skip, limit=limit)
    return users

@router.get("/all-users/all")
def get_all_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Retorna todos los usuarios registrados en el sistema sin aplicar paginación.

    Este endpoint está restringido solo a usuarios con roles `creator` o `admin`.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    List[User]
        Lista completa de usuarios en formato de modelo de respuesta (no especificado si es `UserResponse` o similar).

    Lanza:
    ------
    HTTPException 403:
        Si el usuario autenticado no tiene permisos para acceder a esta información.
    """

    if current_user.user_type not in [UserType.creator, UserType.admin, UserType.user]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to search for users by email"
        )

    """Endpoint que llama a la función fetch_all_users."""
    return fetch_all_users(db)  

@router.post("/send-file-emails")
async def send_file_to_emails(
    file: UploadFile = File(...),
    emails: List[str] = FastAPIForm(...),
    name_form: str = FastAPIForm(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Envía un archivo adjunto a una lista de correos electrónicos con un nombre de formulario asociado.

    Este endpoint permite al usuario autenticado subir un archivo (PDF, imagen, etc.) y enviarlo
    como adjunto a múltiples destinatarios especificados. Además, registra información relacionada
    si es necesario (por ejemplo, historial o logs).

    Parámetros:
    -----------
    file : UploadFile
        Archivo que se desea enviar como adjunto.

    emails : List[str]
        Lista de direcciones de correo electrónico destino.

    name_form : str
        Nombre del formulario asociado con el archivo.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    JSONResponse
        Objeto JSON con el resultado del proceso, incluyendo posibles errores
        o confirmaciones de envío.

    Lanza:
    ------
    HTTPException 400:
        Si no se proporciona un archivo válido.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Archivo no proporcionado.")

    result = prepare_and_send_file_to_emails(file, emails,name_form, current_user.id,db )
    return JSONResponse(content=result)



@router.put("/info/update-profile")
def update_user_info(
    update_data: UserUpdateInfo,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza los datos básicos del perfil del usuario autenticado.

    Este endpoint permite que un usuario modifique su información personal, como
    nombre, teléfono, correo electrónico, entre otros campos permitidos en el esquema `UserUpdateInfo`.

    Parámetros:
    -----------
    update_data : UserUpdateInfo
        Datos actualizados que el usuario desea guardar (por ejemplo, nombre, teléfono, etc.).

    db : Session
        Sesión activa de base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud. Solo puede modificar su propia información.

    Retorna:
    --------
    dict
        Diccionario con la información del usuario actualizada o un mensaje de confirmación.

    Lanza:
    ------
    HTTPException:
        Si ocurre un error durante la actualización (por ejemplo, integridad o permisos).
    """
    result = update_user_info_in_db(db, current_user, update_data)
    return result



@router.post("/create_user_auto_password", response_model=UserResponse, status_code=status.HTTP_201_CREATED )
def create_user_auto_password(
    user: UserBaseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Crea un nuevo usuario con una contraseña generada automáticamente.

    Solo los usuarios con tipo `admin` pueden acceder a este endpoint. La contraseña
    será generada aleatoriamente y almacenada de forma segura. Esta función es útil 
    para crear cuentas de usuario rápidamente sin requerir una contraseña manual.

    Parámetros:
    -----------
    user : UserBaseCreate
        Objeto que contiene los datos básicos del nuevo usuario (nombre, correo, documento, etc.).

    db : Session
        Sesión activa de base de datos.

    current_user : models.User
        Usuario autenticado que realiza la acción (debe ser administrador).

    Retorna:
    --------
    UserResponse
        Usuario recién creado con sus datos (excepto la contraseña por seguridad).

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario actual no es administrador.
        - 400: Si el correo o documento ya están registrados.
    """
        # Verificar permisos de administrador
    if current_user.user_type.name != models.UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update user types"
        )
    return create_user_with_random_password(db, user)

@router.put("/users/update_user_type")
async def update_user_type(
    num_document: str, 
    user_type: str, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """
    Actualiza el tipo de usuario (`user_type`) de un usuario existente identificado por su número de documento.

    Reglas y restricciones:
    ------------------------
    - Solo los usuarios con tipo `admin` pueden realizar esta operación.
    - Un administrador no puede cambiar su propio tipo de usuario.
    - El nuevo tipo de usuario debe estar dentro de los valores válidos definidos en la enumeración `UserType`.

    Parámetros:
    -----------
    num_document : str
        Número de documento del usuario cuyo tipo se desea actualizar.

    user_type : str
        Nuevo valor del tipo de usuario. Debe ser uno de los valores permitidos por `UserType` (por ejemplo: "admin", "creator", "user").

    db : Session
        Sesión activa de base de datos.

    current_user : models.User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    dict
        Mensaje de éxito junto con el nuevo tipo de usuario.

    Lanza:
    ------
    HTTPException:
        - 400: Si el administrador intenta cambiar su propio tipo de usuario o si el tipo proporcionado no es válido.
        - 403: Si el usuario autenticado no es administrador.
        - 404: Si no se encuentra un usuario con el número de documento especificado.
    """
    # Verificar si el número de documento del usuario a actualizar es el mismo que el del current_user
    if num_document == current_user.num_document:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin cannot update their own user type."
        )
    
    # Verificar permisos de administrador
    if current_user.user_type.name != models.UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update user types"
        )
    
    # Validar que el tipo de usuario sea válido
    if user_type not in [item.value for item in models.UserType]:
        raise HTTPException(status_code=400, detail="Invalid user type")
    
    # Buscar el usuario en la base de datos por su número de documento
    user = get_user_by_document(db, num_document)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Actualizar el tipo de usuario
    user.user_type = user_type
    db.commit()
    
    return {"message": f"User type for {num_document} updated successfully", "user_type": user.user_type}



@router.post("/email-config/", response_model=EmailConfigCreate)
def create_email(email_config: EmailConfigCreate, db: Session = Depends(get_db),current_user: models.User = Depends(get_current_user)):
    """
    Crea una nueva configuración de correo electrónico.

    Solo los usuarios con tipo `admin` tienen permiso para crear configuraciones de correo.

    Parámetros:
    -----------
    email_config : EmailConfigCreate
        Objeto que contiene los datos necesarios para la configuración del correo. 
        (por ejemplo: `smtp_host`, `smtp_port`, `sender_email`, etc.).

    db : Session
        Sesión activa de base de datos.

    current_user : models.User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    EmailConfigCreate
        Objeto con la configuración de correo electrónico recién creada.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no tiene permisos de administrador.
        - 500: Si ocurre un error inesperado al guardar la configuración.
    """
    try:
        if current_user.user_type.name != models.UserType.admin.name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to update user types"
            )
        return create_email_config(db, email_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    

@router.get("/email-config/", response_model=List[EmailConfigResponse])
def get_email_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
    """
    Obtiene todas las configuraciones de correo electrónico disponibles.

    Este endpoint devuelve una lista de todas las configuraciones de correo registradas
    en el sistema. Si no existen configuraciones, devuelve una lista vacía.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    Retorna:
    --------
    List[EmailConfigResponse]
        Lista de configuraciones de correo electrónico existentes, 
        o una lista vacía si no hay configuraciones.

    Lanza:
    ------
    HTTPException:
        - 500: Si ocurre un error inesperado durante la consulta.
    """
    try:
        email_configs = get_all_email_configs(db)
        return email_configs if email_configs else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.put("/email-config/{id}")
def update_email_config(id: int, email_update: EmailConfigUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Actualiza la dirección de correo electrónico de una configuración existente.

    Este endpoint permite modificar el campo `email_address` de una configuración de
    correo previamente creada. Solo los usuarios con rol `creator` o `admin` tienen
    permiso para realizar esta operación.

    Parámetros:
    -----------
    id : int
        ID de la configuración de correo a actualizar.

    email_update : EmailConfigUpdate
        Objeto con el nuevo correo electrónico (`email_address`) a registrar.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    dict:
        Mensaje de éxito y los datos actualizados de la configuración.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no tiene permisos para modificar la configuración.
        - 404: Si no se encuentra la configuración de correo con el ID especificado.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    # Buscar el registro en la base de datos
    email_config = db.query(EmailConfig).filter(EmailConfig.id == id).first()

    if not email_config:
        raise HTTPException(status_code=404, detail="Configuración de correo no encontrada")

    # Actualizar el valor del correo
    email_config.email_address = email_update.email_address

    # Guardar cambios
    db.commit()
    db.refresh(email_config)
    
    return {"message": "Correo actualizado correctamente", "data": email_config}


@router.put("/email-config/{id}/status")
def update_email_config_status(id: int, status_update: EmailStatusUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Actualiza el estado (`is_active`) de una configuración de correo electrónico.

    Solo los usuarios con permisos de tipo `creator` o `admin` pueden activar o desactivar
    una configuración de correo.

    Parámetros:
    -----------
    id : int
        ID de la configuración de correo que se desea actualizar.

    status_update : EmailStatusUpdate
        Objeto que contiene el nuevo estado booleano (`is_active`).

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la solicitud.

    Retorna:
    --------
    dict:
        Mensaje de éxito junto con la configuración de correo actualizada.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no tiene permisos para realizar esta acción.
        - 404: Si no se encuentra la configuración de correo con el ID especificado.
    """
    if current_user.user_type.name not in [UserType.creator.name, UserType.admin.name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    status_config = db.query(EmailConfig).filter(EmailConfig.id == id).first()

    if not status_config:
        raise HTTPException(status_code=404, detail="Configuración de correo no encontrada")

    status_config.is_active = status_update.is_active

    db.commit()
    db.refresh(status_config)

    return {"message": "Estado actualizado correctamente", "data": status_config}

class WelcomeEmailRequest(BaseModel):
    email: EmailStr
    name: str
    password: str

@router.post("/send_welcome_email")
def send_email(data: WelcomeEmailRequest):
    """
    Envía un correo electrónico de bienvenida a un nuevo usuario.

    Este endpoint utiliza un servicio de envío de correos para enviar
    un mensaje de bienvenida con las credenciales del usuario.

    Parámetros:
    -----------
    data : WelcomeEmailRequest
        Objeto que contiene los datos necesarios para enviar el correo:
        - `email` (str): Correo electrónico del destinatario.
        - `name` (str): Nombre del usuario.
        - `password` (str): Contraseña generada para el usuario.

    Retorna:
    --------
    dict:
        Mensaje indicando que el correo fue enviado correctamente.

    Lanza:
    ------
    HTTPException:
        - 500: Si ocurre un error durante el envío del correo.
    """
    success = send_welcome_email(email=data.email, name=data.name, password=data.password)
    if not success:
        raise HTTPException(status_code=500, detail="No se pudo enviar el correo")
    return {"message": f"Correo enviado a {data.email}"}


@router.post("/create_category", response_model=UserCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category_endpoint(
    category: UserCategoryCreate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar la categoría de un usuario"
        )
    return create_user_category(db, category)

@router.get("/list_all_user/categories", response_model=List[UserCategoryResponse])
def list_all_user_categories(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso"
        )
    return get_all_user_categories(db)

@router.delete("/delete_user_category/{category_id}", status_code=status.HTTP_200_OK)
def delete_user_category(category_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar la categoría de un usuario"
        )
    return delete_user_category_by_id(db, category_id)

@router.put("/update_user_category/{user_id}/category")
def update_user_category(
    user_id: int,
    category_data: UpdateUserCategory,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar la categoría de un usuario"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if category_data.id_category is not None:
        category = db.query(UserCategory).filter(UserCategory.id == category_data.id_category).first()
        if not category:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")

    user.id_category = category_data.id_category
    db.commit()
    db.refresh(user)

    return {
        "message": "Categoría actualizada correctamente",
        "user_id": user.id,
        "new_category_id": user.id_category
    }
    
@router.patch("/update-recognition-id", response_model=UserResponse, status_code=status.HTTP_200_OK)
def update_user_recognition_id(
    data: UpdateRecognitionId,
    db: Session = Depends(get_db),
):
    """
    Endpoint para actualizar el recognition_id de un usuario basado en su número de documento.
    
    Esta función busca un usuario por su número de documento y actualiza su recognition_id.
    Si el usuario no existe, retorna un error 404.
    Si el recognition_id ya existe para otro usuario, retorna un error 409.
    
    Parámetros:
    -----------
    data : UpdateRecognitionId
        Objeto con el número de documento y el nuevo recognition_id.
    
    db : Session
        Sesión activa de la base de datos proporcionada por FastAPI.
    
    Retorna:
    --------
    UserResponse
        Objeto del usuario actualizado (excluyendo la contraseña).
    """
    
    # Buscar el usuario por número de documento usando consulta directa
    user = db.query(User).filter(User.num_document == data.num_document).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con número de documento {data.num_document} no encontrado"
        )
    
    # Verificar si el recognition_id ya existe para otro usuario
    existing_user_with_recognition = db.query(User).filter(
        User.recognition_id == data.recognition_id,
        User.id != user.id
    ).first()
    
    if existing_user_with_recognition:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El recognition_id {data.recognition_id} ya está asignado a otro usuario"
        )
    
    # Actualizar el recognition_id
    user.recognition_id = data.recognition_id
    db.commit()
    db.refresh(user)
    
    return user


@router.post("/encrypt-test")
async def encrypt_test():
    """Endpoint simple para probar encriptación"""
    data = {"mensaje": "MANUEL GOMEZ MACEA", "numero": 50, "activo": True}
    encrypted = encrypt_object(data)
    return {
        "original": data,
        "encrypted": encrypted
    }

@router.post("/decrypt-test/{encrypted_data}")
async def decrypt_test(encrypted_data: str):
    """Endpoint simple para probar desencriptación"""
    decrypted = decrypt_object(encrypted_data)
    return {
        "decrypted": decrypted,
        "encrypted_was": encrypted_data
    }
@router.patch("/asign-bitacora/{user_id}")
def asignar_bitacora(
    user_id: int,
    asignar: Optional[bool] = True,  # True = asignar, False = quitar
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Asigna o quita el permiso de 'asign_bitacora' a un usuario específico.
    Solo los usuarios con rol 'admin' o 'creator' pueden hacerlo.
    """
    # Verificar permisos del usuario actual
    if current_user.user_type.value not in ["admin", "creator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para asignar bitácoras."
        )

    # Buscar el usuario al que se le asignará el permiso
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    # Actualizar el valor
    user.asign_bitacora = asignar
    db.commit()
    db.refresh(user)

    return {
        "message": f"Permiso de bitácora {'asignado' if asignar else 'revocado'} correctamente al usuario {user.name}",
        "data": {
            "id": user.id,
            "name": user.name,
            "num_document": user.num_document,
            "asign_bitacora": user.asign_bitacora
        }
    }

class MigrationResponse(BaseModel):
    status: str
    total_to_migrate: int
    migrated: int
    skipped: int
    message: str
    details: dict = {}


def get_element_uuid_by_question(form_design, question_id):
    """
    🎯 Busca el UUID del elemento que coincida con question_id
    Ahora usa AMBOS: linkExternalId e id_question
    """
    if not form_design or not isinstance(form_design, list):
        return None
    
    for item in form_design:
        if isinstance(item, dict):
            # ✅ NUEVO: Verificar AMBOS campos
            link_id = item.get('linkExternalId')
            id_q = item.get('id_question')
            element_uuid = item.get('id')
            
            # Si cualquiera de los dos coincide, retornar el UUID
            if element_uuid and (link_id == question_id or id_q == question_id):
                return element_uuid
            
            # 🔄 Buscar recursivamente en children (layouts, repeaters)
            children = item.get('children', [])
            if children and isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        child_link = child.get('linkExternalId')
                        child_id_q = child.get('id_question')
                        child_uuid = child.get('id')
                        
                        if child_uuid and (child_link == question_id or child_id_q == question_id):
                            return child_uuid
    
    return None


@router.post("/migrate/form-design-elements", response_model=MigrationResponse)
async def migrate_form_design_elements(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
    """
    🔄 Migración mejorada con id_question
    Actualiza form_design_element_id en answers usando el nuevo campo id_question
    """
    
    try:
        # 1. Obtener answers sin form_design_element_id Y su form_design
        result = db.execute(
            text("""
                SELECT a.id, a.question_id, f.form_design, f.id as form_id
                FROM answers a
                JOIN responses r ON a.response_id = r.id
                JOIN forms f ON r.form_id = f.id
                WHERE a.form_design_element_id IS NULL
                ORDER BY a.id
            """)
        )
        
        rows = result.fetchall()
        total = len(rows)
        migrated = 0
        skipped = 0
        details = {
            "by_form": {},
            "errors": []
        }
        
        if total == 0:
            return MigrationResponse(
                status="success",
                total_to_migrate=0,
                migrated=0,
                skipped=0,
                message="✅ Nada que migrar - Todos los answers ya tienen form_design_element_id"
            )
        
        # 2. Procesar cada fila
        for answer_id, question_id, form_design_json, form_id in rows:
            try:
                # Parsear el form_design JSON
                form_design = json.loads(form_design_json) if form_design_json else []
                
                # Buscar el UUID usando la función mejorada
                uuid = get_element_uuid_by_question(form_design, question_id)
                
                # Solo actualizar si encuentra el UUID
                if uuid:
                    db.execute(
                        text("UPDATE answers SET form_design_element_id = :uuid WHERE id = :id"),
                        {"uuid": uuid, "id": answer_id}
                    )
                    migrated += 1
                    
                    # Tracking por formulario
                    if form_id not in details["by_form"]:
                        details["by_form"][form_id] = {"migrated": 0, "skipped": 0}
                    details["by_form"][form_id]["migrated"] += 1
                    
                else:
                    skipped += 1
                    
                    # Tracking de los que no se pudieron migrar
                    if form_id not in details["by_form"]:
                        details["by_form"][form_id] = {"migrated": 0, "skipped": 0}
                    details["by_form"][form_id]["skipped"] += 1
                    
                    details["errors"].append({
                        "answer_id": answer_id,
                        "question_id": question_id,
                        "form_id": form_id,
                        "reason": "No se encontró elemento con linkExternalId o id_question coincidente"
                    })
                
            except json.JSONDecodeError as e:
                skipped += 1
                details["errors"].append({
                    "answer_id": answer_id,
                    "question_id": question_id,
                    "form_id": form_id,
                    "reason": f"JSON inválido: {str(e)}"
                })
                continue
            except Exception as e:
                skipped += 1
                details["errors"].append({
                    "answer_id": answer_id,
                    "question_id": question_id,
                    "form_id": form_id,
                    "reason": f"Error: {str(e)}"
                })
                continue
        
        db.commit()
        
        # 3. Preparar mensaje detallado
        message_parts = [f"✨ Migración completada: {migrated}/{total} actualizadas"]
        if skipped > 0:
            message_parts.append(f"⚠️ {skipped} omitidas (no se encontró UUID)")
        
        return MigrationResponse(
            status="success" if migrated > 0 else "partial",
            total_to_migrate=total,
            migrated=migrated,
            skipped=skipped,
            message=" | ".join(message_parts),
            details=details
        )
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"❌ Error en migración: {str(e)}"
        )


# 🆕 ENDPOINT ADICIONAL: Ver estadísticas de migración
@router.get("/migrate/stats")
async def get_migration_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
    """📊 Estadísticas de migración"""
    
    result = db.execute(
        text("""
            SELECT 
                COUNT(*) as total_answers,
                COUNT(form_design_element_id) as with_uuid,
                COUNT(*) - COUNT(form_design_element_id) as without_uuid
            FROM answers
        """)
    )
    
    row = result.fetchone()
    
    return {
        "total_answers": row[0],
        "with_uuid": row[1],
        "without_uuid": row[2],
        "percentage_complete": round((row[1] / row[0] * 100) if row[0] > 0 else 0, 2)
    }


# 🆕 ENDPOINT ADICIONAL: Ver answers problemáticos
@router.get("/migrate/problematic")
async def get_problematic_answers(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated"
        )
    """🔍 Ver answers que no se pudieron migrar"""
    
    result = db.execute(
        text("""
            SELECT 
                a.id as answer_id,
                a.question_id,
                q.question_text,
                f.id as form_id,
                f.title as form_title,
                f.form_design::text as form_design_preview
            FROM answers a
            JOIN responses r ON a.response_id = r.id
            JOIN forms f ON r.form_id = f.id
            LEFT JOIN questions q ON a.question_id = q.id
            WHERE a.form_design_element_id IS NULL
            ORDER BY a.id DESC
            LIMIT :limit
        """),
        {"limit": limit}
    )
    
    rows = result.fetchall()
    
    problematic = []
    for row in rows:
        # Parsear form_design para ver qué elementos tiene
        try:
            form_design = json.loads(row[5]) if row[5] else []
            elements_with_links = [
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "linkExternalId": item.get("linkExternalId"),
                    "id_question": item.get("id_question")
                }
                for item in form_design
                if isinstance(item, dict) and item.get("linkExternalId")
            ]
        except:
            elements_with_links = []
        
        problematic.append({
            "answer_id": row[0],
            "question_id": row[1],
            "question_text": row[2],
            "form_id": row[3],
            "form_title": row[4],
            "available_elements": elements_with_links
        })
    
    return {
        "total_problematic": len(problematic),
        "answers": problematic
    }