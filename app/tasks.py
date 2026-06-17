"""
Tareas Celery de SafeMetrics.
==========================================================================
`process_bulk_record` procesa UN registro de un envío masivo por Excel:
crea la respuesta y sus answers reutilizando la MISMA lógica de servidor que
usa el diligenciamiento normal (post_create_response + create_answer_in_db),
de modo que aprobaciones, bitácora y correos se comportan igual (no se altera
ningún otro funcionamiento).

El progreso de cada job se lleva en Redis con contadores atómicos (HINCRBY) y
listas de índices OK/fallidos, para que la UI sepa exactamente cómo va.
"""

import asyncio
import json

from app.celery_app import celery_app
from app.database import SessionLocal
from app.redis_client import redis_client


def job_key(job_id: str) -> str:
    return f"bulk_import:{job_id}"


def _bump_progress(job_id: str, record_index: int, ok: bool, err: str | None) -> int | None:
    """Actualiza contadores del job de forma atómica y registra el índice del
    registro en la lista de OK o de fallidos (para que la UI sepa cuáles).

    Devuelve el nuevo valor de `done` (atómico, vía HINCRBY) para que el llamador
    pueda detectar de forma segura cuál fue el ÚLTIMO registro del job y disparar
    el correo resumen una sola vez."""
    r = getattr(redis_client, "client", None)
    if not r:
        return None
    key = job_key(job_id)
    new_done = None
    try:
        if ok:
            r.hincrby(key, "ok", 1)
            r.rpush(key + ":ok", record_index)
            r.expire(key + ":ok", 86400)
        else:
            r.hincrby(key, "failed", 1)
            r.rpush(key + ":failed_idx", record_index)
            r.expire(key + ":failed_idx", 86400)
            if err:
                r.rpush(key + ":errors", f"#{record_index + 1}: {err}")
                r.expire(key + ":errors", 86400)
        new_done = r.hincrby(key, "done", 1)
        r.expire(key, 86400)
    except Exception:
        # El progreso es best-effort: nunca debe tumbar el procesamiento real.
        pass
    return new_done


def _maybe_send_summary(job_id: str, form_id: int, user_id: int, new_done: int | None) -> None:
    """Si este fue el último registro del job, envía UN correo resumen al usuario.

    La importación masiva NO manda un correo por registro (saturaría al proveedor
    SMTP). En cambio, al completarse el job se envía un único resumen. Se usa un
    candado SET NX para garantizar un solo envío aunque la tarea se re-entregue."""
    r = getattr(redis_client, "client", None)
    if not r or new_done is None:
        return
    try:
        key = job_key(job_id)
        data = r.hgetall(key)
        total = int(data.get("total", 0) or 0)
        # Solo el registro que cierra el job (done == total) sigue adelante.
        if not total or new_done < total:
            return
        # Candado: solo un envío aunque task_acks_late re-entregue el último task.
        if not r.set(key + ":summary_sent", "1", nx=True, ex=86400):
            return

        ok_count = int(data.get("ok", 0) or 0)
        failed = int(data.get("failed", 0) or 0)

        from app.database import SessionLocal
        from app.models import User, Form

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            form = db.query(Form).filter(Form.id == form_id).first()
            email = getattr(user, "email", None)
            name = getattr(user, "name", "") or ""
            form_title = getattr(form, "title", None) or f"Formato {form_id}"
        finally:
            db.close()

        if not email:
            return

        from app.api.controllers.bulk_import_mail import send_bulk_import_summary_email

        send_bulk_import_summary_email(email, name, form_title, total, ok_count, failed)
    except Exception:
        # El resumen es best-effort: nunca debe afectar el procesamiento.
        pass


