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
    # Si llegas a este punto, significa que el token es válido
    return {"message": "Token is valid", "user": current_user}