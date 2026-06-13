"""
Endpoints de seguridad (solo lectura) para Los Cargos de ArIA.

SM-CARGO-01: expone los eventos de autenticación que vigila el Cargo 7
(Seguridad): logins fallidos, accesos, etc. ArIA solo LEE.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_current_user
from app.models import User, UserType, AuthEvent

router = APIRouter()


@router.get("/auth-events")
def get_auth_events(
    since: Optional[str] = Query(None, description="ISO8601 — solo eventos en/después de esta fecha"),
    event_type: Optional[str] = Query(None, description="filtra por tipo de evento"),
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SM-CARGO-01 · Eventos de autenticación recientes (Cargo 7 Seguridad). Solo admin."""
    if current_user.user_type != UserType.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere rol de administrador",
        )

    q = db.query(AuthEvent)
    if since:
        try:
            dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="`since` debe ser ISO8601")
        q = q.filter(AuthEvent.created_at >= dt)
    if event_type:
        q = q.filter(AuthEvent.event_type == event_type)

    rows = q.order_by(AuthEvent.created_at.desc()).limit(limit).all()
    return {
        "data": [
            {
                "event_type": e.event_type,
                "user_id": e.user_id,
                "email": e.email,
                "ip": e.ip,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "detail": e.detail,
            }
            for e in rows
        ]
    }
