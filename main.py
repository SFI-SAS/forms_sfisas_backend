import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text
from app.api.controllers.mail import send_rule_notification_email
from app.redis_client import redis_client
from app.crud import (
    get_response_details_logic,
    get_schedules_by_frequency,
    get_pending_notification_rules,
    disable_notification_rule
)

from app.database import SessionLocal, engine
from app.models import Base, EmailConfig
from app.api.endpoints import (
    alias, approvers, consultants, download_template, home_dashboard, integrations, list_form, pdf_router, profiles, projects, responses,
    responsibilitytransfer, users, forms, auth, questions, generic_activities, question_requests
)

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Safemetrics Forms API",
    version="1.0.0",
    description="API para gestión de formularios",
    openapi_version="3.1.0"
)


# ─────────────────────────────────────────────────────────────────────────────
# Manejador global de errores (M-4): para respuestas 5xx NO se expone el detalle
# interno al cliente (los `detail=str(e)` filtran esquema de BD, rutas y driver).
# Se loguea el detalle real en el servidor y se devuelve un mensaje genérico.
# Los 4xx conservan su mensaje (el frontend los necesita) delegando al manejador
# por defecto de FastAPI. Cubre TODOS los endpoints sin editar su código.
# ─────────────────────────────────────────────────────────────────────────────
from starlette.exceptions import HTTPException as _StarletteHTTPException
from starlette.requests import Request as _Request
from fastapi.exception_handlers import http_exception_handler as _default_http_exception_handler


@app.exception_handler(_StarletteHTTPException)
async def _sanitized_http_exception_handler(request: _Request, exc: _StarletteHTTPException):
    if exc.status_code >= 500:
        logger.error(
            "5xx en %s %s -> %s: %s",
            request.method, request.url.path, exc.status_code, exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": "Error interno del servidor."},
            headers=getattr(exc, "headers", None),
        )
    return await _default_http_exception_handler(request, exc)


# 1. CORS debe ir primero
import os
_default_origins = "https://forms.sfisas.com.co,http://localhost:4321"
_origins_env = os.getenv("CORS_ORIGINS", _default_origins)
origins = [o.strip() for o in _origins_env.split(",") if o.strip()]

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,                     # NUNCA "*" con credentials
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "User-Agent"],
    max_age=600,
)

# 2. GZIP
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000
)

# 3. ✅ SECURITY HEADERS
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)

    # Forzar HTTPS en el navegador por 1 año
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Bloquear embedding en iframes (previene clickjacking)
    response.headers["X-Frame-Options"] = "DENY"

    # Evitar que el browser adivine el MIME type
    response.headers["X-Content-Type-Options"] = "nosniff"

    # No enviar referrer a sitios externos
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # H-BW-012: X-XSS-Protection deprecado — removido. CSP cubre este caso.

    # No permitir acceso a cámara, micrófono, geolocation, etc.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    # Content Security Policy — ajusta los dominios a los tuyos
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self' https://app.safemetrics.co https://forms.sfisas.com.co; "
        "frame-ancestors 'none';"
    )

    return response
# ========================================
# CONFIGURACIÓN DE TEMPLATES
# ========================================
templates_env = Environment(loader=FileSystemLoader("app/api/templates"))
app.state.templates_env = templates_env

# ========================================
# GUARDAR REDIS EN APP STATE
# ========================================
app.state.redis_client = redis_client

