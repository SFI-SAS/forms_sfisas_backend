"""
Endpoints que alimentan las vistas del Home rediseñado de forms_sfi
(Sprint 1 — Decisión 1 / CLAUDE.md sección 4).

- GET    /home/pending-forms       → To-Do: formatos asignados sin responder en el período actual.
- GET    /home/upcoming-events     → Calendario: eventos expandidos por rango de fechas.
- DELETE /home/schedules/{id}      → Borra una programación periódica.
- DELETE /home/schedules/by-form-user → Borra schedule por (form_id, user_id).

Todos derivan de FormSchedule (modelo ya existente, no requiere migración).
Convención de auth seguida de forms.py.
"""

import calendar
import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models import ApprovalStatus, BitacoraLogsSimple, EstadoEvento, Form, FormSchedule, Response, ResponseApproval, ResponseStatus, User, UserType
from sqlalchemy import and_, func, or_

router = APIRouter()
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Helpers de cálculo sobre FormSchedule
# ────────────────────────────────────────────────────────────────────────────

# repeat_days viene como JSON serializado en BD. Admite inglés y español
# porque el frontend actual mezcla ambos en distintas pantallas.
_WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}


def _to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _parse_repeat_days(raw: Optional[str]) -> set[int]:
    if not raw:
        return set()
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    if not isinstance(items, list):
        return set()
    out = set()
    for item in items:
        if isinstance(item, str):
            idx = _WEEKDAY_MAP.get(item.strip().lower())
            if idx is not None:
                out.add(idx)
        elif isinstance(item, int) and 0 <= item <= 6:
            out.add(item)
    return out


def _add_months(d: date, n: int) -> date:
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _compute_next_due_date(sch: FormSchedule, today: date) -> Optional[date]:
    """Próxima fecha en la que el formato debe diligenciarse según el schedule."""
    freq = (sch.frequency_type or "").lower()
    specific = _to_date(sch.specific_date)

    if freq in ("specific", "once") and specific:
        return specific

    if freq == "daily":
        return today

    if freq == "weekly":
        targets = _parse_repeat_days(sch.repeat_days)
        if not targets:
            return None
        for offset in range(0, 7):
            candidate = today + timedelta(days=offset)
            if candidate.weekday() in targets:
                return candidate
        return None

    if freq == "monthly":
        target_day = specific.day if specific else 1
        last_day_this = calendar.monthrange(today.year, today.month)[1]
        this_month = date(today.year, today.month, min(target_day, last_day_this))
        if this_month >= today:
            return this_month
        return _add_months(this_month, 1)

    if freq in ("interval", "custom") and sch.interval_days and specific:
        if specific >= today:
            return specific
        delta = (today - specific).days
        remainder = delta % sch.interval_days
        if remainder == 0:
            return today
        return today + timedelta(days=sch.interval_days - remainder)

    return None


def _is_done_in_current_period(
    sch: FormSchedule, last_submitted_at: Optional[datetime], today: date
) -> bool:
    """¿El usuario ya envió respuesta en el período que cubre el schedule actual?"""
    if not last_submitted_at:
        return False
    submitted = _to_date(last_submitted_at)
    if not submitted:
        return False

    freq = (sch.frequency_type or "").lower()

    if freq == "daily":
        return submitted == today
    if freq == "weekly":
        return (submitted.isocalendar()[0], submitted.isocalendar()[1]) == (
            today.isocalendar()[0],
            today.isocalendar()[1],
        )
    if freq == "monthly":
        return submitted.year == today.year and submitted.month == today.month
    if freq in ("specific", "once"):
        specific = _to_date(sch.specific_date)
        return bool(specific and submitted >= specific)
    if freq in ("interval", "custom") and sch.interval_days:
        return (today - submitted).days < sch.interval_days
    return False


