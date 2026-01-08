from app.core.security import get_current_user
from app.database import get_db
from app.models import DownloadTemplate, Form, User
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import func 

router = APIRouter()

# ========== SCHEMAS ==========

class DownloadTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    form_ids: List[int]
    selected_fields: List[int]
    conditions: List[dict] = []
    date_filter: dict = {}
    preferred_format: str = 'excel'

class DownloadTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    form_ids: Optional[List[int]] = None
    selected_fields: Optional[List[int]] = None
    conditions: Optional[List[dict]] = None
    date_filter: Optional[dict] = None
    preferred_format: Optional[str] = None
    is_active: Optional[bool] = None

class DownloadTemplateResponse(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str]
    form_ids: List[int]
    selected_fields: List[int]
    conditions: List[dict]
    date_filter: dict
    preferred_format: str
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    # Información adicional
    forms_count: int
    fields_count: int
    conditions_count: int
    
    class Config:
        from_attributes = True

# ========== ENDPOINTS ==========

@router.post("/templates", response_model=DownloadTemplateResponse)
async def create_template(
    template: DownloadTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Crear una nueva plantilla de descarga"""
    
    # Validar que los formularios existen
    forms_exist = db.query(Form).filter(Form.id.in_(template.form_ids)).count()
    if forms_exist != len(template.form_ids):
        raise HTTPException(status_code=404, detail="Uno o más formularios no existen")
    
    # Crear plantilla
    new_template = DownloadTemplate(
        user_id=current_user.id,
        name=template.name,
        description=template.description,
        form_ids=template.form_ids,
        selected_fields=template.selected_fields,
        conditions=template.conditions,
        date_filter=template.date_filter,
        preferred_format=template.preferred_format
    )
    
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    
    # Construir respuesta con información adicional
    response = DownloadTemplateResponse(
        id=new_template.id,
        user_id=new_template.user_id,
        name=new_template.name,
        description=new_template.description,
        form_ids=new_template.form_ids,
        selected_fields=new_template.selected_fields,
        conditions=new_template.conditions or [],
        date_filter=new_template.date_filter or {},
        preferred_format=new_template.preferred_format,
        is_active=new_template.is_active,
        last_used_at=new_template.last_used_at,
        created_at=new_template.created_at,
        updated_at=new_template.updated_at,
        forms_count=len(new_template.form_ids),
        fields_count=len(new_template.selected_fields),
        conditions_count=len(new_template.conditions or [])
    )
    
    return response


@router.get("/templates", response_model=List[DownloadTemplateResponse])
async def get_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    is_active: Optional[bool] = None
):
    """Obtener todas las plantillas del usuario actual"""
    
    query = db.query(DownloadTemplate).filter(
        DownloadTemplate.user_id == current_user.id
    )
    
    if is_active is not None:
        query = query.filter(DownloadTemplate.is_active == is_active)
    
    templates = query.order_by(DownloadTemplate.updated_at.desc()).all()
    
    response = []
    for template in templates:
        response.append(DownloadTemplateResponse(
            id=template.id,
            user_id=template.user_id,
            name=template.name,
            description=template.description,
            form_ids=template.form_ids or [],
            selected_fields=template.selected_fields or [],
            conditions=template.conditions or [],
            date_filter=template.date_filter or {},
            preferred_format=template.preferred_format,
            is_active=template.is_active,
            last_used_at=template.last_used_at,
            created_at=template.created_at,
            updated_at=template.updated_at,
            forms_count=len(template.form_ids or []),
            fields_count=len(template.selected_fields or []),
            conditions_count=len(template.conditions or [])
        ))
    
    return response


@router.get("/templates/{template_id}", response_model=DownloadTemplateResponse)
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener una plantilla específica"""
    
    template = db.query(DownloadTemplate).filter(
        DownloadTemplate.id == template_id,
        DownloadTemplate.user_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    
    # Actualizar última fecha de uso
    template.last_used_at = func.now()
    db.commit()
    
    return DownloadTemplateResponse(
        id=template.id,
        user_id=template.user_id,
        name=template.name,
        description=template.description,
        form_ids=template.form_ids or [],
        selected_fields=template.selected_fields or [],
        conditions=template.conditions or [],
        date_filter=template.date_filter or {},
        preferred_format=template.preferred_format,
        is_active=template.is_active,
        last_used_at=template.last_used_at,
        created_at=template.created_at,
        updated_at=template.updated_at,
        forms_count=len(template.form_ids or []),
        fields_count=len(template.selected_fields or []),
        conditions_count=len(template.conditions or [])
    )


@router.put("/templates/{template_id}", response_model=DownloadTemplateResponse)
async def update_template(
    template_id: int,
    template_update: DownloadTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Actualizar una plantilla existente"""
    
    template = db.query(DownloadTemplate).filter(
        DownloadTemplate.id == template_id,
        DownloadTemplate.user_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    
    # Actualizar campos proporcionados
    update_data = template_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)
    
    db.commit()
    db.refresh(template)
    
    return DownloadTemplateResponse(
        id=template.id,
        user_id=template.user_id,
        name=template.name,
        description=template.description,
        form_ids=template.form_ids or [],
        selected_fields=template.selected_fields or [],
        conditions=template.conditions or [],
        date_filter=template.date_filter or {},
        preferred_format=template.preferred_format,
        is_active=template.is_active,
        last_used_at=template.last_used_at,
        created_at=template.created_at,
        updated_at=template.updated_at,
        forms_count=len(template.form_ids or []),
        fields_count=len(template.selected_fields or []),
        conditions_count=len(template.conditions or [])
    )

@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Eliminar una plantilla permanentemente"""
    
    template = db.query(DownloadTemplate).filter(
        DownloadTemplate.id == template_id,
        DownloadTemplate.user_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    
    # Hard delete - eliminar definitivamente de la BD
    db.delete(template)
    db.commit()
    
    return {"message": "Plantilla eliminada exitosamente", "template_id": template_id}


@router.post("/templates/{template_id}/duplicate")
async def duplicate_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Duplicar una plantilla existente"""
    
    original_template = db.query(DownloadTemplate).filter(
        DownloadTemplate.id == template_id,
        DownloadTemplate.user_id == current_user.id
    ).first()
    
    if not original_template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    
    # Crear copia
    new_template = DownloadTemplate(
        user_id=current_user.id,
        name=f"{original_template.name} (Copia)",
        description=original_template.description,
        form_ids=original_template.form_ids,
        selected_fields=original_template.selected_fields,
        conditions=original_template.conditions,
        date_filter=original_template.date_filter,
        preferred_format=original_template.preferred_format
    )
    
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    
    return {
        "message": "Plantilla duplicada exitosamente",
        "template_id": new_template.id,
        "name": new_template.name
    }