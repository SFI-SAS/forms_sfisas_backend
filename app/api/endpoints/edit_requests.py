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


def _tomar_foto(db: Session, response_id: int, form_id: int,
                element_ids: Optional[List[str]],
                etiquetas_pedidas: Optional[dict] = None) -> list:
    """Qué vale cada campo pedido, AHORA MISMO.

    `element_ids` None = todos los campos que tengan respuesta (alcance 'all').

    Lo que hace esto menos trivial de lo que parece: en un repetidor un campo
    NO tiene un valor, tiene uno POR FILA. Pedir "editar la hora de salida" en
    una asistencia de 40 trabajadores son 40 valores, y el administrador
    necesita verlos para saber cuál está mal.

    La fila se identifica por `repeater_row_index` y nunca por el orden en que
    llegan las answers: con huecos, el orden no corresponde a las filas.

    `etiquetas_pedidas` son los nombres que venían en la solicitud. Hacen falta
    para un caso real: un campo que YA NO ESTÁ en el diseño porque alguien
    editó el formato. Sus respuestas siguen ahí, pero el diseño no sabe cómo se
    llamaba, y sin esto el administrador vería un uuid.
    """
    from app.models import Answer

    form = db.query(Form).filter(Form.id == form_id).first()
    design = field_access.collect_design(form.form_design if form else [])

    etiquetas = {f["element_id"]: f["label"] for f in design.fields}
    repetidor = {f["element_id"]: f["repeater_id"] for f in design.fields}
    nombre_rep = {r["id"]: r["label"] for r in design.repeaters}
    # Los answers viejos pueden no traer form_design_element_id; por eso se
    # guarda también el camino por question_id.
    por_pregunta = {}
    for f in design.fields:
        if isinstance(f.get("question_id"), int):
            por_pregunta.setdefault(f["question_id"], f["element_id"])

    answers = db.query(Answer).filter(Answer.response_id == response_id).all()

    # Nombre de la pregunta, para los campos que YA NO están en el diseño y que
    # tampoco venían en la solicitud: sin esto la bandeja mostraba un uuid
    # crudo, que no le dice nada a nadie. La respuesta sí sabe de qué pregunta
    # es, y la pregunta sabe cómo se llama.
    from app.models import Question
    qids = {a.question_id for a in answers if a.question_id}
    texto_pregunta = {}
    if qids:
        for q in db.query(Question).filter(Question.id.in_(qids)).all():
            texto_pregunta[q.id] = q.question_text
    nombre_por_elemento = {}
    for a in answers:
        el = a.form_design_element_id or por_pregunta.get(a.question_id)
        if el and el not in nombre_por_elemento and a.question_id in texto_pregunta:
            nombre_por_elemento[el] = texto_pregunta[a.question_id]

    agrupado: dict = {}
    for a in answers:
        el = a.form_design_element_id or por_pregunta.get(a.question_id)
        if not el:
            continue
        # Se agrupa TODO, no solo lo pedido: la foto lleva el formato completo
        # para dar contexto, y el filtro por lo pedido se aplica más abajo
        # marcando `pedido`, no descartando.
        agrupado.setdefault(el, []).append(a)

    # Se recorre el DISEÑO COMPLETO y en su orden, no solo lo pedido: el
    # administrador necesita ver el formato entero para ubicar el campo.
    # "Quiere cambiar la hora de salida" no dice nada; "la hora de salida de
    # Juan, que entró a las 6 y tiene registrada la salida a las 4" sí.
    #
    # Los campos NO pedidos viajan igual, marcados con `pedido: false`, para
    # que la pantalla los pinte en segundo plano.
    pedidos = set(element_ids) if element_ids is not None else None
    claves = [f["element_id"] for f in design.fields]

    # Answers de campos que ya no están en el diseño (alguien editó el formato
    # después de responder). Van al final: se perderían del todo si no.
    huerfanos = [el for el in agrupado.keys() if el not in etiquetas]
    claves = claves + sorted(huerfanos)

    foto = []
    for el in claves:
        grupo = agrupado.get(el, [])
        valores = [
            {
                "fila": a.repeater_row_index,
                "valor": (a.answer_text or ""),
            }
            for a in sorted(
                grupo,
                key=lambda x: (x.repeater_row_index is None, x.repeater_row_index or 0),
            )
        ]
        en_diseno = el in etiquetas
        # Sin alcance ('all') todo lo respondido cuenta como pedido.
        es_pedido = True if pedidos is None else (el in pedidos)

        # Un campo que ni se pidió ni tiene respuesta no aporta nada y solo
        # alarga la tarjeta. Los pedidos sí aparecen aunque estén vacíos: que
        # no tengan respuesta es justamente el dato.
        if not es_pedido and not valores:
            continue

        foto.append({
            "element_id": el,
            "pedido": es_pedido,
            # Diseño primero (es la fuente viva), luego lo que decía la
            # solicitud, y solo si no hay nada el uuid.
            # Diseño → lo que decía la solicitud → el nombre de la pregunta →
            # y solo si no hay nada, el uuid.
            "label": (
                etiquetas.get(el)
                or (etiquetas_pedidas or {}).get(el)
                or nombre_por_elemento.get(el)
                or el
            ),
            "repeater_id": repetidor.get(el),
            "repeater_label": nombre_rep.get(repetidor.get(el)) if repetidor.get(el) else None,
            # El administrador tiene que saber que está autorizando algo que ya
            # no está en el formato: puede ser justo la razón del problema.
            "en_diseno": en_diseno,
            "valores": valores,
        })
    return foto


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
        # Lo que valían los campos cuando se pidió. Es lo que el administrador
        # mira para decidir, y lo que deja constancia en el historial.
        "snapshot": req.snapshot or [],
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

    # La foto se toma AHORA, al pedir, no al atender: entre una cosa y otra la
    # respuesta puede cambiar, y después de la corrección ya no habría manera
    # de reconstruir cómo estaba.
    ids_pedidos = (
        [f.element_id for f in payload.fields] if payload.scope == "fields" else None
    )
    foto = _tomar_foto(
        db, payload.response_id, response.form_id, ids_pedidos,
        {f.element_id: f.label for f in payload.fields if f.label},
    )

    req = ResponseEditRequest(
        response_id=payload.response_id,
        form_id=response.form_id,
        requester_id=current_user.id,
        scope=payload.scope,
        fields=(
            [f.model_dump() for f in payload.fields] if payload.scope == "fields" else None
        ),
        snapshot=foto,
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