def _expand_schedule_in_range(
    sch: FormSchedule, range_start: date, range_end: date
) -> List[date]:
    """Lista de fechas concretas en [range_start, range_end] generadas por el schedule."""
    freq = (sch.frequency_type or "").lower()
    specific = _to_date(sch.specific_date)
    out: List[date] = []

    if freq in ("specific", "once"):
        if specific and range_start <= specific <= range_end:
            out.append(specific)
        return out

    if freq == "daily":
        cursor = range_start
        while cursor <= range_end:
            out.append(cursor)
            cursor += timedelta(days=1)
        return out

    if freq == "weekly":
        targets = _parse_repeat_days(sch.repeat_days)
        if not targets:
            return out
        cursor = range_start
        while cursor <= range_end:
            if cursor.weekday() in targets:
                out.append(cursor)
            cursor += timedelta(days=1)
        return out

    if freq == "monthly":
        target_day = specific.day if specific else 1
        month_cursor = date(range_start.year, range_start.month, 1)
        while month_cursor <= range_end:
            last_day = calendar.monthrange(month_cursor.year, month_cursor.month)[1]
            candidate = date(
                month_cursor.year, month_cursor.month, min(target_day, last_day)
            )
            if range_start <= candidate <= range_end:
                out.append(candidate)
            month_cursor = _add_months(month_cursor, 1).replace(day=1)
        return out

    if freq in ("interval", "custom") and sch.interval_days and specific:
        if specific > range_end:
            return out
        cursor = specific
        while cursor < range_start:
            cursor += timedelta(days=sch.interval_days)
        while cursor <= range_end:
            out.append(cursor)
            cursor += timedelta(days=sch.interval_days)
        return out

    return out


def _event_period(sch: FormSchedule, event_date: date) -> tuple[date, date]:
    """
    Período de "validez" de un evento. Si el usuario envía una Response
    cuya fecha cae en [start, end], el evento se considera completado.
    """
    freq = (sch.frequency_type or "").lower()
    if freq == "daily":
        return (event_date, event_date)
    if freq == "weekly":
        weekday = event_date.weekday()  # 0=lun, 6=dom
        start = event_date - timedelta(days=weekday)
        end = start + timedelta(days=6)
        return (start, end)
    if freq == "monthly":
        last_day = calendar.monthrange(event_date.year, event_date.month)[1]
        return (
            date(event_date.year, event_date.month, 1),
            date(event_date.year, event_date.month, last_day),
        )
    if freq in ("specific", "specific_date", "once"):
        # Cualquier respuesta desde la fecha del evento en adelante cuenta.
        return (event_date, date(9999, 12, 31))
    if freq in ("interval", "periodic", "custom") and sch.interval_days:
        return (event_date, event_date + timedelta(days=sch.interval_days - 1))
    return (event_date, event_date)


# ────────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────────

_URGENCY_RANK = {
    "vencido": 0,
    "hoy": 1,
    "esta_semana": 2,
    "proximo": 3,
    "indefinido": 4,
    "hecha": 5,
}


