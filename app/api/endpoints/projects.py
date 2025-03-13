from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.crud import create_project, delete_project_by_id, get_all_projects, get_forms_by_project
from app.schemas import FormResponse, ProjectCreate, ProjectResponse


router = APIRouter()

@router.post("/", response_model=ProjectResponse)
def create_new_project(project: ProjectCreate, db: Session = Depends(get_db),):
    return create_project(db, project)

@router.get("/all_projects/", response_model=List[ProjectResponse])
def get_projects(db: Session = Depends(get_db)):
    return get_all_projects(db)

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_endpoint(project_id: int, db: Session = Depends(get_db)):
    return delete_project_by_id(db, project_id)


@router.get("/by-project/{project_id}", response_model=List[FormResponse])
def get_forms_by_project_endpoint(project_id: int, db: Session = Depends(get_db)):
    return get_forms_by_project(db, project_id)