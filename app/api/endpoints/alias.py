# En: app/routes/alias.py (nuevo archivo)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.security import get_current_user
from app.database import get_db
from app.models import Alias, User
from app.schemas import AliasCreate, AliasUpdate, AliasResponse, AliasList

router = APIRouter()

# ========================================
# CREAR ALIAS
# ========================================
@router.post("/", response_model=AliasResponse, status_code=status.HTTP_201_CREATED)
def create_alias(
    alias_data: AliasCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crear un nuevo alias.
    Solo administradores pueden crear alias.
    """
    if current_user.user_type.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para crear alias"
        )

    try:
        db_alias = Alias(
            name=alias_data.name.upper().strip() if alias_data.name else alias_data.name,
            description=alias_data.description.upper().strip() if alias_data.description else alias_data.description
        )
        db.add(db_alias)
        db.commit()
        db.refresh(db_alias)
        return db_alias
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del alias ya existe"
        )


# ========================================
# OBTENER TODOS LOS ALIAS
# ========================================
@router.get("/", response_model=list[AliasList])
def get_all_aliases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtener lista de todos los alias.

    SECURITY (ID-005): requiere autenticación.
    Accesible para todos los usuarios autenticados.
    """
    aliases = db.query(Alias).all()
    return aliases


# ========================================
# OBTENER ALIAS POR ID
# ========================================
@router.get("/{alias_id}", response_model=AliasResponse)
def get_alias(
    alias_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtener un alias específico por su ID.

    SECURITY (ID-005): requiere autenticación.
    """
    db_alias = db.query(Alias).filter(Alias.id == alias_id).first()
    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alias no encontrado"
        )
    return db_alias


# ========================================
# ACTUALIZAR ALIAS
# ========================================
@router.put("/{alias_id}", response_model=AliasResponse)
def update_alias(
    alias_id: int,
    alias_data: AliasUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualizar un alias existente.
    Solo administradores pueden actualizar.
    """
    if current_user.user_type.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para actualizar alias"
        )

    db_alias = db.query(Alias).filter(Alias.id == alias_id).first()
    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alias no encontrado"
        )

    try:
        if alias_data.name:
            db_alias.name = alias_data.name.upper().strip()
        if alias_data.description is not None:
            db_alias.description = alias_data.description.upper().strip() if alias_data.description else alias_data.description

        db.commit()
        db.refresh(db_alias)
        return db_alias
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del alias ya existe"
        )


# ========================================
# ELIMINAR ALIAS
# ========================================
@router.delete("/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alias(
    alias_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Eliminar un alias.
    Solo administradores pueden eliminar.
    """
    if current_user.user_type.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para eliminar alias"
        )

    db_alias = db.query(Alias).filter(Alias.id == alias_id).first()
    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alias no encontrado"
        )

    db.delete(db_alias)
    db.commit()
    return None