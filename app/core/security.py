from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.models import User, UserType
from app.database import get_db
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Iterable, Optional

import os
import bcrypt

load_dotenv()

# Esquema para autenticar usando OAuth2 con JWT Bearer Tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Clave secreta y algoritmo utilizados para firmar y verificar JWT
SECRET_KEY = os.getenv("SECRET_KEY")  # Define esto en tu configuración
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está configurada en variables de entorno. La app no puede iniciar.")
if len(SECRET_KEY) < 32:
    raise RuntimeError(
        f"SECRET_KEY debe tener al menos 32 caracteres (tiene {len(SECRET_KEY)}). "
        "Genera una clave segura con: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )

ALGORITHM = "HS256"

# H-BW-005: tiempos de vida calibrados.
#   - Access token: corto (30 min). Reduce la ventana de uso si el token es robado.
#   - Refresh token: largo (7 días), en cookie HttpOnly. Solo se envía a /auth/refresh.
ACCESS_TOKEN_MINUTES = 30
REFRESH_TOKEN_DAYS   = 7

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
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # H-BW-005: default reducido de 24h a 30 min.
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# H-BW-005: refresh token. Vive en cookie HttpOnly y solo se acepta en /auth/refresh.
def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({
        "exp":  datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        "type": "refresh",
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# H-BW-005: validar un refresh token y retornar el `sub` (email).
# Lanza JWTError si el token es inválido, expiró, o no es de tipo refresh.
def decode_refresh_token(token: str) -> str:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "refresh":
        raise JWTError("Token is not a refresh token")
    sub = payload.get("sub")
    if not sub:
        raise JWTError("Refresh token missing sub")
    return sub

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


def require_roles(allowed: Iterable[UserType]):
    """Dependency factory: exige que current_user tenga uno de los roles `allowed`.

    SECURITY (ID-005): helper reusable para los endpoints administrativos.
    Lanza 403 si el rol no coincide. Devuelve el User en caso de éxito,
    igual que get_current_user, para poder seguir usándolo dentro del endpoint.

    Uso:
        @router.get("/...")
        def endpoint(
            current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
        ):
            ...
    """
    allowed_set = set(allowed)

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.user_type not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los roles: {sorted(r.value for r in allowed_set)}",
            )
        return current_user

    return _checker


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