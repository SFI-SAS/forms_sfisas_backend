import os

from fastapi import APIRouter, HTTPException, Request, Response, status, Depends
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import Token, UserTokenOut
from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    REFRESH_TOKEN_DAYS,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_password,
    get_current_user,
)
from app.crud import get_user_by_email
from fastapi.security import OAuth2PasswordRequestForm
from app.models import User, AuthEvent


def _client_ip(request: Request) -> str:
    """IP del cliente respetando el proxy (CapRover/nginx) vía X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for") if request else None
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (request.client.host if request and request.client else "")[:64]


def _log_auth_event(db, event_type: str, *, user_id=None, email=None,
                    ip: str = "", detail: str = None) -> None:
    """SM-CARGO-01: registra un evento de auth. Nunca debe romper el login."""
    try:
        db.add(AuthEvent(event_type=event_type, user_id=user_id,
                         email=email, ip=ip, detail=detail))
        db.commit()
    except Exception:
        db.rollback()


# H-BW-005: helper para emitir las dos cookies de auth en una llamada.
def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    is_production = os.getenv("ENV") != "development"
    samesite      = "strict" if is_production else "lax"

    # Cookie de access — corta vida, scope global (la lee el middleware SSR).
    response.set_cookie(
        key      = "token",
        value    = access_token,
        max_age  = ACCESS_TOKEN_MINUTES * 60,
        httponly = True,
        secure   = is_production,
        samesite = samesite,
        path     = "/",
    )
    # Cookie de refresh — larga vida, path restringido a /auth/refresh.
    # Esto reduce la superficie: solo se envía cuando el cliente pide refresh.
    response.set_cookie(
        key      = "refresh_token",
        value    = refresh_token,
        max_age  = REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        httponly = True,
        secure   = is_production,
        samesite = samesite,
        path     = "/auth/refresh",
    )


def _clear_auth_cookies(response: Response) -> None:
    # Borrar ambas cookies. El path debe coincidir con el de set_cookie.
    response.delete_cookie("token", path="/")
    response.delete_cookie("refresh_token", path="/auth/refresh")


class ValidateTokenResponse(BaseModel):
    """H-BW-004: wrapper de respuesta para /validate-token. Aísla el ORM
    `User` (que incluye el hash de password) detrás del schema UserTokenOut."""
    message: str
    user: UserTokenOut

router = APIRouter()


@router.post("/token", response_model=Token)
def login_for_access_token(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    **Login para obtener el token de acceso**:
    Este endpoint permite que un usuario se autentique mediante su correo electrónico y contraseña. Si las credenciales son correctas, se generará un token de acceso.

    - **form_data.username**: El correo electrónico del usuario.
    - **form_data.password**: La contraseña del usuario.

    **Respuestas:**
    - **200 OK**: Devuelve un token de acceso en formato Bearer.
    - **401 Unauthorized**: Si las credenciales son incorrectas o el usuario no existe.

    **Ejemplo de respuesta exitosa**:
    ```json
    {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer"
    }
    ```

    **Ejemplo de error (credenciales incorrectas)**:
    ```json
    {
        "detail": "Incorrect username or password"
    }
    ```
    """
    user = get_user_by_email(db, form_data.username)
    if user is None or not verify_password(form_data.password, user.password):
        # SM-CARGO-01: login fallido → evento de seguridad (Cargo 7).
        _log_auth_event(
            db, "login_failed",
            user_id=(user.id if user else None),
            email=form_data.username, ip=_client_ip(request),
            detail="credenciales inválidas",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # SM-CARGO-01: login exitoso.
    _log_auth_event(db, "login_success", user_id=user.id, email=user.email, ip=_client_ip(request))

    # H-BW-005: emitir ambos tokens.
    access_token  = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})
    _set_auth_cookies(response, access_token, refresh_token)

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=Token)
def refresh_access_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    H-BW-005: Renueva el access token usando el refresh token (cookie HttpOnly).

    Flujo:
      1) Lee `refresh_token` de la cookie. Si no existe → 401.
      2) Valida que sea un refresh token válido y no expirado.
      3) Verifica que el usuario aún existe en la BD (si fue borrado, no renovamos).
      4) Emite un nuevo access token + rota el refresh token (mitiga reuso).
      5) Retorna el access en el body (para que el cliente JS lo conozca).

    No requiere `Authorization` header — la auth viene de la cookie.
    """
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    try:
        email = decode_refresh_token(token)
    except JWTError:
        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = get_user_by_email(db, email)
    if user is None:
        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )

    # Rotación: emitir refresh nuevo también. Si el viejo fue robado, queda
    # invalidado en la práctica (el atacante necesitaría usarlo antes que el
    # usuario legítimo refresque).
    new_access  = create_access_token(data={"sub": email})
    new_refresh = create_refresh_token(data={"sub": email})
    _set_auth_cookies(response, new_access, new_refresh)

    return {"access_token": new_access, "token_type": "bearer"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_clear_cookies(response: Response):
    """
    H-BW-005: Borra las cookies HttpOnly del servidor. El cleanup completo
    (localStorage, JS cookies, etc.) lo hace el cliente en `lib/auth`.
    """
    _clear_auth_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/validate-token", response_model=ValidateTokenResponse, status_code=status.HTTP_200_OK)
def validate_token(current_user: User = Depends(get_current_user)):
    """
    **Validación del token de acceso**:
    Este endpoint permite verificar si el token de acceso es válido. Si el token es válido, devuelve un mensaje de confirmación junto con los datos del usuario.

    - **current_user**: El usuario autenticado basado en el token.

    **Respuestas:**
    - **200 OK**: Si el token es válido, devuelve un mensaje y los datos del usuario autenticado.

    **Ejemplo de respuesta exitosa**:
    ```json
    {
        "message": "Token is valid",
        "user": {
            "id": 1,
            "email": "user@example.com",
            "full_name": "User Example",
            "is_active": true
        }
    }
    ```

    **Nota**: Si llegas a este punto, significa que el token de acceso proporcionado es válido.
    """
    return {"message": "Token is valid", "user": current_user}


