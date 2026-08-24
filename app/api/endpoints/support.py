"""
Chat de soporte dentro de SafeMetrics.

La conversación vive aquí, en la base: el usuario escribe desde la ventana
flotante y quien atiende responde desde `/home/soporte`. No depende de ningún
servicio externo.

Convive con el botón de WhatsApp del widget, que es la otra vía: quien prefiera
escribir por WhatsApp lo hace desde su propio número y esa conversación no pasa
por aquí. Son dos canales, a propósito.

Dos lados:
  · Usuario  → abre solicitudes, escribe y lee las suyas.
  · Agente   → ve la bandeja completa y responde. Agente = user_type admin,
               o id incluido en SUPPORT_AGENT_USER_IDS (.env), por si hay que
               habilitar a alguien que no es admin. No se inventa un rol nuevo.

NOTA: la columna `whatsapp_notified_at` de `support_tickets` está en desuso.
Quedó de una versión que avisaba por la Cloud API de Meta, descartada a favor
del enlace wa.me. Se conserva para no migrar la tabla.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user
from app.database import get_db
from app.models import SupportMessage, SupportTicket, SupportTicketStatus, User, UserType

load_dotenv()

router = APIRouter()

# Ids de usuarios que atienden soporte sin ser admin. Ej: "12,47"
_AGENTES_EXTRA = {
    int(x) for x in os.getenv("SUPPORT_AGENT_USER_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

MAX_LARGO_MENSAJE = 4000


# ── Permisos ─────────────────────────────────────────────────────────────────

def es_agente(user: User) -> bool:
    return user.user_type == UserType.admin or user.id in _AGENTES_EXTRA


def _exigir_agente(current_user: User = Depends(get_current_user)) -> User:
    if not es_agente(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo soporte")
    return current_user


def _ticket_o_404(db: Session, ticket_id: int, user: User) -> SupportTicket:
    """Trae la solicitud y verifica el acceso. El dueño ve la suya; el agente, todas."""
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if ticket.user_id != user.id and not es_agente(user):
        # 404 y no 403: a quien no es dueño no se le confirma que la solicitud exista.
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return ticket


# ── Cuerpos de petición y respuesta ──────────────────────────────────────────

class ContextoIn(BaseModel):
    """Dónde estaba el usuario al pedir ayuda. Todo opcional: es una ayuda para
    soporte, nunca un requisito para poder escribir."""
    url: Optional[str] = Field(None, max_length=500)
    pantalla: Optional[str] = Field(None, max_length=120)
    form_id: Optional[int] = None
    form_title: Optional[str] = Field(None, max_length=255)
    navegador: Optional[str] = Field(None, max_length=300)


class NuevoTicketIn(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=MAX_LARGO_MENSAJE)
    contexto: Optional[ContextoIn] = None


class NuevoMensajeIn(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=MAX_LARGO_MENSAJE)


class MensajeOut(BaseModel):
    id: int
    ticket_id: int
    autor: str          # 'user' | 'agent'
    autor_nombre: str
    mensaje: str
    creado_en: datetime
    leido: bool


class TicketOut(BaseModel):
    id: int
    asunto: str
    estado: str
    usuario_id: int
    usuario_nombre: str
    agente_nombre: Optional[str]
    contexto: Optional[dict]
    creado_en: datetime
    ultimo_mensaje_en: datetime
    sin_leer: int


# ── Utilidades ───────────────────────────────────────────────────────────────

def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _asunto_desde(mensaje: str) -> str:
    """Resumen para la bandeja: la primera línea, recortada."""
    limpio = " ".join(mensaje.split())
    return limpio[:80] + ("…" if len(limpio) > 80 else "")


def _a_mensaje_out(m: SupportMessage) -> MensajeOut:
    return MensajeOut(
        id=m.id,
        ticket_id=m.ticket_id,
        autor=m.sender_role,
        autor_nombre=m.sender_name,
        mensaje=m.body,
        creado_en=m.created_at,
        leido=m.read_at is not None,
    )


def _contar_sin_leer(db: Session, ticket_id: int, para: str) -> int:
    """Mensajes que `para` ('user'|'agent') todavía no ha leído.

    Lo no leído por el agente son los mensajes del usuario, y viceversa.
    """
    de_quien = "user" if para == "agent" else "agent"
    return (
        db.query(func.count(SupportMessage.id))
        .filter(
            SupportMessage.ticket_id == ticket_id,
            SupportMessage.sender_role == de_quien,
            SupportMessage.read_at.is_(None),
        )
        .scalar()
        or 0
    )


def _a_ticket_out(db: Session, t: SupportTicket, para: str) -> TicketOut:
    return TicketOut(
        id=t.id,
        asunto=t.subject,
        estado=t.status.value,
        usuario_id=t.user_id,
        usuario_nombre=t.user.name if t.user else "(usuario eliminado)",
        agente_nombre=t.agent.name if t.agent else None,
        contexto=t.context,
        creado_en=t.created_at,
        ultimo_mensaje_en=t.last_message_at,
        sin_leer=_contar_sin_leer(db, t.id, para),
    )


# ── Lado del usuario ─────────────────────────────────────────────────────────

@router.post("/tickets", response_model=TicketOut, status_code=201)
def crear_ticket(
    payload: NuevoTicketIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Abre una solicitud de soporte con su primer mensaje.

    Si el usuario ya tiene una conversación sin cerrar, se reutiliza en vez de
    abrir otra: para él es un chat continuo, no un formulario de tickets.
    """
    abierto = (
        db.query(SupportTicket)
        .filter(
            SupportTicket.user_id == current_user.id,
            SupportTicket.status != SupportTicketStatus.closed,
        )
        .order_by(SupportTicket.last_message_at.desc())
        .first()
    )

    if abierto:
        ticket = abierto
    else:
        ticket = SupportTicket(
            user_id=current_user.id,
            subject=_asunto_desde(payload.mensaje),
            status=SupportTicketStatus.open,
            context=payload.contexto.model_dump(exclude_none=True) if payload.contexto else None,
            last_message_at=_ahora(),
        )
        db.add(ticket)
        db.flush()

    db.add(SupportMessage(
        ticket_id=ticket.id,
        sender_user_id=current_user.id,
        sender_role="user",
        sender_name=current_user.name,
        body=payload.mensaje,
    ))
    ticket.last_message_at = _ahora()
    ticket.status = SupportTicketStatus.open
    db.commit()
    db.refresh(ticket)

    return _a_ticket_out(db, ticket, para="user")