@celery_app.task(name="bulk_import.process_record", bind=True, max_retries=0)
def process_bulk_record(self, job_id: str, form_id: int, user_id: int, action: str, record_index: int, record: dict):
    """Crea una respuesta + sus answers para un registro del Excel.

    Replica el flujo de /save-response + /save-answers del diligenciamiento
    normal. `record` = {"responses": [{question_id, response, file_path?,
    form_design_element_id?, repeated_id?}, ...]} — el mismo array que el
    frontend arma con su `walk` de la estructura del formato.
    """
    # Cancelación: si el job fue marcado como cancelado, descartar este registro
    # sin insertarlo. Las tareas ya encoladas se consumen rápido (no se puede
    # quitar una tarea concreta de la cola de Celery, pero sí saltarse el trabajo).
    _r = getattr(redis_client, "client", None)
    if _r is not None:
        try:
            if _r.hget(job_key(job_id), "cancelled") == "1":
                return {"ok": False, "error": "cancelado", "index": record_index, "skipped": True}
        except Exception:
            pass

    # Imports diferidos: evitan ciclos y que el worker cargue toda la app al import.
    from app.models import FormatType, ResponseStatus
    from app.models import User, Form
    from app.schemas import PostCreate
    from app.crud import post_create_response, create_answer_in_db

    db = SessionLocal()
    ok = False
    err = None
    try:
        user = db.query(User).filter(User.id == user_id).first()
        form = db.query(Form).filter(Form.id == form_id).first()
        if not user:
            raise ValueError(f"Usuario {user_id} no encontrado")
        if not form:
            raise ValueError(f"Formato {form_id} no encontrado")

        # Mismo criterio que /save-response: estado y si se crean aprobaciones.
        if form.format_type == FormatType.cerrado:
            response_status = ResponseStatus.submitted
            create_approvals = True
        elif action == "send_and_close":
            response_status = ResponseStatus.submitted
            create_approvals = True
        else:  # "send" → borrador
            response_status = ResponseStatus.draft
            create_approvals = False

        # Importación masiva: NUNCA se envía un correo por registro (saturaría al
        # proveedor SMTP y dispara bloqueos por "actividad inusual"). El usuario
        # recibe en su lugar un único correo resumen al terminar el job
        # (ver _maybe_send_summary). El corte real de correos lo hace
        # send_notifications=False en post_create_response (abajo). El resto del
        # flujo (aprobaciones, bitácora, estado) se mantiene idéntico al normal.
        send_emails = False

        responses = record.get("responses", []) or []
        if not responses:
            raise ValueError("Registro sin respuestas válidas")

        # Mismo criterio que extract_repeated_id(): primer repeated_id no vacío.
        repeated_id = None
        for r in responses:
            rid = r.get("repeated_id")
            if rid and str(rid).strip():
                repeated_id = rid
                break

        async def _run():
            result = await post_create_response(
                db=db,
                form_id=form_id,
                user_id=user_id,
                current_user=user,
                request=None,  # sin Request: los correos en background degradan a no-op si lo requieren
                mode="online",
                repeated_id=repeated_id,
                create_approvals=create_approvals,
                status=response_status,
                send_notifications=False,  # bulk: sin correo por registro (ver _maybe_send_summary)
            )
            response_id = result["response_id"]
            id_relation_bitacora = result["id_relation_bitacora"]

            for r in responses:
                val = r.get("response", "")
                # Igual que el frontend: objetos → JSON, lo demás → str.
                answer_text = val if isinstance(val, str) else json.dumps(val)
                pc = PostCreate(
                    response_id=response_id,
                    question_id=r["question_id"],
                    answer_text=answer_text,
                    file_path=r.get("file_path") or "",
                    form_design_element_id=r.get("form_design_element_id"),
                )
                await create_answer_in_db(pc, db, user, None, send_emails, id_relation_bitacora)
            return response_id

        asyncio.run(_run())
        ok = True
    except Exception as e:  # noqa: BLE001 — cualquier fallo cuenta como registro fallido
        err = str(e)[:300]
    finally:
        db.close()

    new_done = _bump_progress(job_id, record_index, ok, err)
    _maybe_send_summary(job_id, form_id, user_id, new_done)
    return {"ok": ok, "error": err, "index": record_index}
