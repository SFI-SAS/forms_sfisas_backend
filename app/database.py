from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("La variable de entorno DATABASE_URL no está definida")

# Crear el engine de SQLAlchemy con manejo de reconexiones
engine = create_engine(
    DATABASE_URL,
    pool_size=10,           # conexiones activas
    max_overflow=20,        # conexiones extra en picos de carga
    pool_timeout=30,        # espera máxima antes de lanzar error por pool lleno
    pool_recycle=1800,      # recicla conexiones cada 30 min
    pool_pre_ping=True,     # <--- evita usar conexiones muertas
    pool_use_lifo=True,     # <--- usa la conexión más reciente del pool
    echo=False,             # evita logs SQL excesivos
    future=True,            # modo moderno de SQLAlchemy
)

# Crear una sesión de SQLAlchemy
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base declarativa común
Base = declarative_base()

# Dependencia para obtener la sesión de la base de datos
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
