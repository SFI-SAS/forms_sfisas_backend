from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List
from app import models
from app.database import get_db
from app.models import User, UserType
from app.crud import create_email_config, create_user, create_user_with_random_password, fetch_all_users, get_all_email_configs, get_user, get_user_by_document, prepare_and_send_file_to_emails, update_user, get_user_by_email, get_users, update_user_info_in_db
from app.schemas import EmailConfigCreate, EmailConfigResponse, UserBaseCreate, UserCreate, UserResponse, UserUpdate, UserUpdateInfo
from app.core.security import get_current_user, hash_password

router = APIRouter()

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    hashed_password = hash_password(user.password)
    user_data = user.model_copy(update={"password": hashed_password})
    
    return create_user(db=db, user=user_data)

@router.get("/{user_id}", response_model=UserResponse)
def get_user_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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

@router.put("/{user_id}", response_model=UserResponse)
def update_user_endpoint(
    user_id: int,
    user: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
    

    if current_user.user_type not in [UserType.creator, UserType.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to search for users by email"
        )

    """Endpoint que llama a la función fetch_all_users."""
    return fetch_all_users(db)  # No necesita `await`

@router.post("/send-file-emails")
async def send_file_to_emails(
    file: UploadFile = File(...),
    emails: List[str] = Form(...),
    name_form: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
    result = update_user_info_in_db(db, current_user, update_data)
    return result



@router.post("/create_user_auto_password", response_model=UserResponse, status_code=status.HTTP_201_CREATED )
def create_user_auto_password(
    user: UserBaseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
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
    try:
        email_configs = get_all_email_configs(db)
        if not email_configs:
            raise HTTPException(status_code=404, detail="No se encontraron configuraciones de correo")
        return email_configs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))