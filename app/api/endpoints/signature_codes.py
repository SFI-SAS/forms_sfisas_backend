"""
Firma por CÓDIGO, para quien no acepta el registro biométrico.

Por qué existe
--------------
Hoy para firmar hay que registrarse con la cara. Algunas personas no lo aceptan;
para ellas se registra nombre, cédula y correo, y se les manda un código de 6
dígitos que usarán al firmar.

Cómo encaja sin tocar lo facial
-------------------------------
El registro facial no tiene tabla propia: es una answer de una pregunta
`regisfacial` cuyo JSON lleva `person_id`, y de ahí sale el directorio de
firmantes. El alta por código escribe esa MISMA answer desde el cliente, con el
`person_id` que emite este módulo y `metodo: "codigo"`. Así la persona aparece
en el selector de firmantes como cualquier otra y no hubo que tocar el camino
biométrico.

El código es FIJO
-----------------
Se genera al registrar y se queda. No vence ni rota solo; solo un administrador
puede generar otro, que reemplaza al anterior. Se guarda con bcrypt: ni el
administrador ni este código pueden leerlo, únicamente se reenvía al correo.

La parte importante: quién da fe de la firma
--------------------------------------------
La firma facial de hoy se guarda tal como la manda el cliente, sin que el
servidor verifique nada (lo marcó la auditoría de julio). Aquí NO se repite ese
patrón: el cliente nunca decide que el código es correcto.

Pero al diligenciar la firma ocurre ANTES de que exista la respuesta —la
response nace al enviar el formato—, así que el servidor tampoco puede escribir
la answer en ese momento. La solución son dos pasos:

  1. `POST /verify` recibe el código, lo valida contra el hash y devuelve un
     COMPROBANTE firmado por el servidor (JWT corto), atado a esa persona, ese
     formato y ese campo.
  2. Al guardar las answers, el backend exige ese comprobante para aceptar
     cualquier firma con `metodo: "codigo"`.

Un cliente no puede fabricar el comprobante porque no tiene la llave. Y como
lleva el formato y el campo adentro, tampoco sirve para firmar otra cosa.
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.controllers.signature_code_mail import send_signature_code_email
from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.database import get_db
from app.models import SignatureCodeEvent, SignatureCodePerson, User, UserType

logger = logging.getLogger(__name__)
router = APIRouter()

# Un código de 6 dígitos que no cambia se adivina si se deja intentar sin freno:
# son un millón de combinaciones y quien lo intente no tiene prisa. El bloqueo
# por intentos es lo único que lo sostiene.
MAX_INTENTOS = 5
BLOQUEO_MINUTOS = 15

# El comprobante solo tiene que sobrevivir entre "digité el código" y "envié el
# formato". Que sea corto limita el daño si alguien lo captura.
COMPROBANTE_MINUTOS = 20
COMPROBANTE_TIPO = "signature_code_proof"


# ── Entradas y salidas ───────────────────────────────────────────────────────

class RegistrarPersonaIn(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=255)
    document: str = Field(..., min_length=3, max_length=50)
    email: EmailStr


class PersonaOut(BaseModel):
    person_id: str
    full_name: str
    document: str
    email: str          # enmascarado para quien no es admin
    is_active: bool
    code_generated_at: Optional[str] = None
    locked: bool = False


class VerificarCodigoIn(BaseModel):
    person_id: str
    code: str = Field(..., min_length=6, max_length=6)
    form_id: int
    form_design_element_id: str
    repeater_row_index: Optional[int] = None


# ── Utilidades ───────────────────────────────────────────────────────────────

def _generar_codigo() -> str:
    """6 dígitos con aleatoriedad criptográfica; se permite el que empieza en 0."""
    return f"{secrets.randbelow(1000000):06d}"


def _enmascarar(email: str) -> str:
    """a***@empresa.com — suficiente para reconocerlo sin exponerlo."""
    try:
        usuario, dominio = email.split("@", 1)
        visible = usuario[0] if usuario else ""
        return f"{visible}{'*' * max(len(usuario) - 1, 1)}@{dominio}"
    except ValueError:
        return "***"


def _ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _registrar_evento(
    db: Session,
    *,
    person_id: str,
    event: str,
    request: Optional[Request] = None,
    user: Optional[User] = None,
    detail: Optional[str] = None,
    response_id: Optional[int] = None,
    element_id: Optional[str] = None,
    row_index: Optional[int] = None,
) -> None:
    """Deja el rastro. Nunca interrumpe la operación: un fallo de auditoría no
    puede impedir que alguien firme, pero sí queda en el log del servidor."""
    try:
        db.add(SignatureCodeEvent(
            person_id=person_id,
            event=event,
            response_id=response_id,
            form_design_element_id=element_id,
            repeater_row_index=row_index,
            acted_by_user_id=user.id if user else None,
            client_ip=_ip(request) if request else None,
            user_agent=(request.headers.get("user-agent") or "")[:500] if request else None,
            detail=detail,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "No se pudo registrar el evento de firma por codigo",
            extra={"event": "signature_code_event_fail"},
        )


def _salida(persona: SignatureCodePerson, *, es_admin: bool) -> PersonaOut:
    ahora = datetime.now(timezone.utc)
    return PersonaOut(
        person_id=persona.person_id,
        full_name=persona.full_name,
        document=persona.document,
        email=persona.email if es_admin else _enmascarar(persona.email),
        is_active=persona.is_active,
        code_generated_at=(
            persona.code_generated_at.isoformat() if persona.code_generated_at else None
        ),
        locked=bool(persona.locked_until and persona.locked_until > ahora),
    )


def emitir_comprobante(
    *, person_id: str, form_id: int, element_id: str, row_index: Optional[int]
) -> str:
    """JWT corto que dice: el servidor vio el código correcto de esta persona
    para este campo de este formato."""
    ahora = datetime.now(timezone.utc)
    payload = {
        "typ": COMPROBANTE_TIPO,
        "sub": person_id,
        "form_id": form_id,
        "el": element_id,
        "row": row_index,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=COMPROBANTE_MINUTOS),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def comprobante_valido(
    token: str,
    *,
    person_id: str,
    form_id: Optional[int] = None,
    element_id: Optional[str] = None,
) -> bool:
    """Lo usa el guardado de answers antes de aceptar una firma por código."""
    if not token:
        return False
    try:
        datos = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return False

    if datos.get("typ") != COMPROBANTE_TIPO:
        return False
    if datos.get("sub") != person_id:
        return False
    if form_id is not None and datos.get("form_id") != form_id:
        return False
    if element_id is not None and datos.get("el") != element_id:
        return False
    return True


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/persons", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
def registrar_persona(
    datos: RegistrarPersonaIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registra a alguien que firmará con código y le manda el suyo.

    Lo puede hacer cualquiera que esté diligenciando, igual que hoy cualquiera
    puede registrar facialmente a otro trabajador.
    """
    documento = datos.document.strip()
    correo = str(datos.email).strip().lower()

    existente = (
        db.query(SignatureCodePerson)
        .filter(SignatureCodePerson.document == documento)
        .first()
    )
    if existente:
        # No es un error del que haya que recuperarse: esa persona ya puede
        # firmar. Se devuelve quién es para que el cliente la ofrezca.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Esa cedula ya esta registrada para firmar con codigo",
                "person_id": existente.person_id,
                "full_name": existente.full_name,
            },
        )

    codigo = _generar_codigo()
    nombre = datos.full_name.strip()

    # El correo va PRIMERO, y la persona solo se crea si salió.
    #
    # El código únicamente existe en dos sitios: ese correo y su hash. Si se
    # registrara a alguien cuyo correo falló, quedaría un firmante que no puede
    # firmar y que nadie puede desatascar salvo generándole otro código. Es
    # preferible no registrarlo: quien está en campo repite el alta y listo.
    if not send_signature_code_email(email=correo, name=nombre, code=codigo):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "No se pudo enviar el codigo al correo, asi que la persona NO "
                "quedo registrada. Revise que el correo este bien escrito e "
                "intentelo de nuevo."
            ),
        )

    persona = SignatureCodePerson(
        person_id=f"cod-{uuid.uuid4().hex[:16]}",
        full_name=nombre,
        document=documento,
        email=correo,
        code_hash=hash_password(codigo),
        code_generated_by_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)

    _registrar_evento(
        db,
        person_id=persona.person_id,
        event="code_generated",
        request=request,
        user=current_user,
        detail="alta",
    )

    return _salida(persona, es_admin=False)


