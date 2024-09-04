from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.models import User
from app.database import get_db
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

import os
import bcrypt

load_dotenv()

# Esquema para autenticar usando OAuth2 con JWT Bearer Tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Clave secreta y algoritmo utilizados para firmar y verificar JWT
SECRET_KEY = os.getenv("SECRET_KEY")  # Define esto en tu configuración
ALGORITHM = "HS256"

# Define el modelo de datos para el payload del token
class TokenData(BaseModel):
    email: str

# Función para crear el token de acceso
def create_access_token(
    data: dict, 
    expires_delta: Optional[timedelta] = None
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)  # Tiempo de expiración por defecto
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Función para obtener el usuario actual basado en el token JWT
def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decodificar el token para obtener los datos del usuario
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Buscar el usuario en la base de datos
    user = db.query(User).filter(User.email == user_id).first()
    if user is None:
        raise credentials_exception
    return user

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.
    """
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hashed password.
    """
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))