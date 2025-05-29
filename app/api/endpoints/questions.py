from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import User, UserType
from app.crud import create_question, create_question_table_relation_logic, delete_question_from_db, get_answers_by_question, get_filtered_questions, get_related_or_filtered_answers, get_unrelated_questions, update_question, get_questions, get_question_by_id, create_options, get_options_by_question_id
from app.schemas import AnswerSchema, QuestionCreate, QuestionTableRelationCreate, QuestionUpdate, QuestionResponse, OptionResponse, OptionCreate
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question_endpoint(
    question: QuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Restringir la creación de preguntas solo a usuarios permitidos (e.g., admin)
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create questions"
        )
    return create_question(db=db, question=question)

@router.put("/{question_id}", response_model=QuestionResponse)
def update_question_endpoint(
    question_id: int,
    question: QuestionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Restringir la actualización de preguntas solo a usuarios permitidos (e.g., admin)
    if current_user.user_type.name != UserType.admin.name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to update questions"
        )
    
    db_question = get_question_by_id(db, question_id)
    if not db_question:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    return update_question(db=db, question_id=question_id, question=question)

@router.get("/", response_model=List[QuestionResponse])
def get_all_questions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    else:
        # Traer todas las preguntas de la base de datos
        questions = get_questions(db)
        return questions
    
    
@router.post("/options/", response_model=List[OptionResponse])
def create_multiple_options(options: List[OptionCreate], db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create options"
        )
    else: 
        return create_options(db=db, options=options)

@router.get("/options/{question_id}", response_model=List[OptionResponse])
def read_options_by_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    else: 
        return get_options_by_question_id(db=db, question_id=question_id)

@router.delete("/delete/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    else: 
        return delete_question_from_db(question_id, db)


@router.get("/{question_id}/answers", response_model=List[AnswerSchema])
def get_question_answers(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        if current_user == None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get options"
            )
        else: 
            answers = get_answers_by_question(db, question_id)

            return answers
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No se encontraron respuestas para esta pregunta"
        )
        
@router.get("/unrelated_questions/{form_id}")
def get_unrelated_questions_endpoint(form_id: int, db: Session = Depends(get_db)):
    unrelated_questions = get_unrelated_questions(db, form_id)
    return unrelated_questions



@router.get("/filtered")
def fetch_filtered_questions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Endpoint para obtener preguntas filtradas"""
    if current_user == None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get options"
            )
    else: 

        return get_filtered_questions(db, current_user.id)


@router.post("/question-table-relation/")
def create_question_table_relation(
    relation_data: QuestionTableRelationCreate,
    db: Session = Depends(get_db)
):
    relation = create_question_table_relation_logic(
        db=db,
        question_id=relation_data.question_id,
        name_table=relation_data.name_table,
        related_question_id=relation_data.related_question_id,
        field_name=relation_data.field_name  # <-- NUEVO
    )

    return {
        "message": "Relation created successfully",
        "data": {
            "id": relation.id,
            "question_id": relation.question_id,
            "related_question_id": relation.related_question_id,
            "name_table": relation.name_table,
            "field_name": relation.field_name  # <-- NUEVO
        }
    }

    
@router.get("/question-table-relation/answers/{question_id}")
def get_related_answers(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(   
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
            )
    else: 
        return get_related_or_filtered_answers(db, question_id)
