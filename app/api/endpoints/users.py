from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import User, UserType
from app.crud import create_user, get_user, update_user, get_user_by_email, get_users
from app.schemas import UserCreate, UserResponse, UserUpdate
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
    if current_user.id != user_id and current_user.user_type != UserType.creators:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to view this user"
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
    if current_user.id != user_id and current_user.user_type != UserType.creator:
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
    if current_user.user_type != UserType.creator:
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
    if current_user.user_type != UserType.creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to list users"
        )
    users = get_users(db, skip=skip, limit=limit)
    return users