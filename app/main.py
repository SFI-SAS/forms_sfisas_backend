from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader
from app.crud import  get_response_details_logic, get_schedules_by_frequency
from app.database import SessionLocal, engine
from app.models import Base
from app.api.endpoints import list_form, pdf_router, projects, responses, responsibilitytransfer, users, forms, auth, questions
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI(
    title="Safemetrics Forms API",
    version="1.0.0",
    description="API para gestión de formularios",
    openapi_version="3.1.0"  # o "3.0.3" si prefieres
)

origins = [
    "https://forms.sfisas.com.co",
    "https://app.safemetrics.co",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# origins = ["*"]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


templates_env = Environment(loader=FileSystemLoader("app/api/templates"))

app.state.templates_env = templates_env
# Incluye los routers de los diferentes módulos
app.include_router(pdf_router.router, prefix="/pdf", tags=["pdf"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(forms.router, prefix="/forms", tags=["forms"])
app.include_router(questions.router, prefix="/questions", tags=["questions"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router,prefix="/projects", tags=["projects"] )
app.include_router(responses.router,prefix="/responses", tags=["responses"] )
app.include_router(list_form.router, prefix="/list_form", tags=["list_form"] )
app.include_router(responsibilitytransfer.router, prefix="/responsibilitytransfer", tags=["responsibility_transfer"])
# Crear todas las tablas definidas en models.py
Base.metadata.create_all(bind=engine)

@app.get("/")
def read_root():
    return {"message": "Bienvenido a Formularios de SFI"}




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
scheduler.add_job(daily_schedule_task, "cron", hour=7, minute=00)  # Ejecutar todos los días a las 7:00 AM
scheduler.start()



# Detener el scheduler al apagar la app
@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()