@router.get("/tickets/mine", response_model=List[TicketOut])
def mis_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Las conversaciones del usuario, la más reciente primero."""
    tickets = (
        db.query(SupportTicket)
        .options(joinedload(SupportTicket.user), joinedload(SupportTicket.agent))
        .filter(SupportTicket.user_id == current_user.id)
        .order_by(SupportTicket.last_message_at.desc())
        .limit(50)
        .all()
    )
    return [_a_ticket_out(db, t, para="user") for t in tickets]


@router.get("/tickets/{ticket_id}/messages", response_model=List[MensajeOut])
def mensajes_del_ticket(
    ticket_id: int,
    desde_id: int = Query(0, ge=0, description="Solo mensajes con id mayor a este"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mensajes de la conversación.

    `desde_id` es lo que hace barato el sondeo del widget: pasado el id del
    último mensaje que ya tiene, solo viaja lo nuevo.

    Leer marca como leídos los mensajes del otro lado.
    """
    ticket = _ticket_o_404(db, ticket_id, current_user)
    soy_agente = es_agente(current_user) and ticket.user_id != current_user.id
    lado = "agent" if soy_agente else "user"

    mensajes = (
        db.query(SupportMessage)
        .filter(SupportMessage.ticket_id == ticket.id, SupportMessage.id > desde_id)
        .order_by(SupportMessage.created_at)
        .all()
    )

    del_otro = "user" if lado == "agent" else "agent"
    pendientes = [m for m in mensajes if m.sender_role == del_otro and m.read_at is None]
    if pendientes:
        ahora = _ahora()
        for m in pendientes:
            m.read_at = ahora
        db.commit()

    return [_a_mensaje_out(m) for m in mensajes]


