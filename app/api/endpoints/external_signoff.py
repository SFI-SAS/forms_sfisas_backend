"""
Registro externo por enlace.

El caso que lo origina: el ingeniero a cargo de una obra diligencia "Asistencia
diaria", registra la salida de todos a las 4 y se va. Un trabajador se queda
hasta las 6:47. Ese trabajador NO tiene usuario en Safemetrics. Se le manda un
correo con un boton; al tocarlo se abre una pagina publica que captura la hora
del servidor y las coordenadas del navegador y las escribe en SU fila.

Dos mitades en este archivo:

  - PUBLICA (sin token de sesion): la abre el trabajador desde el correo. Se
    autentica con un token HMAC firmado sobre el id de la tarea, igual que el QR
    de verificacion del PDF (public_view.py). Sirve UNA sola vez y vence.

  - PRIVADA (con sesion): la usa el ingeniero para configurar el formato, pedir
    el registro de una fila y ver en que va.

Decision de diseno: lo que el trabajador confirma se guarda como un Answer
NORMAL en la respuesta del ingeniero. Por eso sale gratis en PDF, Excel,
"Consultar respuestas", aprobaciones y movil sin tocar ninguna de esas cinco
superficies. La autoria -quien lo registro, cuando, desde donde- vive en
response_external_tasks, no en el Answer.

La hora se guarda SIEMPRE, aunque el GPS falle. El dato que de verdad se
necesita es la hora; perderla porque el navegador nego la ubicacion seria peor
que quedarse sin coordenadas.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import field_access
from app.core.security import SECRET_KEY, get_current_user
from app.crud import get_bogota_time
from app.database import get_db
from app.models import (
    Answer,
    Form,
    FormExternalSignoff,
    Response,
    ResponseExternalTask,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ===========================================================================
# Token del enlace
# ===========================================================================
# Mismo esquema que el QR del PDF: HMAC sobre (id, timestamp). No guarda nada
# en BD porque la firma ya prueba que el enlace lo emitimos nosotros. Lo que
# SI se mira en BD es el estado: un enlace ya usado no vuelve a escribir.

_SIGNOFF_SECRET = hashlib.sha256(f"external-signoff-{SECRET_KEY}".encode()).digest()
# Tope duro del token. El vencimiento REAL es expires_at de la tarea (12h por
# defecto); esto es solo para que una firma no viva para siempre.
_TOKEN_TTL = 90 * 24 * 3600


def generate_signoff_token(task_id: int) -> str:
    ts = int(time.time())
    payload = struct.pack(">II", task_id, ts)
    sig = hmac.new(_SIGNOFF_SECRET, payload, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(payload + sig).rstrip(b"=").decode()


def verify_signoff_token(token: str) -> Optional[int]:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
        if len(raw) != 24:
            return None
        payload, sig_received = raw[:8], raw[8:]
        sig_expected = hmac.new(_SIGNOFF_SECRET, payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig_received, sig_expected):
            return None
        task_id, ts = struct.unpack(">II", payload)
        if time.time() - ts > _TOKEN_TTL:
            return None
        return task_id
    except Exception:
        return None


def build_signoff_link(task_id: int) -> str:
    """URL publica que va dentro del boton del correo."""
    base = os.getenv(
        "FRONTEND_URL", "https://safemetrics-sfi-dev.service.saferut.com"
    ).rstrip("/")
    return f"{base}/public/registro/{generate_signoff_token(task_id)}"


# ===========================================================================
# Schemas
# ===========================================================================

class SignoffConfigIn(BaseModel):
    is_enabled: bool = True
    repeater_id: Optional[str] = None
    email_element_id: str
    name_element_id: Optional[str] = None
    time_element_id: str
    location_element_id: Optional[str] = None
    # Condicion de fila: solo se puede pedir donde este campo valga uno de estos
    # valores. None = sin condicion.
    row_condition_element_id: Optional[str] = None
    row_condition_values: Optional[List[str]] = None
    trigger_mode: str = "on_demand"
    expires_hours: int = Field(default=12, ge=1, le=720)
    email_subject: Optional[str] = None
    action_label: str = "Registrar mi salida"


class RequestTaskIn(BaseModel):
    """El ingeniero pide el registro de una fila."""
    repeater_row_index: Optional[int] = None
    # Solo si la fila no trae correo y lo quiere escribir a mano.
    override_email: Optional[str] = None


class ConfirmIn(BaseModel):
    """Lo que manda la pagina publica al confirmar."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    # 'denied' | 'unavailable' | 'timeout' | 'unsupported'
    location_error: Optional[str] = None


