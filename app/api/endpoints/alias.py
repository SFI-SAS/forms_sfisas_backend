# En: app/routes/alias.py (nuevo archivo)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user
from app.database import get_db
from app.models import Alias, Question, User
from app.schemas import AliasCreate, AliasUpdate, AliasResponse, AliasList, QuestionWithCategory

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
        db_alias = Alias(name=alias_data.name, description=alias_data.description)
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
def get_all_aliases(db: Session = Depends(get_db)):
    """
    Obtener lista de todos los alias.
    Accesible para todos los usuarios autenticados.
    """
    aliases = db.query(Alias).all()
    return aliases


# ========================================
# OBTENER ALIAS POR ID
# ========================================
@router.get("/{alias_id}", response_model=AliasResponse)
def get_alias(alias_id: int, db: Session = Depends(get_db)):
    """
    Obtener un alias específico por su ID.
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
            db_alias.name = alias_data.name
        if alias_data.description is not None:
            db_alias.description = alias_data.description

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

# En tu archivo de rutas

@router.put("/{question_id}/alias", response_model=QuestionWithCategory)
def update_question_alias(
    question_id: int,
    alias_data: dict,  # Ejemplo: {"id_alias": 5} o {"id_alias": null}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza el alias asignado a una pregunta.
    
    Parámetros:
    -----------
    question_id : int
        ID de la pregunta a actualizar
    
    alias_data : dict
        Diccionario con el campo id_alias (puede ser int o None)
    
    Retorna:
    --------
    QuestionWithCategory:
        La pregunta actualizada con su nuevo alias
    
    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado
        - 404: Si la pregunta no existe
        - 400: Si el alias no existe
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update question alias"
        )
    
    # Buscar la pregunta
    question = db.query(Question).filter(Question.id == question_id).first()
    
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with id {question_id} not found"
        )
    
    # Obtener el nuevo id_alias
    new_alias_id = alias_data.get('id_alias')
    
    # Si se proporciona un alias, verificar que existe
    if new_alias_id is not None:
        alias_exists = db.query(Alias).filter(Alias.id == new_alias_id).first()
        if not alias_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alias with id {new_alias_id} does not exist"
            )
    
    # Actualizar el alias
    question.id_alias = new_alias_id
    db.commit()
    db.refresh(question)
    
    # Recargar con las relaciones
    question = db.query(Question).options(
        joinedload(Question.category),
        joinedload(Question.alias)
    ).filter(Question.id == question_id).first()
    
    return question