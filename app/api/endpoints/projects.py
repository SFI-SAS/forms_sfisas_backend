from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.crud import create_project, delete_project_by_id, get_all_projects, get_forms_by_project, get_responses_by_project
from app.schemas import FormResponse, ProjectCreate, ProjectResponse
from app.models import User, UserType
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=ProjectResponse)
def create_new_project(project: ProjectCreate, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    """
    Crea un nuevo proyecto.

    Este endpoint permite a los usuarios con rol **admin** crear un nuevo proyecto.
    El proyecto incluirá información como nombre, descripción u otros campos definidos
    en el modelo `ProjectCreate`.

    Solo los usuarios con permisos de administrador pueden realizar esta acción.

    Parámetros:
    -----------
    project : ProjectCreate
        Objeto con los datos necesarios para crear el proyecto:
        - `name` (str): Nombre del proyecto.
        - `description` (str): Descripción del proyecto.
        - (otros campos definidos en el modelo `ProjectCreate`).

    db : Session
        Sesión activa de base de datos proporcionada por `get_db`.

    current_user : User
        Usuario autenticado, se utiliza para validar los permisos de administrador.

    Retorna:
    --------
    ProjectResponse:
        Objeto con los datos del proyecto recién creado.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no tiene permiso para crear proyectos.
    """
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create forms"
        )
    return create_project(db, project)

@router.get("/all_projects/", response_model=List[ProjectResponse])
def get_projects(db: Session = Depends(get_db)):
    """
    Obtiene la lista de todos los proyectos registrados.

    Este endpoint devuelve todos los proyectos almacenados en la base de datos.
    No requiere autenticación ni permisos especiales, aunque puede personalizarse
    para agregar filtros o paginación si es necesario.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos proporcionada por `get_db`.

    Retorna:
    --------
    List[ProjectResponse]:
        Lista de objetos `ProjectResponse` con la información de cada proyecto.
    """
    return get_all_projects(db)



@router.get("/by-project/{project_id}", response_model=List[FormResponse])
def get_forms_by_project_endpoint(project_id: int, db: Session = Depends(get_db)):
    """
    Obtiene todos los formularios asociados a un proyecto específico.

    Este endpoint permite recuperar la lista de formularios que pertenecen a un proyecto determinado,
    identificado por su `project_id`.

    Parámetros:
    -----------
    project_id : int
        ID del proyecto del cual se quieren obtener los formularios.

    db : Session
        Sesión activa de la base de datos proporcionada por la dependencia `get_db`.

    Retorna:
    --------
    List[FormResponse]:
        Lista de formularios (`FormResponse`) vinculados al proyecto.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentran formularios asociados al proyecto.
    """
    return get_forms_by_project(db, project_id)

@router.get("/responses-by-project/{project_id}")
def get_responses_by_project_endpoint(project_id: int, db: Session = Depends(get_db)):
    """
    Obtiene las respuestas de formularios asociadas a un proyecto específico.

    Este endpoint permite recuperar todas las respuestas registradas para los formularios
    que pertenecen a un proyecto determinado.

    Cada formulario incluirá sus respuestas, y dentro de cada respuesta se listan
    las respuestas detalladas (`answers`) junto con el texto de la pregunta relacionada.

    Parámetros:
    -----------
    project_id : int
        ID del proyecto del cual se desean obtener las respuestas.

    db : Session
        Sesión activa de la base de datos.

    Retorna:
    --------
    List[dict]:
        Lista de formularios que contienen:
        - `form`: Objeto del formulario.
        - `responses`: Lista de respuestas con:
            - `response`: Objeto de la respuesta.
            - `answers`: Lista de respuestas individuales con:
                - `id`: ID de la respuesta.
                - `answer_text`: Texto de la respuesta.
                - `question_text`: Texto de la pregunta correspondiente.
                - `question_id`, `response_id`, `file_path`.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentran formularios o respuestas asociadas al proyecto.
    """
    return get_responses_by_project(db, project_id)