# ===========================================================================
# Utilidades
# ===========================================================================

_VALID_LOCATION_ERRORS = {"denied", "unavailable", "timeout", "unsupported"}
_VALID_TRIGGERS = {"on_demand", "on_submit"}


def _config_of(db: Session, form_id: int) -> Optional[FormExternalSignoff]:
    return (
        db.query(FormExternalSignoff)
        .filter(
            FormExternalSignoff.form_id == form_id,
            FormExternalSignoff.is_enabled.is_(True),
        )
        .first()
    )


def _row_answers(db: Session, response_id: int, row_index: Optional[int]):
    """Los answers de UNA fila del repetidor (o los sueltos si no hay fila)."""
    q = db.query(Answer).filter(Answer.response_id == response_id)
    if row_index is None:
        return q.all()
    return q.filter(Answer.repeater_row_index == row_index).all()


def _value_of_element(answers, element_id: Optional[str], question_id=None) -> Optional[str]:
    """Busca el valor de un elemento del diseno dentro de un grupo de answers.

    Primero por form_design_element_id, que es lo correcto. Si no aparece
    (answers viejos que se guardaron sin el) cae al question_id.
    """
    if not element_id:
        return None
    for a in answers:
        if a.form_design_element_id == element_id:
            valor = (a.answer_text or "").strip()
            if valor:
                return valor
    if question_id is not None:
        for a in answers:
            if a.question_id == question_id:
                valor = (a.answer_text or "").strip()
                if valor:
                    return valor
    return None


def _fila_cumple(
    answers, config: FormExternalSignoff, design
) -> bool:
    """Decide si a esta fila se le puede pedir el registro.

    Sin condicion configurada, todas pasan. Con condicion, el valor de la fila
    tiene que estar entre los aceptados.

    Esta funcion es la AUTORIDAD. El boton de la pantalla se pinta con lo mismo,
    pero pintar no es autorizar: sin esta comprobacion, una peticion a mano le
    pediria el registro a cualquier fila.
    """
    element_id = config.row_condition_element_id
    if not element_id:
        return True

    valores = config.row_condition_values
    if isinstance(valores, str):
        try:
            valores = json.loads(valores)
        except (ValueError, TypeError):
            valores = None
    if not valores:
        # Campo elegido pero sin valores marcados: es una condicion a medio
        # hacer. Se trata como "sin condicion" en vez de bloquear todo, que
        # dejaria el formato inservible sin que nadie entienda por que.
        return True

    actual = _value_of_element(
        answers, element_id, design.question_of_element.get(element_id)
    )
    if actual is None:
        return False

    # Comparacion tolerante: el valor guardado puede venir con espacios o con
    # otra caja que el de las opciones del diseno.
    actual_norm = actual.strip().casefold()
    return any(str(v).strip().casefold() == actual_norm for v in valores)


def _can_manage_response(response: Response, user: User) -> bool:
    """Quien puede pedir un registro externo: el dueno de la respuesta, o
    admin/creator. Mismo criterio que el resto de endpoints de answers."""
    if response.user_id == user.id:
        return True
    return getattr(user.user_type, "name", None) in ("admin", "creator")


def _write_answer(
    db: Session,
    *,
    response_id: int,
    question_id: Optional[int],
    element_id: Optional[str],
    repeater_id: Optional[str],
    row_index: Optional[int],
    value: str,
) -> bool:
    """Escribe (o corrige) el dato en la fila. Devuelve False si no hay donde.

    Busca primero por el elemento del diseno; si no existe la answer, la crea.
    Se corrige en vez de duplicar: una fila no puede terminar con dos horas de
    salida distintas.
    """
    if question_id is None or not element_id:
        return False

    existing = (
        db.query(Answer)
        .filter(
            Answer.response_id == response_id,
            Answer.form_design_element_id == element_id,
            Answer.repeater_row_index == row_index,
        )
        .first()
    )
    if existing is None:
        existing = (
            db.query(Answer)
            .filter(
                Answer.response_id == response_id,
                Answer.question_id == question_id,
                Answer.repeater_row_index == row_index,
            )
            .first()
        )

    if existing is not None:
        existing.answer_text = value
        if not existing.form_design_element_id:
            existing.form_design_element_id = element_id
        return True

    db.add(
        Answer(
            response_id=response_id,
            question_id=question_id,
            answer_text=value,
            form_design_element_id=element_id,
            repeated_id=repeater_id,
            repeater_row_index=row_index,
        )
    )
    return True