@router.get("/pending-forms")
def get_user_pending_forms(
    include_completed: bool = Query(
        False,
        description="Si True, incluye también las tareas completadas en el período actual (urgency='hecha').",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Formatos asignados al usuario logueado. Por defecto solo retorna los que
    aún NO tienen respuesta enviada en el período actual. Si
    `include_completed=true`, también devuelve los completados con
    `urgency='hecha'` y `completed=true`.

    Retorna lista ordenada por urgencia y luego por fecha objetivo:
        [
          {
            "form_id", "title", "description", "category_id",
            "frequency_type", "next_due_date" (ISO), "urgency",
            "last_submitted_at" (ISO|null), "schedule_id", "completed" (bool)
          },
          ...
        ]

    `urgency` ∈ {"vencido", "hoy", "esta_semana", "proximo", "indefinido", "hecha"}.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated",
        )

    today = date.today()
    schedules = (
        db.query(FormSchedule)
        .filter(
            FormSchedule.user_id == current_user.id,
            FormSchedule.status.is_(True),
        )
        .all()
    )
    if not schedules:
        return []

    form_ids = [s.form_id for s in schedules]
    forms_by_id = {
        f.id: f
        for f in db.query(Form)
        .filter(Form.id.in_(form_ids), Form.is_enabled.is_(True))
        .all()
    }

    last_submitted_by_form = {}
    last_rows = (
        db.query(Response.form_id, Response.submitted_at)
        .filter(
            Response.user_id == current_user.id,
            Response.form_id.in_(form_ids),
            Response.status.in_([ResponseStatus.submitted, ResponseStatus.approved]),
        )
        .order_by(Response.submitted_at.desc())
        .all()
    )
    for form_id, submitted_at in last_rows:
        # se queda con la primera ocurrencia (la más reciente por el order_by)
        last_submitted_by_form.setdefault(form_id, submitted_at)

    pending = []
    for sch in schedules:
        form = forms_by_id.get(sch.form_id)
        if form is None:
            continue

        last_submitted_at = last_submitted_by_form.get(form.id)
        is_done = _is_done_in_current_period(sch, last_submitted_at, today)

        if is_done:
            if not include_completed:
                continue
            urgency = "hecha"
            next_due = _compute_next_due_date(sch, today)
        else:
            next_due = _compute_next_due_date(sch, today)
            if next_due is None:
                urgency = "indefinido"
            elif next_due < today:
                urgency = "vencido"
            elif next_due == today:
                urgency = "hoy"
            elif (next_due - today).days <= 7:
                urgency = "esta_semana"
            else:
                urgency = "proximo"

        pending.append({
            "form_id": form.id,
            "title": form.title,
            "description": form.description,
            "category_id": form.id_category,
            "frequency_type": sch.frequency_type,
            "next_due_date": next_due.isoformat() if next_due else None,
            "urgency": urgency,
            "last_submitted_at": (
                last_submitted_at.isoformat() if last_submitted_at else None
            ),
            "schedule_id": sch.id,
            "completed": is_done,
        })

    pending.sort(
        key=lambda p: (
            _URGENCY_RANK.get(p["urgency"], 99),
            p["next_due_date"] or "9999-12-31",
            p["title"].lower(),
        )
    )
    return pending


@router.get("/upcoming-events")
def get_user_upcoming_events(
    start_date: date = Query(..., description="Inicio del rango (ISO YYYY-MM-DD)"),
    end_date: date = Query(..., description="Fin del rango (ISO YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Eventos del calendario expandidos a partir de los FormSchedule activos
    del usuario logueado, dentro del rango pedido.

    Retorna lista ordenada por fecha:
        [
          { "form_id", "title", "date" (ISO), "frequency_type",
            "schedule_id", "category_id", "completed" (bool) },
          ...
        ]

    `completed` es true si el usuario envió respuesta dentro del período del
    evento (definido por _event_period según frequency_type).
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated",
        )
    if end_date < start_date:
        raise HTTPException(
            status_code=400, detail="end_date debe ser >= start_date"
        )
    if (end_date - start_date).days > 366:
        raise HTTPException(
            status_code=400,
            detail="Rango máximo 366 días para evitar explosión de eventos",
        )

    schedules = (
        db.query(FormSchedule)
        .filter(
            FormSchedule.user_id == current_user.id,
            FormSchedule.status.is_(True),
        )
        .all()
    )
    if not schedules:
        return []

    form_ids = [s.form_id for s in schedules]
    forms_by_id = {
        f.id: f
        for f in db.query(Form)
        .filter(Form.id.in_(form_ids), Form.is_enabled.is_(True))
        .all()
    }

    # Precarga respuestas del usuario en un rango ampliado para cubrir los
    # períodos que se extienden más allá de end_date (ej. specific_date).
    response_rows = (
        db.query(Response.form_id, Response.submitted_at)
        .filter(
            Response.user_id == current_user.id,
            Response.form_id.in_(form_ids),
            Response.status.in_([ResponseStatus.submitted, ResponseStatus.approved]),
        )
        .all()
    )
    # Índice: form_id -> lista de submitted_dates (orden no importa)
    completions_by_form: dict[int, list[date]] = {}
    for r_form_id, submitted_at in response_rows:
        d = _to_date(submitted_at)
        if d is None:
            continue
        completions_by_form.setdefault(r_form_id, []).append(d)

    def _is_event_done(sch: FormSchedule, event_date: date) -> bool:
        dates = completions_by_form.get(sch.form_id, [])
        if not dates:
            return False
        p_start, p_end = _event_period(sch, event_date)
        return any(p_start <= rd <= p_end for rd in dates)

    events = []
    for sch in schedules:
        form = forms_by_id.get(sch.form_id)
        if form is None:
            continue
        for d in _expand_schedule_in_range(sch, start_date, end_date):
            events.append({
                "form_id": form.id,
                "title": form.title,
                "date": d.isoformat(),
                "frequency_type": sch.frequency_type,
                "schedule_id": sch.id,
                "category_id": form.id_category,
                "completed": _is_event_done(sch, d),
            })

    events.sort(key=lambda e: (e["date"], e["title"].lower()))
    return events


# ────────────────────────────────────────────────────────────────────────────
# Eliminación de programaciones (DELETE)
# ────────────────────────────────────────────────────────────────────────────

def _user_can_manage_schedules(user: User) -> bool:
    """admin y creator pueden tocar schedules de cualquier usuario."""
    if user is None or user.user_type is None:
        return False
    try:
        return user.user_type.name in (UserType.admin.name, UserType.creator.name)
    except Exception:
        return False


# IMPORTANTE: la ruta literal /schedules/by-form-user DEBE declararse ANTES que
# la paramétrica /schedules/{schedule_id}. FastAPI matchea en orden de definición;
# si {schedule_id} va primero, "by-form-user" cae ahí y falla con 422 int_parsing
# (schedule_id='by-form-user'). Esto rompía delete_schedule_by_form_user (siempre
# 422). Hallado por el harness de cobertura de tools de ArIA (2026-06-04).
@router.delete("/schedules/by-form-user", status_code=status.HTTP_204_NO_CONTENT)
def delete_form_schedule_by_form_user(
    form_id: int = Query(..., description="ID del formato"),
    user_id: int = Query(..., description="ID del usuario al que se le programó"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina la programación de un formato para un usuario específico,
    sin necesidad de conocer el id del schedule.

    Permisos:
      - admin/creator: pueden borrar para cualquier usuario.
      - resto de usuarios: solo si `user_id` == el suyo.

    Idempotente: si no existe schedule para esa combinación retorna 204 igual.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated",
        )

    if not _user_can_manage_schedules(current_user) and user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar esta programación",
        )

    deleted = (
        db.query(FormSchedule)
        .filter(
            FormSchedule.form_id == form_id,
            FormSchedule.user_id == user_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info(
        "delete_form_schedule_by_form_user: form_id=%s user_id=%s deleted=%s",
        form_id, user_id, deleted,
    )
    return


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina una programación periódica de un formato por su id.

    Permisos:
      - admin/creator: pueden borrar cualquier schedule.
      - resto de usuarios: solo pueden borrar schedules cuyo `user_id` es el suyo.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authenticated",
        )

    sch = db.query(FormSchedule).filter(FormSchedule.id == schedule_id).first()
    if sch is None:
        raise HTTPException(status_code=404, detail="Programación no encontrada")

    if not _user_can_manage_schedules(current_user) and sch.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar esta programación",
        )

    db.delete(sch)
    db.commit()
    return


# ────────────────────────────────────────────────────────────────────────────
# Actividad reciente — feed para el Dashboard (página 1 del mockup).
# Lectura pura sobre ResponseApproval/Response/Form/User. NO toca el motor
# de aprobaciones (intocable #1, crud.py:4138-4509) ni el activity log
# (intocable #6, services/activity.py).
# ────────────────────────────────────────────────────────────────────────────

@router.get("/recent-activity")
def get_recent_activity(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Eventos recientes sobre los formatos que el usuario actual sometió a
    aprobación: quién y cuándo aprobó/rechazó cada respuesta. Más nuevo primero.
    """
    rows = (
        db.query(ResponseApproval, Response, Form, User)
        .join(Response, Response.id == ResponseApproval.response_id)
        .join(Form, Form.id == Response.form_id)
        .join(User, User.id == ResponseApproval.user_id)
        .filter(
            Response.user_id == current_user.id,
            ResponseApproval.reviewed_at.isnot(None),
            ResponseApproval.status.in_(
                [ApprovalStatus.aprobado, ApprovalStatus.rechazado]
            ),
        )
        .order_by(ResponseApproval.reviewed_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": ap.id,
            "actor_id": actor.id,
            "actor_name": actor.name,
            "action": ap.status.value,  # "aprobado" | "rechazado"
            "form_id": form.id,
            "form_title": form.title,
            "response_id": resp.id,
            "occurred_at": ap.reviewed_at,
        }
        for ap, resp, form, actor in rows
    ]


# ────────────────────────────────────────────────────────────────────────────
# To-Do: eventos de bitácora donde el usuario es CREADOR o PARTICIPANTE,
# que aún requieren atención (estado != finalizado). El campo participantes
# es CSV de num_document. Replica el wrapping de get_bitacora_eventos_by_user
# para evitar falsos positivos por substring.
# ────────────────────────────────────────────────────────────────────────────

@router.get("/pending-bitacora-events")
def list_pending_bitacora_events_for_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Eventos de bitácora pendientes para el usuario: o los creó él, o lo
    agregaron como participante. Excluye los finalizados. Alimenta la sección
    'Eventos pendientes' del To-Do del Home.

    Formato de los campos en BD (ver crud.py:6842 y ButtonEventModal.tsx:432):
      - registrado_por: "Nombre Apellido - {num_document}"
      - participantes:  CSV con ', ' separator de "Nombre Apellido - {num_document}"

    Estrategia de match:
      - registrado_por: comparar contra el label exacto (name+doc) o, si el
        nombre cambió, por sufijo "- {num_document}".
      - participantes: concatenar ', ' al final del campo y buscar
        "%- {num_document}, %" para asegurar token completo (evita falsos
        positivos por substring entre num_documents).
    """
    me_doc = str(current_user.num_document)
    me_label = f"{current_user.name} - {me_doc}"
    suffix_pattern = f"%- {me_doc}"  # sufijo: "...- 12345"

    # Para participantes: agregamos ', ' al final del campo y buscamos el token
    # como "%- 12345, %". Garantiza que matchee el token completo, incluso si es
    # el último de la lista.
    participants_with_trailing = func.concat(
        func.coalesce(BitacoraLogsSimple.participantes, ''),
        ', '
    )

    rows = (
        db.query(BitacoraLogsSimple)
        .filter(
            or_(
                BitacoraLogsSimple.registrado_por == me_label,
                BitacoraLogsSimple.registrado_por.like(suffix_pattern),
                participants_with_trailing.like(f"%- {me_doc}, %"),
            ),
            BitacoraLogsSimple.estado != EstadoEvento.finalizado,
        )
        .order_by(BitacoraLogsSimple.created_at.desc())
        .all()
    )

    def _is_creator(ev: BitacoraLogsSimple) -> bool:
        rp = ev.registrado_por or ""
        return rp == me_label or rp.endswith(f"- {me_doc}")

    return [
        {
            "id": ev.id,
            "clasificacion": ev.clasificacion,
            "titulo": ev.titulo,
            "fecha": ev.fecha,
            "hora": ev.hora,
            "ubicacion": ev.ubicacion,
            "registrado_por": ev.registrado_por,
            "is_creator": _is_creator(ev),
            "estado": ev.estado.value if hasattr(ev.estado, "value") else str(ev.estado),
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in rows
    ]
