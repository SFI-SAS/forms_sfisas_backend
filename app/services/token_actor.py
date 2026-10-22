"""Le dice a la base quién está haciendo el cambio, para que los triggers de
token_events lo anoten (scripts/db_migrations/2026-10-19_tokens_eventos_y_licencia.sql).

El middleware lee el email del token de la petición (sin validar permisos: eso
lo sigue haciendo get_current_user) y, al empezar cada transacción, se pasa a
PostgreSQL con set_config(..., true), que dura solo esa transacción.

Sin petición (tareas programadas, scripts) no se pone nada y el evento queda
sin actor.
"""
import contextvars

from jose import JWTError, jwt
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.security import ALGORITHM, SECRET_KEY

_actor: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("token_actor", default=None)


def _desde_peticion(request) -> tuple[str, str] | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        datos = jwt.decode(auth[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    email = datos.get("sub")
    if not isinstance(email, str):
        return None
    return email, "api" if datos.get("type") == "integrator" else "ui"


async def middleware_actor(request, call_next):
    marca = _actor.set(_desde_peticion(request))
    try:
        return await call_next(request)
    finally:
        _actor.reset(marca)


@event.listens_for(Session, "after_begin")
def _pasar_actor_a_la_base(session, transaction, connection):
    actor = _actor.get()
    if actor is None:
        return
    connection.execute(
        text("SELECT set_config('safemetrics.actor_email', :email, true), "
             "set_config('safemetrics.origen', :origen, true)"),
        {"email": actor[0], "origen": actor[1]},
    )
