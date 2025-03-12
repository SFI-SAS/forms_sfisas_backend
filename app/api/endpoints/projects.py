from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.crud import create_project, get_all_projects
from app.schemas import ProjectCreate, ProjectResponse


router = APIRouter()

@router.post("/", response_model=ProjectResponse)
def create_new_project(project: ProjectCreate, db: Session = Depends(get_db),):
    return create_project(db, project)

@router.get("/all_projects/", response_model=List[ProjectResponse])
def get_projects(db: Session = Depends(get_db)):
    return get_all_projects(db)