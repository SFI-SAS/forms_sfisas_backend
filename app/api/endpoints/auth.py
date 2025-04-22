from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import Token
from app.core.security import create_access_token, verify_password, get_current_user
from app.crud import get_user_by_email
from typing import Annotated
from fastapi.security import OAuth2PasswordRequestForm
from app.models import User

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]

@router.post("/token", response_model=Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/validate-token", status_code=status.HTTP_200_OK)
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