@router.get("/persons", response_model=list[PersonaOut])
def listar_personas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Quiénes firman con código.

    Mismo criterio de acceso que el directorio facial (cualquiera que diligencia
    necesita poder elegirlas), pero el correo completo solo lo ve un
    administrador.
    """
    es_admin = current_user.user_type in (UserType.admin, UserType.creator)
    personas = (
        db.query(SignatureCodePerson)
        .order_by(SignatureCodePerson.full_name)
        .all()
    )
    return [_salida(p, es_admin=es_admin) for p in personas]


@router.post("/persons/{person_id}/regenerate", response_model=PersonaOut)
def regenerar_codigo(
    person_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Genera un código nuevo y lo manda al correo. El anterior deja de servir.

    No devuelve el código: en la base solo queda su hash y este es el punto en
    el que se decidió que nadie lo vea en pantalla.
    """
    persona = (
        db.query(SignatureCodePerson)
        .filter(SignatureCodePerson.person_id == person_id)
        .first()
    )
    if not persona:
        raise HTTPException(status_code=404, detail="Firmante no encontrado")

    codigo = _generar_codigo()

    # También aquí el correo va primero: si se guardara el hash nuevo y el envío
    # fallara, el código anterior dejaría de servir y la persona se quedaría sin
    # ninguno. Así, un fallo de correo no le quita lo que ya tenía.
    if not send_signature_code_email(
        email=persona.email, name=persona.full_name, code=codigo, es_nuevo=True
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "No se pudo enviar el correo, asi que no se cambio nada: la "
                "persona conserva su codigo anterior. Intentelo de nuevo."
            ),
        )

    persona.code_hash = hash_password(codigo)
    persona.code_generated_at = datetime.now(timezone.utc)
    persona.code_generated_by_user_id = current_user.id
    # Un código nuevo limpia el bloqueo: si estaba trabado por intentos, este es
    # justamente el remedio.
    persona.failed_attempts = 0
    persona.locked_until = None
    db.commit()
    db.refresh(persona)

    _registrar_evento(
        db,
        person_id=persona.person_id,
        event="code_generated",
        request=request,
        user=current_user,
        detail="regenerado",
    )

    return _salida(persona, es_admin=True)


