import io
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Any, List, Optional
from app import models
from app.api.controllers.mail import send_welcome_email
from app.api.endpoints.pdf_router import generate_pdf_from_form_id
from app.database import get_db
from app.models import EmailConfig, User, UserCategory, UserType
from app.crud import create_email_config, create_user, create_user_category, create_user_with_random_password, decrypt_object, delete_user_category_by_id, encrypt_object, fetch_all_users, get_all_email_configs, get_all_user_categories, get_response_details_logic, get_user, get_user_by_document, prepare_and_send_file_to_emails, update_user, get_user_by_email, get_users, update_user_info_in_db
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



@router.get("/forms/{form_id}/pdf")
async def generate_pdf_endpoint(
    form_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    Endpoint para generar y descargar PDF de un formulario.
    """
    try:
        pdf_bytes = await generate_pdf_from_form_id(
            form_id=form_id,
            db=db,
            current_user=current_user,
            request=request
        )
        
        # Crear nombre del archivo
        filename = f"form_{form_id}_response.pdf"
        
        # Crear response con el PDF
        response = StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Error interno del servidor al generar el PDF"
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

    if current_user.user_type not in [UserType.creator, UserType.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to search for users by email"
        )

    """Endpoint que llama a la función fetch_all_users."""
    return fetch_all_users(db)  

@router.post("/send-file-emails")
async def send_file_to_emails(
    file: UploadFile = File(...),
    emails: List[str] = Form(...),
    name_form: str = Form(...),
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
def get_email_configs(db: Session = Depends(get_db)):
    """
    Obtiene todas las configuraciones de correo electrónico disponibles.

    Este endpoint devuelve una lista de todas las configuraciones de correo registradas
    en el sistema.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    Retorna:
    --------
    List[EmailConfigResponse]
        Lista de configuraciones de correo electrónico existentes.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentran configuraciones de correo.
        - 500: Si ocurre un error inesperado durante la consulta.
    """
    try:
        email_configs = get_all_email_configs(db)
        if not email_configs:
            raise HTTPException(status_code=404, detail="No se encontraron configuraciones de correo")
        return email_configs
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