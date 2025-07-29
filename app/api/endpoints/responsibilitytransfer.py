from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from requests import Session

from app.api.controllers.responsibility_service import ResponsibilityTransferService
from app.core.security import get_current_user
from app.database import get_db
from app.models import User, UserType


class TransferRequest(BaseModel):
    from_user_id: int
    to_user_id: int

class SpecificTransferRequest(BaseModel):
    from_user_id: int
    to_user_id: int
    form_ids: List[int]
    responsibility_types: List[str] = ['schedules', 'approvals', 'notifications', 'moderators']

class BatchTransferRequest(BaseModel):
    transfers: List[Dict[str, Any]]

router = APIRouter()

@router.post("/transfer-responsibilities")
async def transfer_responsibilities(
    request: TransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Transfiere todas las responsabilidades de un usuario a otro
    AUTOMÁTICAMENTE detecta y maneja duplicados sin necesidad de especificar exclusiones
    """
    try:
        if current_user.user_type.name != UserType.admin.name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to create forms"
            )
        service = ResponsibilityTransferService(db)
        result = service.transfer_all_responsibilities(
            request.from_user_id,
            request.to_user_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/transfer-specific-responsibilities")
async def transfer_specific_responsibilities(
    request: SpecificTransferRequest,
    db: Session = Depends(get_db)
):
    """
    Transfiere responsabilidades específicas por formulario
    
    Ejemplo de uso:
    {
        "from_user_id": 1,
        "to_user_id": 2,
        "form_ids": [1, 3],  // Solo transferir formularios 1 y 3
        "responsibility_types": ["schedules", "notifications"]
    }
    """
    try:
        service = ResponsibilityTransferService(db)
        result = service.transfer_specific_responsibilities(
            request.from_user_id,
            request.to_user_id,
            request.form_ids,
            request.responsibility_types
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/user-responsibilities/{user_id}")
async def get_user_responsibilities(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene todas las responsabilidades de un usuario
    """
    try:
        
        if current_user.user_type.name != UserType.admin.name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to create forms"
            )
        service = ResponsibilityTransferService(db)
        result = service.get_user_responsibilities(user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