# ========================================
# ROUTERS
# ========================================
app.include_router(pdf_router.router, prefix="/pdf", tags=["pdf"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(forms.router, prefix="/forms", tags=["forms"])
app.include_router(approvers.router, prefix="/approvers", tags=["approvers"])
app.include_router(questions.router, prefix="/questions", tags=["questions"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(responses.router, prefix="/responses", tags=["responses"])
app.include_router(list_form.router, prefix="/list_form", tags=["list_form"])
app.include_router(
    responsibilitytransfer.router, 
    prefix="/responsibilitytransfer", 
    tags=["responsibility_transfer"]
)
app.include_router(download_template.router, prefix="/download_template", tags=["Download Templates"])
app.include_router(alias.router, prefix="/alias", tags=["alias"])
app.include_router(consultants.router, prefix="/consultants", tags=["consultants"])
app.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
app.include_router(generic_activities.router, prefix="/generic-activities", tags=["generic-activities"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
app.include_router(home_dashboard.router, prefix="/home", tags=["home"])
app.include_router(question_requests.router, prefix="/question-requests", tags=["Question Requests"])

# ========================================
# CREAR TABLAS
# ========================================
# H-BW-008: create_all solo en desarrollo. En prod usar migraciones manuales (carpeta migrations/).
if os.getenv("ENV") == "development":
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Tablas creadas/verificadas (modo desarrollo)")
else:
    logger.info("ℹ️ Producción: create_all omitido — usá migraciones manuales (migrations/)")

# ========================================
# EVENTOS DE INICIO Y CIERRE
# ========================================
# H-BW-009: startup_event consolidado (email seed + Redis check) está más abajo.

@app.on_event("shutdown")
async def shutdown_event():
    """Se ejecuta al apagar la aplicación"""
    logger.info("🛑 Apagando aplicación...")
    scheduler.shutdown()

# ========================================
# ENDPOINTS
# ========================================
@app.get("/")
def read_root():
    return {"message": "Bienvenido a Formularios de SFI"}

@app.get("/health")
def health_check():
    """Endpoint para verificar estado de la API, Redis y BD.

    SECURITY (ID-026): retorna HTTP 503 si Redis o BD están caídos para que
    orquestadores (k8s, ELB, nginx upstream) hagan failover automático.
    El body mantiene el mismo shape en éxito y degradación para facilitar debug.
    """
    redis_status = redis_client.check_connection()
    db_status = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = True
    except Exception as e:
        # No exponer detalles internos al cliente; solo loguear tipo de excepción.
        logger.warning("ID-026: health DB ping fallido (%s)", type(e).__name__)
    healthy = redis_status and db_status
    body = {
        "status": "ok" if healthy else "degraded",
        "redis_connected": redis_status,
        "db_connected": db_status,
    }
    return JSONResponse(content=body, status_code=200 if healthy else 503)

# ========================================
# SCHEDULER PARA TAREAS PROGRAMADAS
# ========================================
DIAS_SEMANA = {
    "monday": "lunes",
    "tuesday": "martes",
    "wednesday": "miercoles",
    "thursday": "jueves",
    "friday": "viernes",
    "saturday": "sabado",
    "sunday": "domingo"
}

def daily_schedule_task():
    """Obtiene los registros activos para el día actual y ejecuta la lógica necesaria."""
    logger.info("⏳ Ejecutando tarea diaria de formularios programados...")

    db = SessionLocal()
    try:
        schedules = get_schedules_by_frequency(db)
        logger.info(f"📆 Registros obtenidos para hoy: {len(schedules)}")

        response_details = get_response_details_logic(db)
        logger.info(f"📌 Detalles de respuestas obtenidos: {len(response_details)}")

    except Exception as e:
        logger.error(f"⚠️ Error en la tarea diaria de formularios: {str(e)}")
    finally:
        db.close()


@app.on_event("startup")
async def startup_seed_email_config():
    """H-BW-009: Inicializa email_config (solo dev) y verifica Redis al iniciar."""
    logger.info("🚀 Iniciando aplicación...")
    
    # ====== INICIALIZAR EMAIL_CONFIG ======
    db = SessionLocal()
    try:
        # Verificar si ya existen registros
        email_count = db.query(EmailConfig).count()
        
        if email_count == 0:
            # H-BW-010: Solo seed en desarrollo; en prod se debe ejecutar script manual.
            if os.getenv("ENV") == "development":
                db.add_all([
                    EmailConfig(email_address="example1@domain.com", is_active=False),
                    EmailConfig(email_address="example2@domain.com", is_active=False),
                ])
                db.commit()
                logger.info("✅ Registros de email_config inicializados (seed development)")
            else:
                logger.info("ℹ️ email_config vacía — si es primer deploy, ejecutá el script de seed manualmente")
        else:
            logger.info(f"ℹ️ email_config ya contiene {email_count} registros")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error al inicializar email_config: {str(e)}")
    finally:
        db.close()
    
    # Verificar conexión a Redis
    if redis_client.check_connection():
        logger.info("✅ Redis conectado correctamente")
    else:
        logger.warning("⚠️ Advertencia: Redis no está disponible")
        
def notification_rules_task():
    """
    Tarea programada para enviar notificaciones de reglas de vencimiento.
    Se ejecuta diariamente y:
    1. Busca reglas que deben notificarse hoy
    2. Envía correos de alerta
    3. Deshabilita las reglas ya notificadas
    """
    logger.info("\n" + "="*60)
    logger.info("⏰ Ejecutando tarea de notificaciones de reglas...")
    logger.info("="*60)

    db = SessionLocal()
    emails_sent = 0
    emails_failed = 0
    
    try:
        # Obtener notificaciones pendientes
        notifications = get_pending_notification_rules(db)
        
        if not notifications:
            logger.info("✅ No hay notificaciones pendientes para hoy")
            return
        
        logger.info(f"\n📬 Procesando {len(notifications)} notificaciones...")
        
        # Procesar cada notificación
        for notification in notifications:
            try:
                logger.info(f"\n📧 Enviando correo a {notification['user_email']}...")
                
                # Enviar correo
                email_sent = send_rule_notification_email(
                    user_email=notification['user_email'],
                    user_name=notification['user_name'],
                    form_title=notification['form_title'],
                    form_description=notification['form_description'],
                    response_id=notification['response_id'],
                    date_limit=notification['date_limit'],
                    days_remaining=notification['days_remaining'],
                    days_before_alert=notification['days_before_alert'],
                    question_text=notification['question_text'],
                    user_document=notification['user_document'],
                    user_telephone=notification['user_telephone']
                )
                
                if email_sent:
                    emails_sent += 1
                    
                    # ✅ DESHABILITAR LA REGLA DESPUÉS DE ENVIAR EL CORREO
                    disabled = disable_notification_rule(db, notification['rule_id'])
                    
                    if disabled:
                        logger.info(f"   ✅ Correo enviado y regla ID {notification['rule_id']} deshabilitada")
                    else:
                        logger.warning(f"   ⚠️ Correo enviado pero no se pudo deshabilitar la regla ID {notification['rule_id']}")
                else:
                    emails_failed += 1
                    logger.error(f"   ❌ No se pudo enviar el correo a {notification['user_email']}")
                    
            except Exception as e:
                emails_failed += 1
                logger.error(f"   ❌ Error procesando notificación para {notification.get('user_email', 'email desconocido')}: {str(e)}")
                continue
        
        # Resumen final
        logger.info("\n" + "="*60)
        logger.info("📊 RESUMEN DE NOTIFICACIONES")
        logger.info("="*60)
        logger.info(f"✅ Correos enviados exitosamente: {emails_sent}")
        logger.error(f"❌ Correos fallidos: {emails_failed}")
        logger.info(f"📨 Total procesados: {len(notifications)}")
        logger.info("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Error general en la tarea de notificaciones: {str(e)}")
    finally:
        db.close()


# Configurar el scheduler
scheduler = BackgroundScheduler()

# Tarea diaria de formularios programados (7:00 AM)
scheduler.add_job(
    daily_schedule_task, 
    "cron", 
    hour=7, 
    minute=0,
    id="daily_forms_task"
)

# ✅ NUEVA TAREA: Notificaciones de reglas (8:00 AM)
scheduler.add_job(
    notification_rules_task,
    "cron",
    hour=15,
    minute=29,
    id="notification_rules_task"
)

# Iniciar el scheduler
scheduler.start()

logger.info("\n" + "="*60)
logger.info("📅 TAREAS PROGRAMADAS CONFIGURADAS")
logger.info("="*60)
logger.info("⏰ Formularios programados: Diario a las 7:00 AM")
logger.info("⏰ Notificaciones de reglas: Diario a las 8:00 AM")
logger.info("="*60 + "\n")