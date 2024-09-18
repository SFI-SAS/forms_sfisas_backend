from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models import Base
from app.api.endpoints import users, forms, auth, questions

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluye los routers de los diferentes módulos
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(forms.router, prefix="/forms", tags=["forms"])
app.include_router(questions.router, prefix="/questions", tags=["questions"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])

# Crear todas las tablas definidas en models.py
Base.metadata.create_all(bind=engine)

@app.get("/")
def read_root():
    return {"message": "Bienvenido a Formularios de SFI"}