# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.middleware.gzip import GZipMiddleware 
# from jinja2 import Environment, FileSystemLoader
# from app.crud import get_response_details_logic, get_schedules_by_frequency
# from app.database import SessionLocal, engine
# from app.models import Base
# from app.api.endpoints import (
#     approvers, list_form, pdf_router, projects, responses, 
#     responsibilitytransfer, users, forms, auth, questions
# )
# from datetime import datetime
# from apscheduler.schedulers.background import BackgroundScheduler

# app = FastAPI(
#     title="Safemetrics Forms API",
#     version="1.0.0",
#     description="API para gestión de formularios",
#     openapi_version="3.1.0"
# )


# # 1. CORS debe ir primero
# origins = ["*"]  # Ajustar en producción: ["https://forms.sfisas.com.co", "https://app.safemetrics.co"]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # 2. ✅ GZIP debe ir después de CORS
# # Solo comprime respuestas mayores a 1KB (1000 bytes)
# app.add_middleware(
#     GZipMiddleware,  # ✅ GZipMiddleware (con 'i' minúscula)
#     minimum_size=1000  # Solo comprimir respuestas >1KB
# )

# # ========================================
# # CONFIGURACIÓN DE TEMPLATES
# # ========================================
# templates_env = Environment(loader=FileSystemLoader("app/api/templates"))
# app.state.templates_env = templates_env

# # ========================================
# # ROUTERS
# # ========================================
# app.include_router(pdf_router.router, prefix="/pdf", tags=["pdf"])
# app.include_router(users.router, prefix="/users", tags=["users"])
# app.include_router(forms.router, prefix="/forms", tags=["forms"])
# app.include_router(approvers.router, prefix="/approvers", tags=["approvers"])
# app.include_router(questions.router, prefix="/questions", tags=["questions"])
# app.include_router(auth.router, prefix="/auth", tags=["auth"])
# app.include_router(projects.router, prefix="/projects", tags=["projects"])
# app.include_router(responses.router, prefix="/responses", tags=["responses"])
# app.include_router(list_form.router, prefix="/list_form", tags=["list_form"])
# app.include_router(
#     responsibilitytransfer.router, 
#     prefix="/responsibilitytransfer", 
#     tags=["responsibility_transfer"]
# )

# # ========================================
# # CREAR TABLAS
# # ========================================
# Base.metadata.create_all(bind=engine)

# # ========================================
# # ENDPOINTS
# # ========================================
# @app.get("/")
# def read_root():
#     return {"message": "Bienvenido a Formularios de SFI"}


# # ========================================
# # SCHEDULER PARA TAREAS PROGRAMADAS
# # ========================================
# DIAS_SEMANA = {
#     "monday": "lunes",
#     "tuesday": "martes",
#     "wednesday": "miercoles",
#     "thursday": "jueves",
#     "friday": "viernes",
#     "saturday": "sabado",
#     "sunday": "domingo"
# }

# def daily_schedule_task():
#     """Obtiene los registros activos para el día actual y ejecuta la lógica necesaria."""
#     print("⏳ Ejecutando tarea diaria...")

#     db = SessionLocal()
#     try:
#         schedules = get_schedules_by_frequency(db)
#         print(f"📆 Registros obtenidos para hoy: {len(schedules)}")

#         response_details = get_response_details_logic(db)
#         print(f"📌 Detalles de respuestas obtenidos: {len(response_details)}")

#         # Aquí podrías llamar a la función que envía correos u otra acción
#         # send_reminder_emails(schedules)

#     except Exception as e:
#         print(f"⚠️ Error en la tarea diaria: {str(e)}")
#     finally:
#         db.close()

# # Configurar el scheduler
# scheduler = BackgroundScheduler()
# scheduler.add_job(
#     daily_schedule_task, 
#     "cron", 
#     hour=7, 
#     minute=0
# )  # Ejecutar todos los días a las 7:00 AM
# scheduler.start()

# # Detener el scheduler al apagar la app
# @app.on_event("shutdown")
# def shutdown_event():
#     scheduler.shutdown()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware 
from jinja2 import Environment, FileSystemLoader
from app.redis_client import redis_client
from app.crud import get_response_details_logic, get_schedules_by_frequency
from app.database import SessionLocal, engine
from app.models import Base
from app.api.endpoints import (
    approvers, list_form, pdf_router, projects, responses, 
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
origins = ["*"]  # Ajustar en producción: ["https://forms.sfisas.com.co", "https://app.safemetrics.co"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. ✅ GZIP debe ir después de CORS
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000
)

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
    print("⏳ Ejecutando tarea diaria...")

    db = SessionLocal()
    try:
        schedules = get_schedules_by_frequency(db)
        print(f"📆 Registros obtenidos para hoy: {len(schedules)}")

        response_details = get_response_details_logic(db)
        print(f"📌 Detalles de respuestas obtenidos: {len(response_details)}")

        # Aquí podrías llamar a la función que envía correos u otra acción
        # send_reminder_emails(schedules)

    except Exception as e:
        print(f"⚠️ Error en la tarea diaria: {str(e)}")
    finally:
        db.close()

# Configurar el scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    daily_schedule_task, 
    "cron", 
    hour=7, 
    minute=0
)
scheduler.start()