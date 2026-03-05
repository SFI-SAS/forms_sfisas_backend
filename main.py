from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware 
from jinja2 import Environment, FileSystemLoader
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
    alias, approvers, download_template, list_form, pdf_router, projects, responses, 
    responsibilitytransfer, users, forms, auth, questions
)

from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI(
    title="Safemetrics Forms API",
    version="1.0.0",
    description="API para gestión de formularios",
    openapi_version="3.1.0"
)


# 1. CORS debe ir primero
origins = ["https://forms.sfisas.com.co", "https://app.safemetrics.co", "*"]  # Ajustar en producción: ["https://forms.sfisas.com.co", "https://app.safemetrics.co"]

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

    # Bloquear XSS en browsers antiguos
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # No permitir acceso a cámara, micrófono, geolocation, etc.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    # Content Security Policy — ajusta los dominios a los tuyos
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
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

# ========================================
# CREAR TABLAS
# ========================================
Base.metadata.create_all(bind=engine)

# ========================================
# EVENTOS DE INICIO Y CIERRE
# ========================================
@app.on_event("startup")
async def startup_event():
    """Se ejecuta al iniciar la aplicación"""
    print("🚀 Iniciando aplicación...")
    
    # Verificar conexión a Redis
    if redis_client.check_connection():
        print("✅ Redis conectado correctamente")
    else:
        print("⚠️ Advertencia: Redis no está disponible")

@app.on_event("shutdown")
async def shutdown_event():
    """Se ejecuta al apagar la aplicación"""
    print("🛑 Apagando aplicación...")
    scheduler.shutdown()

# ========================================
# ENDPOINTS
# ========================================
@app.get("/")
def read_root():
    return {"message": "Bienvenido a Formularios de SFI"}

@app.get("/health")
def health_check():
    """Endpoint para verificar estado de la API y Redis"""
    redis_status = redis_client.check_connection()
    return {
        "status": "ok",
        "redis_connected": redis_status
    }

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
    print("⏳ Ejecutando tarea diaria de formularios programados...")

    db = SessionLocal()
    try:
        schedules = get_schedules_by_frequency(db)
        print(f"📆 Registros obtenidos para hoy: {len(schedules)}")

        response_details = get_response_details_logic(db)
        print(f"📌 Detalles de respuestas obtenidos: {len(response_details)}")

    except Exception as e:
        print(f"⚠️ Error en la tarea diaria de formularios: {str(e)}")
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    """Se ejecuta al iniciar la aplicación"""
    print("🚀 Iniciando aplicación...")
    
    # ====== INICIALIZAR EMAIL_CONFIG ======
    db = SessionLocal()
    try:
        # Verificar si ya existen registros
        email_count = db.query(EmailConfig).count()
        
        if email_count == 0:
            db.add_all([
                EmailConfig(email_address="example1@domain.com", is_active=False),
                EmailConfig(email_address="example2@domain.com", is_active=False),
            ])
            db.commit()
            print("✅ Registros de email_config inicializados")
        else:
            print(f"ℹ️ email_config ya contiene {email_count} registros")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al inicializar email_config: {str(e)}")
    finally:
        db.close()
    
    # Verificar conexión a Redis
    if redis_client.check_connection():
        print("✅ Redis conectado correctamente")
    else:
        print("⚠️ Advertencia: Redis no está disponible")
        
def notification_rules_task():
    """
    Tarea programada para enviar notificaciones de reglas de vencimiento.
    Se ejecuta diariamente y:
    1. Busca reglas que deben notificarse hoy
    2. Envía correos de alerta
    3. Deshabilita las reglas ya notificadas
    """
    print("\n" + "="*60)
    print("⏰ Ejecutando tarea de notificaciones de reglas...")
    print("="*60)

    db = SessionLocal()
    emails_sent = 0
    emails_failed = 0
    
    try:
        # Obtener notificaciones pendientes
        notifications = get_pending_notification_rules(db)
        
        if not notifications:
            print("✅ No hay notificaciones pendientes para hoy")
            return
        
        print(f"\n📬 Procesando {len(notifications)} notificaciones...")
        
        # Procesar cada notificación
        for notification in notifications:
            try:
                print(f"\n📧 Enviando correo a {notification['user_email']}...")
                
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
                        print(f"   ✅ Correo enviado y regla ID {notification['rule_id']} deshabilitada")
                    else:
                        print(f"   ⚠️ Correo enviado pero no se pudo deshabilitar la regla ID {notification['rule_id']}")
                else:
                    emails_failed += 1
                    print(f"   ❌ No se pudo enviar el correo a {notification['user_email']}")
                    
            except Exception as e:
                emails_failed += 1
                print(f"   ❌ Error procesando notificación para {notification.get('user_email', 'email desconocido')}: {str(e)}")
                continue
        
        # Resumen final
        print("\n" + "="*60)
        print("📊 RESUMEN DE NOTIFICACIONES")
        print("="*60)
        print(f"✅ Correos enviados exitosamente: {emails_sent}")
        print(f"❌ Correos fallidos: {emails_failed}")
        print(f"📨 Total procesados: {len(notifications)}")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"❌ Error general en la tarea de notificaciones: {str(e)}")
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

print("\n" + "="*60)
print("📅 TAREAS PROGRAMADAS CONFIGURADAS")
print("="*60)
print("⏰ Formularios programados: Diario a las 7:00 AM")
print("⏰ Notificaciones de reglas: Diario a las 8:00 AM")
print("="*60 + "\n")