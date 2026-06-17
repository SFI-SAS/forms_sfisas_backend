"""
Celery app de SafeMetrics.
==========================================================================
Broker y backend en Redis (el que ya usa el proyecto). Se usa para procesar
en cola los envíos masivos por Excel, evitando que el frontend golpee N veces
los endpoints de creación de respuesta y sature el sistema.

Correr el worker (DEBE estar corriendo para que la cola se procese).
En Windows usar el pool de threads (el prefork falla):
    celery -A app.celery_app worker -P threads -c 3 -Q bulk_import --loglevel=info

Variables de entorno (opcionales; por defecto deriva de REDIS_HOST/PORT/PASSWORD):
    CELERY_BROKER_URL, CELERY_RESULT_BACKEND
"""

import os
from celery import Celery


def _redis_url(db: int) -> str:
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD") or ""
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


# DB 1 para el broker y DB 2 para resultados, para no chocar con la caché de la
# app (que usa la DB 0 por defecto en redis_client.py).
celery_app = Celery(
    "safemetrics",
    broker=os.getenv("CELERY_BROKER_URL", _redis_url(1)),
    backend=os.getenv("CELERY_RESULT_BACKEND", _redis_url(2)),
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Bogota",
    enable_utc=True,
    task_acks_late=True,            # re-entrega si el worker muere a mitad
    worker_prefetch_multiplier=1,  # 1 task a la vez por proceso → cola real, no ráfaga
    task_default_queue="bulk_import",
    result_expires=3600,
)