def _expire_if_due(db: Session, task: ResponseExternalTask) -> bool:
    """Marca la tarea como vencida si se le paso la hora. True = ya no sirve."""
    if task.status != "pending":
        return task.status != "pending"
    ahora = get_bogota_time()
    vence = task.expires_at
    if vence is not None and vence.tzinfo is None:
        from datetime import timezone as _tz
        vence = vence.replace(tzinfo=_tz.utc)
    if vence is not None and ahora > vence:
        task.status = "expired"
        db.commit()
        return True
    return False


def _create_task(
    db: Session,
    *,
    response: Response,
    config: FormExternalSignoff,
    design,
    row_index: Optional[int],
    email: str,
    name: Optional[str],
    requested_by_user_id: Optional[int],
) -> ResponseExternalTask:
    """Crea la solicitud, o reusa la que ya estuviera viva para esa fila.

    Reusar en vez de duplicar es lo que hace que "reenviar" no llene el buzon
    del trabajador de enlaces distintos que apuntan al mismo sitio.
    """
    viva = (
        db.query(ResponseExternalTask)
        .filter(
            ResponseExternalTask.response_id == response.id,
            ResponseExternalTask.repeater_row_index == row_index,
            ResponseExternalTask.time_element_id == config.time_element_id,
            ResponseExternalTask.status == "pending",
        )
        .first()
    )

    vence = get_bogota_time() + timedelta(hours=config.expires_hours or 12)

    if viva is not None:
        # Se refresca el vencimiento y el destinatario: si el ingeniero corrigio
        # el correo de la fila, el reenvio debe irse al nuevo.
        viva.expires_at = vence
        viva.recipient_email = email
        viva.recipient_name = name
        db.commit()
        db.refresh(viva)
        return viva

    task = ResponseExternalTask(
        response_id=response.id,
        form_id=response.form_id,
        repeater_id=config.repeater_id,
        repeater_row_index=row_index,
        recipient_email=email,
        recipient_name=name,
        time_element_id=config.time_element_id,
        time_question_id=design.question_of_element.get(config.time_element_id),
        location_element_id=config.location_element_id,
        location_question_id=(
            design.question_of_element.get(config.location_element_id)
            if config.location_element_id
            else None
        ),
        status="pending",
        requested_by_user_id=requested_by_user_id,
        expires_at=vence,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _send_task_email(db: Session, task: ResponseExternalTask) -> bool:
    """Manda el correo de la tarea. Nunca revienta: si el SMTP falla, la tarea
    queda creada y el ingeniero puede reenviar."""
    from app.api.controllers.external_signoff_mail import send_external_signoff_email

    form = db.query(Form).filter(Form.id == task.form_id).first()
    config = db.query(FormExternalSignoff).filter(
        FormExternalSignoff.form_id == task.form_id
    ).first()
    solicitante = (
        db.query(User).filter(User.id == task.requested_by_user_id).first()
        if task.requested_by_user_id
        else None
    )

    vence_txt = None
    if task.expires_at:
        try:
            vence_txt = task.expires_at.strftime("%d/%m/%Y a las %H:%M")
        except Exception:
            vence_txt = None

    ok = send_external_signoff_email(
        to_email=task.recipient_email,
        to_name=task.recipient_name or "",
        form_title=form.title if form else "Safemetrics",
        requested_by_name=solicitante.name if solicitante else "El responsable del formato",
        link=build_signoff_link(task.id),
        action_label=(config.action_label if config else None) or "Registrar mi salida",
        subject_text=(config.email_subject if config else None),
        expires_text=vence_txt,
    )
    if ok and not task.email_sent:
        task.email_sent = True
        db.commit()
    return ok


# ===========================================================================
# PUBLICO - lo que abre el trabajador desde el correo
# ===========================================================================

@router.get("/registro/{token}")
def public_signoff_info(token: str, db: Session = Depends(get_db)):
    """Datos para pintar la pagina publica. No escribe nada.

    Devuelve siempre 200 con un estado legible salvo que el token sea basura:
    la pagina tiene que poder decir "esto ya se registro" o "este enlace
    vencio" en vez de mostrar un error crudo.
    """
    task_id = verify_signoff_token(token)
    if task_id is None:
        raise HTTPException(status_code=404, detail="Enlace invalido")

    task = db.query(ResponseExternalTask).filter(ResponseExternalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Enlace invalido")

    _expire_if_due(db, task)

    form = db.query(Form).filter(Form.id == task.form_id).first()
    config = db.query(FormExternalSignoff).filter(
        FormExternalSignoff.form_id == task.form_id
    ).first()
    solicitante = (
        db.query(User).filter(User.id == task.requested_by_user_id).first()
        if task.requested_by_user_id
        else None
    )

    return {
        "status": task.status,
        "nombre": task.recipient_name or "",
        "formato": form.title if form else "",
        "solicitado_por": solicitante.name if solicitante else "",
        "accion": (config.action_label if config else None) or "Registrar mi salida",
        "pide_ubicacion": bool(task.location_element_id),
        "vence": task.expires_at.isoformat() if task.expires_at else None,
        # Solo cuando ya se registro, para poder mostrarselo si vuelve a abrir.
        "hora_registrada": task.confirmed_time,
        "ubicacion_registrada": task.confirmed_location,
    }


@router.post("/registro/{token}/confirmar")
def public_signoff_confirm(
    token: str,
    payload: ConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Graba la hora (y la ubicacion si la hubo) en la fila del trabajador.

    La hora la pone el SERVIDOR, no el celular: la del celular se cambia a mano
    en dos toques.

    Si el GPS fallo, se graba la hora igual y queda constancia del motivo. El
    dato que se necesita es la hora.
    """
    task_id = verify_signoff_token(token)
    if task_id is None:
        raise HTTPException(status_code=404, detail="Enlace invalido")

    task = db.query(ResponseExternalTask).filter(ResponseExternalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Enlace invalido")

    if _expire_if_due(db, task):
        if task.status == "done":
            raise HTTPException(
                status_code=409,
                detail="Este registro ya se hizo. No hay nada mas que hacer.",
            )
        if task.status == "cancelled":
            raise HTTPException(
                status_code=409, detail="Esta solicitud fue cancelada."
            )
        raise HTTPException(
            status_code=410,
            detail="Este enlace vencio. Pidele al responsable que te lo mande otra vez.",
        )

    response = db.query(Response).filter(Response.id == task.response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="La respuesta ya no existe")

    ahora = get_bogota_time()
    hora_txt = ahora.strftime("%H:%M")

    escrito = _write_answer(
        db,
        response_id=task.response_id,
        question_id=task.time_question_id,
        element_id=task.time_element_id,
        repeater_id=task.repeater_id,
        row_index=task.repeater_row_index,
        value=hora_txt,
    )
    if not escrito:
        logger.error(
            "Registro externo sin destino para la hora (task=%s): el campo ya no "
            "existe en el formato", task.id
        )
        raise HTTPException(
            status_code=422,
            detail="El formato cambio y ya no tiene donde guardar la hora. "
                   "Avisale al responsable.",
        )

    ubicacion_txt = None
    error_ubicacion = None
    if payload.latitude is not None and payload.longitude is not None:
        # Mismo formato que el campo location del sistema: "lat, lng" con 6
        # decimales. Si se guarda distinto, no se puede comparar ni mapear.
        ubicacion_txt = f"{payload.latitude:.6f}, {payload.longitude:.6f}"
        if task.location_element_id:
            _write_answer(
                db,
                response_id=task.response_id,
                question_id=task.location_question_id,
                element_id=task.location_element_id,
                repeater_id=task.repeater_id,
                row_index=task.repeater_row_index,
                value=ubicacion_txt,
            )
    else:
        error_ubicacion = payload.location_error
        if error_ubicacion not in _VALID_LOCATION_ERRORS:
            error_ubicacion = "unavailable"

    task.status = "done"
    task.confirmed_at = ahora
    task.confirmed_time = hora_txt
    task.confirmed_location = ubicacion_txt
    task.location_error = error_ubicacion
    task.client_ip = (request.client.host if request.client else None)
    task.user_agent = request.headers.get("user-agent")

    db.commit()

    logger.info(
        "Registro externo confirmado (task=%s, response=%s, fila=%s, hora=%s, gps=%s)",
        task.id, task.response_id, task.repeater_row_index, hora_txt,
        "si" if ubicacion_txt else f"no ({error_ubicacion})",
    )

    return {
        "ok": True,
        "hora": hora_txt,
        "ubicacion": ubicacion_txt,
        "sin_ubicacion": error_ubicacion,
    }


# Cuanto tiempo despues de registrar la hora se sigue aceptando la ubicacion.
# Es la ventana de una MISMA visita a la pagina, no un permiso abierto: pasado
# esto, unas coordenadas ya no prueban donde estaba la persona a esa hora.
_VENTANA_UBICACION_TARDIA = timedelta(minutes=10)


@router.post("/registro/{token}/ubicacion")
def public_signoff_late_location(
    token: str,
    payload: ConfirmIn,
    db: Session = Depends(get_db),
):
    """Agrega la ubicacion a un registro cuya hora ya se guardo.

    Por que existe: el GPS de un celular puede tardar MUCHO. Medido en un
    telefono real, la primera coordenada llego a los 39 segundos. Esperarla
    antes de guardar la hora es apostar a que la persona no cierre la pagina;
    cortar el GPS a los 20s es botar una ubicacion que si iba a llegar.

    Asi que la pagina hace las dos cosas: a los 10 segundos guarda la hora
    -que es el dato que importa- y sigue esperando en segundo plano. Si las
    coordenadas aparecen, entran por aqui.

    Solo completa lo que quedo vacio: nunca pisa una ubicacion ya registrada.
    """
    task_id = verify_signoff_token(token)
    if task_id is None:
        raise HTTPException(status_code=404, detail="Enlace invalido")

    task = db.query(ResponseExternalTask).filter(ResponseExternalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Enlace invalido")

    if task.status != "done":
        raise HTTPException(
            status_code=409, detail="Este registro todavia no tiene hora"
        )
    if not task.location_element_id:
        raise HTTPException(
            status_code=422, detail="Este formato no guarda ubicacion"
        )
    if task.confirmed_location:
        # Ya la tiene. No es un error: la pagina puede reintentar.
        return {"ok": True, "ubicacion": task.confirmed_location, "ya_estaba": True}

    if payload.latitude is None or payload.longitude is None:
        raise HTTPException(status_code=422, detail="Faltan las coordenadas")

    ahora = get_bogota_time()
    confirmado = task.confirmed_at
    if confirmado is not None and confirmado.tzinfo is None:
        from datetime import timezone as _tz
        confirmado = confirmado.replace(tzinfo=_tz.utc)
    if confirmado is None or (ahora - confirmado) > _VENTANA_UBICACION_TARDIA:
        raise HTTPException(
            status_code=410,
            detail="Paso demasiado tiempo desde el registro de la hora",
        )

    ubicacion_txt = f"{payload.latitude:.6f}, {payload.longitude:.6f}"
    _write_answer(
        db,
        response_id=task.response_id,
        question_id=task.location_question_id,
        element_id=task.location_element_id,
        repeater_id=task.repeater_id,
        row_index=task.repeater_row_index,
        value=ubicacion_txt,
    )
    task.confirmed_location = ubicacion_txt
    task.location_error = None
    db.commit()

    logger.info(
        "Registro externo: ubicacion tardia agregada (task=%s, %ss despues)",
        task.id, int((ahora - confirmado).total_seconds()),
    )
    return {"ok": True, "ubicacion": ubicacion_txt, "ya_estaba": False}


# ===========================================================================
# PRIVADO - configuracion del formato
# ===========================================================================

@router.get("/config/{form_id}")
def get_signoff_config(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """La config del formato, mas los campos candidatos para poblar los selects.

    Los candidatos salen del diseno vivo, no de una lista guardada: si el
    formato cambio, la pantalla tiene que reflejarlo.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    design = field_access.collect_design(form.form_design)
    campos = [
        {
            "element_id": f["element_id"],
            "question_id": f["question_id"],
            "label": f["label"],
            "type": f["type"],
            "repeater_id": f["repeater_id"],
        }
        for f in design.fields
    ]

    row = (
        db.query(FormExternalSignoff)
        .filter(FormExternalSignoff.form_id == form_id)
        .first()
    )

    return {
        "configurado": row is not None,
        "config": None if row is None else {
            "is_enabled": row.is_enabled,
            "repeater_id": row.repeater_id,
            "email_element_id": row.email_element_id,
            "name_element_id": row.name_element_id,
            "time_element_id": row.time_element_id,
            "location_element_id": row.location_element_id,
            "row_condition_element_id": row.row_condition_element_id,
            "row_condition_values": row.row_condition_values or [],
            "trigger_mode": row.trigger_mode,
            "expires_hours": row.expires_hours,
            "email_subject": row.email_subject,
            "action_label": row.action_label,
        },
        "repetidores": design.repeaters,
        "campos": campos,
    }


@router.put("/config/{form_id}")
def save_signoff_config(
    form_id: int,
    payload: SignoffConfigIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Guarda la config. Solo el dueno del formato o admin/creator."""
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formato no encontrado")

    if not (
        form.user_id == current_user.id
        or getattr(current_user.user_type, "name", None) in ("admin", "creator")
    ):
        raise HTTPException(status_code=403, detail="Sin permiso sobre este formato")

    if payload.trigger_mode not in _VALID_TRIGGERS:
        raise HTTPException(status_code=422, detail="Modo de disparo invalido")

    design = field_access.collect_design(form.form_design)
    validos = set(design.question_of_element.keys())

    # Si el campo no existe en el diseno, la solicitud nunca tendria donde
    # escribir. Se atrapa aqui y no seis horas despues, cuando el trabajador
    # toque el boton y no pase nada.
    for etiqueta, element_id in (
        ("correo", payload.email_element_id),
        ("hora", payload.time_element_id),
    ):
        if element_id not in validos:
            raise HTTPException(
                status_code=422,
                detail=f"El campo de {etiqueta} no existe en el diseno del formato",
            )
    for etiqueta, element_id in (
        ("nombre", payload.name_element_id),
        ("ubicacion", payload.location_element_id),
        ("la condicion", payload.row_condition_element_id),
    ):
        if element_id and element_id not in validos:
            raise HTTPException(
                status_code=422,
                detail=f"El campo de {etiqueta} no existe en el diseno del formato",
            )

    row = (
        db.query(FormExternalSignoff)
        .filter(FormExternalSignoff.form_id == form_id)
        .first()
    )
    if row is None:
        row = FormExternalSignoff(form_id=form_id)
        db.add(row)

    row.is_enabled = payload.is_enabled
    row.repeater_id = payload.repeater_id
    row.email_element_id = payload.email_element_id
    row.name_element_id = payload.name_element_id
    row.time_element_id = payload.time_element_id
    row.location_element_id = payload.location_element_id
    row.row_condition_element_id = payload.row_condition_element_id
    # Sin campo no hay condicion: se limpian tambien los valores para no dejar
    # una condicion huerfana que reaparezca si alguien vuelve a elegir campo.
    row.row_condition_values = (
        list(payload.row_condition_values or [])
        if payload.row_condition_element_id else None
    )
    row.trigger_mode = payload.trigger_mode
    row.expires_hours = payload.expires_hours
    row.email_subject = payload.email_subject
    row.action_label = payload.action_label or "Registrar mi salida"

    db.commit()
    return {"ok": True}


# ===========================================================================
# PRIVADO - pedir y seguir las solicitudes
# ===========================================================================

def _task_out(task: ResponseExternalTask) -> dict:
    return {
        "id": task.id,
        "repeater_row_index": task.repeater_row_index,
        "email": task.recipient_email,
        "nombre": task.recipient_name,
        "status": task.status,
        "requested_at": task.requested_at.isoformat() if task.requested_at else None,
        "expires_at": task.expires_at.isoformat() if task.expires_at else None,
        "email_sent": task.email_sent,
        "confirmed_at": task.confirmed_at.isoformat() if task.confirmed_at else None,
        "hora": task.confirmed_time,
        "ubicacion": task.confirmed_location,
        "sin_ubicacion": task.location_error,
    }


@router.get("/tasks/{response_id}")
def list_response_tasks(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """En que va cada solicitud de esta respuesta, fila por fila."""
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    if not _can_manage_response(response, current_user):
        raise HTTPException(status_code=403, detail="Sin permiso sobre esta respuesta")

    tasks = (
        db.query(ResponseExternalTask)
        .filter(ResponseExternalTask.response_id == response_id)
        .order_by(ResponseExternalTask.id.asc())
        .all()
    )
    for t in tasks:
        _expire_if_due(db, t)

    config = _config_of(db, response.form_id)
    if config is None:
        return {"habilitado": False, "repeater_id": None, "tasks": [], "filas": []}

    # Las filas se arman AQUI y no en el navegador: el servidor ya sabe cual
    # columna trae el correo y cual la hora, y recorrer el diseno otra vez del
    # lado del cliente seria duplicar esa logica en un segundo sitio donde se
    # va a desincronizar.
    form = db.query(Form).filter(Form.id == response.form_id).first()
    design = field_access.collect_design(form.form_design if form else [])
    email_qid = design.question_of_element.get(config.email_element_id)
    name_qid = (
        design.question_of_element.get(config.name_element_id)
        if config.name_element_id else None
    )
    time_qid = design.question_of_element.get(config.time_element_id)

    answers = db.query(Answer).filter(Answer.response_id == response_id).all()
    por_fila: dict = {}
    for a in answers:
        por_fila.setdefault(a.repeater_row_index, []).append(a)

    task_por_fila = {}
    for t in tasks:
        # La ULTIMA de cada fila es la que manda: si una vencio y se volvio a
        # pedir, lo que el ingeniero tiene que ver es la nueva.
        task_por_fila[t.repeater_row_index] = t

    filas = []
    for row_index, grupo in sorted(
        por_fila.items(), key=lambda kv: (kv[0] is None, kv[0])
    ):
        # Con repetidor, los campos sueltos (row_index None) no son una fila.
        if config.repeater_id and row_index is None:
            continue

        correo = _value_of_element(grupo, config.email_element_id, email_qid)
        cumple = _fila_cumple(grupo, config, design)
        t = task_por_fila.get(row_index)
        filas.append({
            "repeater_row_index": row_index,
            "nombre": _value_of_element(grupo, config.name_element_id, name_qid),
            "correo": correo,
            # Lo que hay HOY en la columna de hora: si ya tiene algo, a esa fila
            # no hay nada que pedirle.
            "hora_actual": _value_of_element(grupo, config.time_element_id, time_qid),
            # Si la fila pasa la condicion ("Requiere quedarse = Si").
            "cumple_condicion": cumple,
            "puede_pedirse": bool(correo and "@" in correo) and cumple,
            "task": _task_out(t) if t else None,
        })

    return {
        "habilitado": True,
        "repeater_id": config.repeater_id,
        "tiene_condicion": bool(config.row_condition_element_id),
        "trigger_mode": config.trigger_mode,
        "expires_hours": config.expires_hours,
        "tasks": [_task_out(t) for t in tasks],
        "filas": filas,
    }


@router.post("/tasks/{response_id}")
def request_signoff(
    response_id: int,
    payload: RequestTaskIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """El ingeniero pide el registro de una fila. Crea la tarea y manda el correo."""
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    if not _can_manage_response(response, current_user):
        raise HTTPException(status_code=403, detail="Sin permiso sobre esta respuesta")

    config = _config_of(db, response.form_id)
    if config is None:
        raise HTTPException(
            status_code=422,
            detail="Este formato no tiene configurado el registro externo",
        )

    # Con repetidor SIEMPRE hay que decir de que fila se trata. Sin esto se
    # leerian los answers de la respuesta entera y podria salir el correo de
    # otro trabajador.
    if config.repeater_id and payload.repeater_row_index is None:
        raise HTTPException(
            status_code=422,
            detail="Falta indicar la fila del repetidor",
        )

    form = db.query(Form).filter(Form.id == response.form_id).first()
    design = field_access.collect_design(form.form_design if form else [])

    answers = _row_answers(db, response_id, payload.repeater_row_index)

    # La condicion se comprueba AQUI, no solo en la pantalla. El boton por fila
    # lo pinta el navegador; esto es lo que impide que una peticion a mano le
    # pida el registro a una fila que marco que NO se queda.
    if not _fila_cumple(answers, config, design):
        raise HTTPException(
            status_code=422,
            detail="Esa fila no cumple la condicion configurada para el registro externo",
        )

    email = (payload.override_email or "").strip() or _value_of_element(
        answers,
        config.email_element_id,
        design.question_of_element.get(config.email_element_id),
    )
    if not email or "@" not in email:
        raise HTTPException(
            status_code=422,
            detail="Esa fila no tiene un correo valido en el campo configurado",
        )

    nombre = _value_of_element(
        answers,
        config.name_element_id,
        design.question_of_element.get(config.name_element_id)
        if config.name_element_id
        else None,
    )

    task = _create_task(
        db,
        response=response,
        config=config,
        design=design,
        row_index=payload.repeater_row_index,
        email=email,
        name=nombre,
        requested_by_user_id=current_user.id,
    )

    enviado = _send_task_email(db, task)
    return {"ok": True, "enviado": enviado, "task": _task_out(task)}


@router.post("/tasks/{task_id}/reenviar")
def resend_signoff(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reenvia el correo de una solicitud viva, refrescandole el vencimiento."""
    task = db.query(ResponseExternalTask).filter(ResponseExternalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    response = db.query(Response).filter(Response.id == task.response_id).first()
    if not response or not _can_manage_response(response, current_user):
        raise HTTPException(status_code=403, detail="Sin permiso sobre esta respuesta")

    if task.status == "done":
        raise HTTPException(status_code=409, detail="Ese registro ya se hizo")

    config = _config_of(db, task.form_id)
    horas = config.expires_hours if config else 12
    task.status = "pending"
    task.expires_at = get_bogota_time() + timedelta(hours=horas or 12)
    db.commit()

    enviado = _send_task_email(db, task)
    return {"ok": True, "enviado": enviado, "task": _task_out(task)}


@router.post("/tasks/{task_id}/cancelar")
def cancel_signoff(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mata el enlace. Se usa cuando el ingeniero prefiere escribir la hora el."""
    task = db.query(ResponseExternalTask).filter(ResponseExternalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    response = db.query(Response).filter(Response.id == task.response_id).first()
    if not response or not _can_manage_response(response, current_user):
        raise HTTPException(status_code=403, detail="Sin permiso sobre esta respuesta")

    if task.status == "done":
        raise HTTPException(status_code=409, detail="Ese registro ya se hizo")

    task.status = "cancelled"
    db.commit()
    return {"ok": True, "task": _task_out(task)}


# ===========================================================================
# Disparo automatico al enviar la respuesta
# ===========================================================================

@router.post("/dispatch/{response_id}")
def dispatch_endpoint(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dispara el modo 'al enviar el formato'. Lo llama el frontend al terminar.

    Por que hace falta un endpoint y no basta un gancho en el backend: al
    diligenciar, el frontend guarda las answers llamando a /save-answers UNA VEZ
    POR CAMPO y en paralelo. No hay ningun momento, del lado del servidor, en
    que se sepa que la respuesta ya esta completa: cada llamada ve una respuesta
    a medio llenar, y disparar ahi leeria una fila sin correo todavia.

    El unico que sabe cuando termino es quien envio: por eso lo llama el cliente
    despues de su `Promise.all`.

    Es idempotente: si se llama dos veces, `_create_task` reusa la solicitud viva
    en vez de crear otra, asi que no se duplican correos.
    """
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Respuesta no encontrada")
    if not _can_manage_response(response, current_user):
        raise HTTPException(status_code=403, detail="Sin permiso sobre esta respuesta")

    enviadas = dispatch_on_submit(db, response_id)
    return {"ok": True, "enviadas": enviadas}



def dispatch_on_submit(db: Session, response_id: int) -> int:
    """Manda la solicitud a toda fila con el campo de hora vacio.

    Se llama desde el guardado de respuestas cuando el formato esta en modo
    'on_submit'. Devuelve cuantas solicitudes salieron.

    NUNCA levanta: si esto falla, la respuesta ya se guardo y no se puede tumbar
    un envio por un correo. Se registra y se sigue.
    """
    try:
        response = db.query(Response).filter(Response.id == response_id).first()
        if not response:
            return 0

        config = _config_of(db, response.form_id)
        if config is None or config.trigger_mode != "on_submit":
            return 0

        form = db.query(Form).filter(Form.id == response.form_id).first()
        design = field_access.collect_design(form.form_design if form else [])

        email_qid = design.question_of_element.get(config.email_element_id)
        name_qid = (
            design.question_of_element.get(config.name_element_id)
            if config.name_element_id
            else None
        )
        time_qid = design.question_of_element.get(config.time_element_id)

        todas = db.query(Answer).filter(Answer.response_id == response_id).all()

        # Agrupar por fila. Sin repetidor hay una sola "fila" (None).
        filas = {}
        for a in todas:
            filas.setdefault(a.repeater_row_index, []).append(a)

        enviadas = 0
        for row_index, answers in filas.items():
            # Con repetidor, los campos sueltos no son una fila.
            if config.repeater_id and row_index is None:
                continue

            # Si ya tiene hora, no se le pide nada a nadie.
            if _value_of_element(answers, config.time_element_id, time_qid):
                continue

            # La condicion vale igual en el envio automatico: si no, el modo
            # "al enviar el formato" le escribiria a los 40 trabajadores en vez
            # de a los dos que se quedan.
            if not _fila_cumple(answers, config, design):
                continue

            email = _value_of_element(answers, config.email_element_id, email_qid)
            if not email or "@" not in email:
                continue

            # Si a esa fila ya se le mando y sigue esperando, no se le vuelve a
            # escribir. El disparo automatico puede correr dos veces —un
            # reintento del cliente, un reenvio del formato— y al trabajador le
            # llegarian dos correos identicos. La tarea no se duplicaba (se
            # reusa la viva), pero el correo si volvia a salir.
            ya_pendiente = (
                db.query(ResponseExternalTask)
                .filter(
                    ResponseExternalTask.response_id == response_id,
                    ResponseExternalTask.repeater_row_index == row_index,
                    ResponseExternalTask.time_element_id == config.time_element_id,
                    ResponseExternalTask.status == "pending",
                )
                .first()
            )
            if ya_pendiente is not None:
                continue

            nombre = _value_of_element(answers, config.name_element_id, name_qid)

            task = _create_task(
                db,
                response=response,
                config=config,
                design=design,
                row_index=row_index,
                email=email,
                name=nombre,
                requested_by_user_id=response.user_id,
            )
            if _send_task_email(db, task):
                enviadas += 1

        if enviadas:
            logger.info(
                "Registro externo: %s solicitudes enviadas al enviar la respuesta %s",
                enviadas, response_id,
            )
        return enviadas
    except Exception:
        logger.exception(
            "Registro externo: fallo el disparo automatico de la respuesta %s",
            response_id,
        )
        return 0