@router.post("/verify")
def verificar_codigo(
    datos: VerificarCodigoIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Valida el código y devuelve el comprobante con el que se podrá guardar la
    firma. El cliente nunca decide si el código está bien."""
    persona = (
        db.query(SignatureCodePerson)
        .filter(SignatureCodePerson.person_id == datos.person_id)
        .first()
    )
    if not persona or not persona.is_active:
        raise HTTPException(status_code=404, detail="Firmante no encontrado")

    ahora = datetime.now(timezone.utc)
    if persona.locked_until and persona.locked_until > ahora:
        faltan = int((persona.locked_until - ahora).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Demasiados intentos fallidos. Espere {faltan} minuto(s) o pida "
                f"a un administrador que le genere un codigo nuevo."
            ),
        )

    if not verify_password(datos.code.strip(), persona.code_hash):
        persona.failed_attempts = (persona.failed_attempts or 0) + 1
        evento = "sign_failed"
        if persona.failed_attempts >= MAX_INTENTOS:
            persona.locked_until = ahora + timedelta(minutes=BLOQUEO_MINUTOS)
            persona.failed_attempts = 0
            evento = "locked"
        db.commit()

        _registrar_evento(
            db,
            person_id=persona.person_id,
            event=evento,
            request=request,
            user=current_user,
            element_id=datos.form_design_element_id,
            row_index=datos.repeater_row_index,
            detail=f"formato {datos.form_id}",
        )

        if evento == "locked":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Codigo incorrecto. Se bloqueo por {BLOQUEO_MINUTOS} minutos "
                    f"tras varios intentos fallidos."
                ),
            )
        restantes = MAX_INTENTOS - persona.failed_attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Codigo incorrecto. Le quedan {restantes} intento(s).",
        )

    persona.failed_attempts = 0
    persona.locked_until = None
    persona.last_signed_at = ahora
    db.commit()

    _registrar_evento(
        db,
        person_id=persona.person_id,
        event="sign_ok",
        request=request,
        user=current_user,
        element_id=datos.form_design_element_id,
        row_index=datos.repeater_row_index,
        detail=f"formato {datos.form_id}",
    )

    return {
        "ok": True,
        "person_id": persona.person_id,
        "person_name": persona.full_name,
        "document": persona.document,
        "email": _enmascarar(persona.email),
        "verificado_en": ahora.isoformat(),
        # Lo que el cliente adjunta a la firma; sin esto el guardado la rechaza.
        "comprobante": emitir_comprobante(
            person_id=persona.person_id,
            form_id=datos.form_id,
            element_id=datos.form_design_element_id,
            row_index=datos.repeater_row_index,
        ),
    }
