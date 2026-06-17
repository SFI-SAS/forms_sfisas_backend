"""
Importación masiva por Excel vía cola (Celery + Redis).
==========================================================================
En vez de que el frontend golpee N veces /responses/save-response y
/save-answers (uno por fila del Excel, lo que puede saturar el sistema),
manda TODO el lote a /responses/bulk-import. El backend encola un task por
registro y el worker los procesa de forma controlada. El frontend consulta
el avance con GET /responses/bulk-import/{job_id}.

REQUIERE el worker corriendo:
    celery -A app.celery_app worker -P threads -c 3 -Q bulk_import --loglevel=info
"""

import uuid
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user
from app.models import User
from app.redis_client import redis_client
from app.tasks import process_bulk_record, job_key

router = APIRouter()


class BulkResponseIn(BaseModel):
    """Un item de respuesta tal como lo arma el `walk` del frontend.
    Campos extra (repeater_row_index, parent_*) se ignoran (igual que en el
    flujo normal, donde PostCreate los descarta)."""
    question_id: Union[int, str]
    response: Union[str, dict, bool, None] = ""
    file_path: Optional[str] = ""
    form_design_element_id: Optional[str] = None
    repeated_id: Optional[str] = None


class BulkRecordIn(BaseModel):
    index: int = 0  # posición original del registro (para mapear en la UI)
    responses: List[BulkResponseIn]


class BulkImportIn(BaseModel):
    form_id: int
    action: str = "send"  # "send" | "send_and_close"
    records: List[BulkRecordIn]


@router.post("/bulk-import")
def start_bulk_import(payload: BulkImportIn, current_user: User = Depends(get_current_user)):
    """Encola un lote de registros. Devuelve job_id para consultar el avance."""
    if not payload.records:
        raise HTTPException(status_code=400, detail="No hay registros para importar.")
    if payload.action not in ("send", "send_and_close"):
        raise HTTPException(status_code=400, detail="action inválida.")

    r = getattr(redis_client, "client", None)
    if not r:
        raise HTTPException(status_code=503, detail="Cola no disponible (Redis sin conexión).")

    job_id = uuid.uuid4().hex
    total = len(payload.records)
    key = job_key(job_id)
    # HSET de a un campo (compatible con Redis 3.x; el multi-campo HSET es 4.0+).
    init = {
        "total": total, "done": 0, "ok": 0, "failed": 0,
        "form_id": payload.form_id, "user_id": current_user.id,
    }
    pipe = r.pipeline()
    for field, value in init.items():
        pipe.hset(key, field, value)
    pipe.expire(key, 86400)
    pipe.execute()

    for rec in payload.records:
        process_bulk_record.delay(
            job_id, payload.form_id, current_user.id, payload.action, rec.index, rec.model_dump()
        )

    return {"job_id": job_id, "total": total, "status": "processing"}


@router.get("/bulk-import/{job_id}")
def bulk_import_status(job_id: str, current_user: User = Depends(get_current_user)):
    """Avance del job: cuántos van, cuántos ok/fallidos, índices y errores."""
    r = getattr(redis_client, "client", None)
    if not r:
        raise HTTPException(status_code=503, detail="Cola no disponible (Redis sin conexión).")

    key = job_key(job_id)
    data = r.hgetall(key)
    if not data:
        return {"job_id": job_id, "status": "not_found"}

    total = int(data.get("total", 0))
    done = int(data.get("done", 0))
    errors = r.lrange(key + ":errors", 0, 50)
    ok_indexes = [int(x) for x in r.lrange(key + ":ok", 0, -1)]
    failed_indexes = [int(x) for x in r.lrange(key + ":failed_idx", 0, -1)]
    if data.get("cancelled") == "1":
        job_status = "cancelled"
    elif total and done >= total:
        job_status = "done"
    else:
        job_status = "processing"

    return {
        "job_id": job_id,
        "total": total,
        "done": done,
        "ok": int(data.get("ok", 0)),
        "failed": int(data.get("failed", 0)),
        "status": job_status,
        "errors": errors,
        "ok_indexes": ok_indexes,
        "failed_indexes": failed_indexes,
    }


@router.post("/bulk-import/{job_id}/cancel")
def cancel_bulk_import(job_id: str, current_user: User = Depends(get_current_user)):
    """Cancela un job en curso: marca una bandera en Redis para que el worker
    descarte los registros que aún no ha procesado (sin insertarlos). Las tareas
    ya encoladas se consumen rápido sin hacer nada. No revierte lo ya insertado."""
    r = getattr(redis_client, "client", None)
    if not r:
        raise HTTPException(status_code=503, detail="Cola no disponible (Redis sin conexión).")

    key = job_key(job_id)
    if not r.exists(key):
        return {"job_id": job_id, "status": "not_found"}

    r.hset(key, "cancelled", "1")
    r.expire(key, 86400)
    return {"job_id": job_id, "status": "cancelled"}
