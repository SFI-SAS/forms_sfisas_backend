"""
Solicitudes de edición de respuesta.

El caso: alguien consulta una respuesta suya, ve un error y quiere corregirlo.
La pantalla solo deja editar en borrador, así que pide permiso al
administrador eligiendo QUÉ campos necesita tocar.

Dos lados:

  · USUARIO  — crea la solicitud, ve en qué va, la cancela si se arrepintió, y
    consulta qué tiene autorizado a editar en este momento.
  · ADMIN    — su bandeja: lo pendiente, aprobar, rechazar.

El permiso que concede el administrador es de UN SOLO USO y acotado a los
campos pedidos. Cuando el usuario guarda su corrección, la solicitud pasa a
'used' y la puerta se cierra sola. La alternativa —dejar el permiso abierto—
convierte una autorización puntual en un privilegio permanente que nadie
recuerda revocar.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import field_access
from app.core.security import get_current_user
from app.crud import get_bogota_time
from app.database import get_db
from app.models import (
    Form,
    Response,
    ResponseEditRequest,
    User,
    UserType,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Estados en los que la solicitud sigue "viva": ocupa el cupo de una sola
# solicitud por respuesta y usuario.
VIVOS = ("pending", "approved")


# ===========================================================================
# Schemas
# ===========================================================================

class CampoPedido(BaseModel):
    element_id: str
    question_id: Optional[int] = None
    # La etiqueta se guarda junto al id: si el formato cambia, el administrador
    # tiene que poder leer qué autorizó aunque el campo ya no exista.
    label: Optional[str] = None


class CrearSolicitudIn(BaseModel):
    response_id: int
    # 'all' = la respuesta completa. 'fields' = solo los de `fields`.
    scope: str = "fields"
    fields: List[CampoPedido] = Field(default_factory=list)
    requester_message: Optional[str] = None


class RevisarIn(BaseModel):
    review_message: Optional[str] = None


def _es_admin(user: User) -> bool:
    return getattr(user.user_type, "name", None) == "admin"


def _salida(req: ResponseEditRequest, *, con_formato: bool = False) -> dict:
    datos = {
        "id": req.id,
        "response_id": req.response_id,
        "form_id": req.form_id,
        "scope": req.scope,
        "fields": req.fields or [],
        "requester_message": req.requester_message,
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "review_message": req.review_message,
        "used_at": req.used_at.isoformat() if req.used_at else None,
        "requester": {
            "id": req.requester.id,
            "name": req.requester.name,
            "email": req.requester.email,
        } if req.requester else None,
        "reviewer": {
            "id": req.reviewer.id,
            "name": req.reviewer.name,
        } if req.reviewer else None,
    }
    if con_formato and req.form:
        datos["form"] = {"id": req.form.id, "title": req.form.title}
    return datos


# ===========================================================================
# Lado del USUARIO
# ===========================================================================

@router.post("/")
def crear_solicitud(
    payload: CrearSolicitudIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pide permiso para editar una respuesta propia."""
    response = db.query(Response).filter(Response.id == payload.response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")

    # Solo el dueño. Pedir permiso para editar lo ajeno no tiene sentido, y
    # dejarlo abierto sería una vía para tocar respuestas de otros.
    if response.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Solo puedes pedir editar tus propias respuestas",
        )

    if payload.scope not in ("all", "fields"):
        raise HTTPException(status_code=422, detail="Alcance inválido")
    if payload.scope == "fields" and not payload.fields:
        raise HTTPException(
            status_code=422,
            detail="Elige al menos un campo, o pide la respuesta completa",
        )

    # Una sola solicitud viva por respuesta y usuario: pulsar dos veces el botón
    # no le deja al administrador dos solicitudes idénticas que atender.
    viva = (
        db.query(ResponseEditRequest)
        .filter(
            ResponseEditRequest.response_id == payload.response_id,
            ResponseEditRequest.requester_id == current_user.id,
            ResponseEditRequest.status.in_(VIVOS),
        )
        .first()
    )
    if viva is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ya tienes una solicitud aprobada para esta respuesta; úsala antes de pedir otra"
                if viva.status == "approved"
                else "Ya enviaste una solicitud para esta respuesta y está pendiente"
            ),
        )

    req = ResponseEditRequest(
        response_id=payload.response_id,
        form_id=response.form_id,
        requester_id=current_user.id,
        scope=payload.scope,
        fields=(
            [f.model_dump() for f in payload.fields] if payload.scope == "fields" else None
        ),
        requester_message=(payload.requester_message or "").strip() or None,
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    logger.info(
        "Solicitud de edición creada (id=%s, response=%s, usuario=%s, campos=%s)",
        req.id, req.response_id, current_user.id,
        "todos" if req.scope == "all" else len(req.fields or []),
    )
    return {"ok": True, "solicitud": _salida(req)}


@router.get("/mine/{response_id}")
def mi_solicitud(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """La última solicitud de este usuario sobre esta respuesta.

    La usa la pantalla para saber qué mostrar: el botón de pedir, "pendiente de
    aprobación", o habilitar la edición de los campos autorizados.
    """
    req = (
        db.query(ResponseEditRequest)
        .filter(
            ResponseEditRequest.response_id == response_id,
            ResponseEditRequest.requester_id == current_user.id,
        )
        .order_by(ResponseEditRequest.id.desc())
        .first()
    )
    if req is None:
        return {"solicitud": None, "puede_editar": False, "element_ids": []}

    aprobada = req.status == "approved"
    return {
        "solicitud": _salida(req),
        # Lo que la pantalla necesita para decidir de una: si hay permiso vigente
        # y sobre qué campos.
        "puede_editar": aprobada,
        "todos": aprobada and req.scope == "all",
        "element_ids": (
            [f.get("element_id") for f in (req.fields or [])]
            if aprobada and req.scope == "fields" else []
        ),
    }


@router.get("/mine/avisos/pendientes")
def mis_avisos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permisos aprobados que este usuario todavía no ha usado.

    Es lo que alimenta la insignia del Home. Se eligieron los APROBADOS y no
    "lo resuelto últimamente" a propósito: un permiso sin usar es algo que la
    persona tiene pendiente de hacer, y desaparece solo cuando lo gasta. Un
    aviso de rechazo, en cambio, no tiene nada que hacer y se quedaría ahí
    hasta que alguien inventara un "marcar como visto". De los rechazos ya
    avisa el correo.
    """
    reqs = (
        db.query(ResponseEditRequest)
        .filter(
            ResponseEditRequest.requester_id == current_user.id,
            ResponseEditRequest.status == "approved",
        )
        .order_by(ResponseEditRequest.reviewed_at.desc())
        .all()
    )

    salida = []
    for r in reqs:
        form = db.query(Form).filter(Form.id == r.form_id).first()
        salida.append({
            "id": r.id,
            "response_id": r.response_id,
            "form_id": r.form_id,
            "form_title": form.title if form else f"Formato #{r.form_id}",
            "scope": r.scope,
            "campos": [
                (f.get("label") or f.get("element_id")) for f in (r.fields or [])
            ],
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "review_message": r.review_message,
        })
    return {"count": len(salida), "avisos": salida}


@router.post("/{request_id}/cancelar")
def cancelar(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """El usuario se arrepintió. Libera el cupo para poder pedir otra cosa."""
    req = db.query(ResponseEditRequest).filter(ResponseEditRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if req.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="No es tu solicitud")
    if req.status not in VIVOS:
        raise HTTPException(status_code=409, detail="Esa solicitud ya está cerrada")

    req.status = "cancelled"
    db.commit()
    return {"ok": True}


@router.post("/{request_id}/usar")
def marcar_usada(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cierra el permiso tras guardar la corrección.

    Lo llama la pantalla al terminar de editar. Es lo que hace que la
    autorización sea de un solo uso: si no se llamara, el permiso quedaría
    abierto para siempre.
    """
    req = db.query(ResponseEditRequest).filter(ResponseEditRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if req.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="No es tu solicitud")
    if req.status != "approved":
        raise HTTPException(status_code=409, detail="Esa solicitud no está aprobada")

    req.status = "used"
    req.used_at = get_bogota_time()
    db.commit()
    logger.info("Solicitud de edición usada (id=%s, response=%s)", req.id, req.response_id)
    return {"ok": True}


def _avisar(db: Session, req: ResponseEditRequest, aprobada: bool) -> bool:
    """Le avisa por correo a quien pidió. Nunca levanta.

    Avisar no puede impedir resolver: cuando esto corre, el administrador ya
    decidió y eso está guardado. Si el correo falla, lo peor que pasa es que la
    persona se entera al volver a abrir la respuesta, como antes.
    """
    try:
        from app.api.controllers.edit_request_mail import avisar_solicitud_resuelta

        if not req.requester or not req.requester.email:
            return False

        form = db.query(Form).filter(Form.id == req.form_id).first()
        campos = [
            (f.get("label") or f.get("element_id"))
            for f in (req.fields or [])
        ]
        return avisar_solicitud_resuelta(
            to_email=req.requester.email,
            to_name=req.requester.name or "",
            form_title=form.title if form else "Safemetrics",
            response_id=req.response_id,
            aprobada=aprobada,
            campos=campos,
            todos=req.scope == "all",
            revisado_por=req.reviewer.name if req.reviewer else "",
            mensaje_admin=req.review_message,
        )
    except Exception:
        logger.warning(
            "No se pudo avisar de la solicitud %s", req.id, exc_info=True
        )
        return False


# ===========================================================================
# Lado del ADMINISTRADOR
# ===========================================================================

@router.get("/pending/count")
def contar_pendientes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Contador para la insignia del menú. Un no-admin siempre ve 0."""
    if not _es_admin(current_user):
        return {"count": 0}
    n = (
        db.query(ResponseEditRequest)
        .filter(ResponseEditRequest.status == "pending")
        .count()
    )
    return {"count": n}


@router.get("/pending")
def listar_pendientes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """La bandeja del administrador. Lo más viejo primero: lo que lleva más
    tiempo esperando es lo que más molesta a quien lo pidió."""
    if not _es_admin(current_user):
        raise HTTPException(status_code=403, detail="Solo para administradores")

    reqs = (
        db.query(ResponseEditRequest)
        .filter(ResponseEditRequest.status == "pending")
        .order_by(ResponseEditRequest.created_at.asc())
        .all()
    )
    return {"solicitudes": [_salida(r, con_formato=True) for r in reqs]}


@router.get("/history")
def historial(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lo ya resuelto. Es el rastro de quién autorizó qué y cuándo se usó.

    Importa especialmente porque una respuesta ya aprobada puede editarse y
    conservar su estado: sin este historial no habría manera de saber que algo
    aprobado cambió después.
    """
    if not _es_admin(current_user):
        raise HTTPException(status_code=403, detail="Solo para administradores")

    reqs = (
        db.query(ResponseEditRequest)
        .filter(ResponseEditRequest.status != "pending")
        .order_by(ResponseEditRequest.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return {"solicitudes": [_salida(r, con_formato=True) for r in reqs]}


@router.post("/{request_id}/aprobar")
def aprobar(
    request_id: int,
    payload: RevisarIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _es_admin(current_user):
        raise HTTPException(status_code=403, detail="Solo para administradores")

    req = db.query(ResponseEditRequest).filter(ResponseEditRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="Esa solicitud ya fue atendida")

    req.status = "approved"
    req.reviewed_by = current_user.id
    req.reviewed_at = get_bogota_time()
    req.review_message = (payload.review_message or "").strip() or None
    db.commit()
    db.refresh(req)

    avisado = _avisar(db, req, aprobada=True)

    logger.info(
        "Solicitud de edición aprobada (id=%s, response=%s, admin=%s, avisado=%s)",
        req.id, req.response_id, current_user.id, avisado,
    )
    # `avisado` viaja para que la bandeja pueda decir "aprobada, pero no salió
    # el correo" en vez de dar por hecho que la persona ya se enteró.
    return {"ok": True, "avisado": avisado, "solicitud": _salida(req, con_formato=True)}


@router.post("/{request_id}/rechazar")
def rechazar(
    request_id: int,
    payload: RevisarIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _es_admin(current_user):
        raise HTTPException(status_code=403, detail="Solo para administradores")

    req = db.query(ResponseEditRequest).filter(ResponseEditRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="Esa solicitud ya fue atendida")

    req.status = "rejected"
    req.reviewed_by = current_user.id
    req.reviewed_at = get_bogota_time()
    req.review_message = (payload.review_message or "").strip() or None
    db.commit()
    db.refresh(req)

    avisado = _avisar(db, req, aprobada=False)
    return {"ok": True, "avisado": avisado, "solicitud": _salida(req, con_formato=True)}


# ===========================================================================
# Campos disponibles para pedir
# ===========================================================================

@router.get("/campos/{response_id}")
def campos_de_la_respuesta(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Los campos del formato, para el selector de la solicitud.

    Sale del diseño y no de las answers: el usuario puede querer corregir un
    campo que dejó vacío, y ese no tiene answer que listar.
    """
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    if response.user_id != current_user.id and not _es_admin(current_user):
        raise HTTPException(status_code=403, detail="No es tu respuesta")

    form = db.query(Form).filter(Form.id == response.form_id).first()
    design = field_access.collect_design(form.form_design if form else [])

    # Agrupados por repetidor: en un formato con 30 campos, verlos sueltos y
    # mezclados con las columnas de una tabla no ayuda a elegir.
    etiqueta_rep = {r["id"]: r["label"] for r in design.repeaters}
    campos = [
        {
            "element_id": f["element_id"],
            "question_id": f["question_id"],
            "label": f["label"],
            "type": f["type"],
            "repeater_id": f["repeater_id"],
            "repeater_label": etiqueta_rep.get(f["repeater_id"]) if f["repeater_id"] else None,
        }
        for f in design.fields
    ]
    return {"campos": campos, "repetidores": design.repeaters}