@router.post("/tickets/{ticket_id}/messages", response_model=MensajeOut, status_code=201)
def escribir_mensaje(
    ticket_id: int,
    payload: NuevoMensajeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agrega un mensaje. Sirve para los dos lados; el papel sale de quién eres
    frente a esta solicitud, no de tu rol: un admin que abrió la suya escribe
    como usuario."""
    ticket = _ticket_o_404(db, ticket_id, current_user)
    escribe_agente = es_agente(current_user) and ticket.user_id != current_user.id

    mensaje = SupportMessage(
        ticket_id=ticket.id,
        sender_user_id=current_user.id,
        sender_role="agent" if escribe_agente else "user",
        sender_name=current_user.name,
        body=payload.mensaje,
    )
    db.add(mensaje)

    ticket.last_message_at = _ahora()
    if escribe_agente:
        ticket.status = SupportTicketStatus.answered
        ticket.agent_last_seen_at = _ahora()
        if ticket.assigned_agent_id is None:
            # Se asigna solo al primero que responda: no hace falta una pantalla
            # de asignación para un equipo pequeño.
            ticket.assigned_agent_id = current_user.id
    else:
        # Escribir reabre: para el usuario es el mismo chat de siempre.
        ticket.status = SupportTicketStatus.open

    db.commit()
    db.refresh(mensaje)
    return _a_mensaje_out(mensaje)


@router.post("/tickets/{ticket_id}/close", response_model=TicketOut)
def cerrar_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cierra la conversación. Puede hacerlo el dueño o un agente.
    Si el usuario vuelve a escribir, se reabre sola."""
    ticket = _ticket_o_404(db, ticket_id, current_user)
    ticket.status = SupportTicketStatus.closed
    ticket.closed_at = _ahora()
    db.commit()
    db.refresh(ticket)
    lado = "agent" if es_agente(current_user) and ticket.user_id != current_user.id else "user"
    return _a_ticket_out(db, ticket, para=lado)


# ── Lado del agente ──────────────────────────────────────────────────────────

@router.get("/tickets", response_model=List[TicketOut])
def bandeja(
    estado: Optional[str] = Query(None, description="open | answered | closed"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_exigir_agente),
):
    """Bandeja de soporte. Por defecto, solo lo que sigue vivo."""
    q = (
        db.query(SupportTicket)
        .options(joinedload(SupportTicket.user), joinedload(SupportTicket.agent))
    )

    if estado:
        try:
            q = q.filter(SupportTicket.status == SupportTicketStatus(estado))
        except ValueError:
            raise HTTPException(status_code=400, detail="Estado no válido")
    else:
        q = q.filter(SupportTicket.status != SupportTicketStatus.closed)

    tickets = q.order_by(SupportTicket.last_message_at.desc()).limit(100).all()
    return [_a_ticket_out(db, t, para="agent") for t in tickets]


@router.post("/tickets/{ticket_id}/seen", status_code=204)
def marcar_visto(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_exigir_agente),
):
    """El agente abrió la conversación: se marcan leídos los mensajes del usuario."""
    ticket = _ticket_o_404(db, ticket_id, current_user)
    ahora = _ahora()
    ticket.agent_last_seen_at = ahora
    (
        db.query(SupportMessage)
        .filter(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_role == "user",
            SupportMessage.read_at.is_(None),
        )
        .update({SupportMessage.read_at: ahora}, synchronize_session=False)
    )
    db.commit()


@router.get("/unread-count")
def sin_leer(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Contador para el globito: lo que le falta leer a quien pregunta.

    Al agente le cuenta todo lo pendiente de la bandeja; al usuario, solo lo
    suyo. Es el único endpoint que el widget consulta con el panel cerrado, así
    que se mantiene barato: una sola consulta agregada.
    """
    if es_agente(current_user):
        total = (
            db.query(func.count(SupportMessage.id))
            .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
            .filter(
                SupportMessage.sender_role == "user",
                SupportMessage.read_at.is_(None),
                SupportTicket.status != SupportTicketStatus.closed,
                or_(SupportTicket.user_id != current_user.id, SupportTicket.user_id.is_(None)),
            )
            .scalar()
            or 0
        )
        return {"sin_leer": total, "soy_agente": True}

    total = (
        db.query(func.count(SupportMessage.id))
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .filter(
            SupportTicket.user_id == current_user.id,
            SupportMessage.sender_role == "agent",
            SupportMessage.read_at.is_(None),
        )
        .scalar()
        or 0
    )
    return {"sin_leer": total, "soy_agente": False}


@router.get("/config")
def config_soporte(current_user: User = Depends(get_current_user)):
    """Lo que el frontend necesita al arrancar: si quien mira es agente (para
    ofrecerle la bandeja) y su nombre, para el saludo del mensaje de WhatsApp."""
    return {
        "soy_agente": es_agente(current_user),
        "nombre": current_user.name,
    }
