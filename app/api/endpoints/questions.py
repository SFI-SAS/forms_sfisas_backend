
# Changes to be committed:
#	modified:   app/api/endpoints/questions.py
#

import hashlib
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.params import Query
from pymysql import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import Alias, FormQuestion, Question, QuestionCategory, QuestionFilterCondition, QuestionLocationRelation, QuestionTableRelation, QuestionType, User, UserType
from app.crud import  create_question_table_relation_logic, delete_question_from_db, get_answers_by_question, get_answers_by_question_id, get_filtered_questions, get_question_by_id_with_category, get_questions_by_category_id, get_related_or_filtered_answers_optimized, get_related_or_filtered_answers_with_forms, get_unrelated_questions, update_question, get_questions, get_question_by_id, create_options, get_options_by_question_id
from app.schemas import AnswerByQuestionResponse, AnswerSchema, DetectSelectRelationsRequest, QuestionCategoryCreate, QuestionCategoryOut, QuestionCreate, QuestionLocationRelationCreate, QuestionLocationRelationOut, QuestionTableRelationCreate, QuestionUpdate, QuestionResponse, OptionResponse, OptionCreate, QuestionWithCategory, UpdateQuestionCategory
from app.core.security import get_current_user

router = APIRouter()

# En: app/routes/questions.py

@router.post("/", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question_endpoint(
    question: QuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea una nueva pregunta con alias opcional.
    """
    if current_user.user_type.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create questions"
        )
    
    # ⭐ VALIDAR QUE EL ALIAS EXISTA
    if question.id_alias:
        alias = db.query(Alias).filter(Alias.id == question.id_alias).first()
        if not alias:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El alias especificado no existe"
            )
    
    try:
        db_question = Question(
            question_text=question.question_text,
            description=question.description,
            question_type=question.question_type,
            required=question.required,
            root=question.root,
            id_category=question.id_category,
            id_alias=question.id_alias  # ⭐ AGREGAR ESTA LÍNEA
        )
        db.add(db_question)
        db.commit()
        db.refresh(db_question)
        return db_question
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error to create a question with the provided information"
        )

@router.put("/{question_id}", response_model=QuestionResponse)
def update_question_endpoint(
    question_id: int,
    question: QuestionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza una pregunta existente en el sistema.

    Solo los usuarios con rol de **administrador** pueden modificar preguntas.  
    Este endpoint permite actualizar uno o más campos de una pregunta existente, como su texto, tipo o si es obligatoria.

    Parámetros:
    -----------
    question_id : int
        ID de la pregunta que se desea actualizar.

    question : QuestionUpdate
        Objeto con los nuevos datos de la pregunta. Solo se actualizarán los campos proporcionados:
        - `question_text` (str, opcional): Nuevo texto de la pregunta.
        - `question_type` (str, opcional): Nuevo tipo de pregunta.
        - `required` (bool, opcional): Nuevo valor que indica si es obligatoria.
        - `root` (bool, opcional): Nuevo valor que indica si es pregunta raíz.

    db : Session
        Sesión de base de datos proporcionada por la dependencia `get_db`.

    current_user : User
        Usuario autenticado, extraído mediante `get_current_user`.

    Retorna:
    --------
    QuestionResponse:
        Objeto con los datos actualizados de la pregunta.

    Lanza:
    ------
    
    HTTPException:
        - 403: Si el usuario no tiene permisos para actualizar preguntas.
        - 404: Si la pregunta con el ID especificado no existe.
        - 400: Si ocurre un error de integridad al actualizar la pregunta.
    """
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

@router.get("/", response_model=List[QuestionWithCategory])
def get_all_questions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene todas las preguntas registradas en el sistema.

    Este endpoint permite recuperar una lista de todas las preguntas disponibles en la base de datos.  
    El usuario debe estar autenticado para poder acceder a esta información.

    Parámetros:
    -----------
    db : Session
        Sesión de base de datos proporcionada por la dependencia `get_db`.

    current_user : User
        Usuario autenticado, extraído mediante `get_current_user`.

    Retorna:
    --------
    List[QuestionResponse]:
        Lista de objetos que representan las preguntas almacenadas.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    else:
        # Traer todas las preguntas de la base de datos
        questions = get_questions(db)
        return questions

@router.get("/get_question_by_id_with_category/{question_id}", response_model=QuestionWithCategory)
def get_question_by_id_endpoint(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene una pregunta específica por su ID.

    Parámetros:
    -----------
    question_id : int
        ID de la pregunta a consultar.
    
    db : Session
        Sesión de base de datos proporcionada por la dependencia `get_db`.

    current_user : User
        Usuario autenticado, extraído mediante `get_current_user`.

    Retorna:
    --------
    QuestionWithCategory:
        Objeto que representa la pregunta con su categoría.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
        - 404: Si la pregunta no existe.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get this question"
        )

    
    question = get_question_by_id_with_category(db, question_id)
    
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with id {question_id} not found"
        )
    
    return question
    
@router.post("/options/", response_model=List[OptionResponse])
def create_multiple_options(options: List[OptionCreate], db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Crea múltiples opciones para una o varias preguntas.

    Este endpoint permite crear varias opciones de respuesta asociadas a preguntas existentes.  
    El usuario debe estar autenticado para realizar esta operación.

    Parámetros:
    -----------
    options : List[OptionCreate]
        Lista de objetos con los datos de cada opción a crear:
        - `question_id` (int): ID de la pregunta a la que pertenece la opción.
        - `option_text` (str): Texto de la opción.

    db : Session
        Sesión activa de la base de datos proporcionada por la dependencia `get_db`.

    current_user : User
        Usuario autenticado mediante `get_current_user`.

    Retorna:
    --------
    List[OptionResponse]:
        Lista con las opciones creadas exitosamente.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
        - 400: Si ocurre un error de integridad al crear las opciones.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create options"
        )
    else: 
        return create_options(db=db, options=options)

@router.get("/options/{question_id}", response_model=List[OptionResponse])
def read_options_by_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Obtiene todas las opciones asociadas a una pregunta específica.

    Este endpoint permite recuperar la lista de opciones de respuesta vinculadas a una pregunta determinada por su ID.  
    El usuario debe estar autenticado para acceder a esta información.

    Parámetros:
    -----------
    question_id : int
        ID de la pregunta de la cual se desean obtener las opciones.

    db : Session
        Sesión activa de la base de datos, inyectada mediante la dependencia `get_db`.

    current_user : User
        Usuario autenticado mediante la dependencia `get_current_user`.

    Retorna:
    --------
    List[OptionResponse]:
        Lista de opciones asociadas a la pregunta especificada.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    else: 
        return get_options_by_question_id(db=db, question_id=question_id)

@router.delete("/delete/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Elimina una pregunta y todas sus relaciones en cascada.

    Este endpoint permite eliminar una pregunta del sistema junto con todas sus dependencias, como respuestas, opciones, relaciones y filtros.  
    El usuario debe estar autenticado para ejecutar esta operación.

    Parámetros:
    -----------
    question_id : int
        ID de la pregunta que se desea eliminar.

    db : Session
        Sesión activa de la base de datos proporcionada por `get_db`.

    current_user : User
        Usuario autenticado mediante `get_current_user`.

    Retorna:
    --------
    dict:
        Mensaje de confirmación o resultado de la operación.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
        )
    else: 
        return delete_question_from_db(db, question_id)


@router.get("/{question_id}/answers", response_model=List[AnswerSchema])
def get_question_answers(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Obtiene todas las respuestas asociadas a una pregunta específica.

    Este endpoint permite recuperar las respuestas que han sido registradas para una pregunta específica,
    identificada por su `question_id`. El usuario debe estar autenticado para acceder a la información.

    Parámetros:
    -----------
    question_id : int
        ID de la pregunta cuyas respuestas se desean consultar.

    db : Session
        Sesión activa de base de datos, proporcionada por `get_db`.

    current_user : User
        Usuario autenticado mediante `get_current_user`.

    Retorna:
    --------
    List[AnswerSchema]:
        Lista de respuestas correspondientes a la pregunta.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
        - 403: Si ocurre un error o no se encuentran respuestas (se podría cambiar a 404 si prefieres más precisión).
    """
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
    """
    Obtiene todas las preguntas que no están relacionadas con un formulario específico.

    Este endpoint devuelve una lista de preguntas que aún no están asociadas al formulario con el `form_id` proporcionado.  
    Es útil para agregar nuevas preguntas a un formulario sin duplicar las ya relacionadas.

    Parámetros:
    -----------
    form_id : int
        ID del formulario al que se desea buscar preguntas no relacionadas.

    db : Session
        Sesión activa de base de datos proporcionada por la dependencia `get_db`.

    Retorna:
    --------
    List[Question]:
        Lista de preguntas que no están asociadas al formulario indicado.
    """
    unrelated_questions = get_unrelated_questions(db, form_id)
    return unrelated_questions



@router.get("/filtered")
def fetch_filtered_questions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Obtiene preguntas raíz, sus respuestas únicas y formularios no raíz asignados al usuario.

    Este endpoint devuelve:
    - Preguntas donde `root=True`.
    - Respuestas únicas asociadas a esas preguntas.
    - Formularios donde `is_root=False` y que estén asignados al usuario autenticado.

    El usuario debe estar autenticado para acceder a este recurso.

    Parámetros:
    -----------
    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado extraído mediante la dependencia `get_current_user`.

    Retorna:
    --------
    dict:
        Un diccionario con:
        - `default_questions`: Lista de preguntas raíz (`root=True`).
        - `answers`: Diccionario con respuestas únicas agrupadas por pregunta.
        - `non_root_forms`: Lista de formularios asignados al usuario (`is_root=False`).

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
    """
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
    """
    Crea una relación entre una pregunta y una tabla externa.

    Este endpoint permite establecer una relación entre una pregunta y una tabla externa
    (por ejemplo, para cargar datos dinámicamente) mediante un campo específico.
    Opcionalmente, también puede relacionarse con otra pregunta.

    Parámetros:
    -----------
    relation_data : QuestionTableRelationCreate
        Objeto con la información necesaria para crear la relación:
        - `question_id` (int): ID de la pregunta origen.
        - `name_table` (str): Nombre de la tabla relacionada.
        - `related_question_id` (Optional[int]): ID de la pregunta relacionada (si aplica).
        - `field_name` (Optional[str]): Campo específico que se utilizará en la relación.

    db : Session
        Sesión activa de base de datos proporcionada por la dependencia `get_db`.

    Retorna:
    --------
    dict:
        Diccionario con un mensaje de éxito y los datos de la relación creada.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentra la pregunta o la pregunta relacionada.
        - 400: Si ya existe una relación para la pregunta dada.
    """
    relation = create_question_table_relation_logic(
        db=db,
        question_id=relation_data.question_id,
        name_table=relation_data.name_table,
        related_question_id=relation_data.related_question_id,
        related_form_id=relation_data.related_form_id,
        field_name=relation_data.field_name  # <-- NUEVO
    )

    return {
        "message": "Relation created successfully",
        "data": {
            "id": relation.id,
            "question_id": relation.question_id,
            "related_question_id": relation.related_question_id,
            "related_form_id": relation.related_form_id,
            "name_table": relation.name_table,
            "field_name": relation.field_name  # <-- NUEVO
        }
    }

@router.get("/question-table-relation/answers/all")
def get_all_related_answers(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene todas las respuestas dinámicas relacionadas o filtradas para todas las preguntas.
    
    Este endpoint procesa todas las preguntas que tienen relaciones de tabla o condiciones de filtro,
    retornando la información completa de formularios y respuestas para cada una.

    Retorna:
    --------
    dict:
        Diccionario con el campo:
        - `questions` (List[dict]): lista de todas las preguntas con sus relaciones, cada una contiene:
            - `question_id` (int): ID de la pregunta
            - `source` (str): origen de los datos
            - `data` (List[dict]): lista de respuestas únicas
            - `forms` (List[dict]): formularios completos con sus respuestas
            - `related_question` (dict): información de la pregunta relacionada (si aplica)
            - `correlations` (dict): mapa de correlaciones entre respuestas
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    
    # Obtener todas las preguntas que tienen relaciones o condiciones
    relations = db.query(QuestionTableRelation).all()
    conditions = db.query(QuestionFilterCondition).all()
    
    # Crear un conjunto de question_ids únicos
    question_ids = set()
    
    # Agregar IDs de relaciones
    for relation in relations:
        question_ids.add(relation.question_id)
    
    # Agregar IDs de condiciones
    for condition in conditions:
        question_ids.add(condition.filtered_question_id)
    
    # Procesar cada pregunta
    all_questions_data = []
    
    for question_id in question_ids:
        try:
            question_data = get_related_or_filtered_answers_with_forms(db, question_id)
            
            # Agregar el question_id al resultado
            all_questions_data.append({
                "question_id": question_id,
                **question_data
            })
        except HTTPException as e:
            # Si hay error con una pregunta específica, continuar con las demás
            print(f"Error procesando pregunta {question_id}: {e.detail}")
            continue
        except Exception as e:
            print(f"Error inesperado procesando pregunta {question_id}: {str(e)}")
            continue
    
    return {
        "total_questions": len(all_questions_data),
        "questions": all_questions_data
    }

# Endpoint actualizado
@router.get("/question-table-relation/answers/{question_id}")
def get_related_answers(
    question_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene respuestas dinámicas relacionadas o filtradas para una pregunta específica.
    
    OPTIMIZACIÓN: Solo retorna data esencial (respuestas únicas + correlaciones).
    NO incluye formularios completos para reducir el payload drásticamente.

    Retorna:
    --------
    dict:
        - `source`: origen de los datos
        - `data`: lista de respuestas únicas con el campo `name`
        - `correlations`: mapeo de correlaciones entre respuestas
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
        )
    
    return get_related_or_filtered_answers_optimized(db, question_id)



@router.post("/location-relation", status_code=201)
def create_location_relation(
    relation: QuestionLocationRelationCreate,
    db: Session = Depends(get_db)
):
    """
    Crea una relación de ubicación entre dos preguntas dentro de un formulario.

    Este endpoint permite registrar una relación entre una pregunta origen y una pregunta destino
    dentro de un formulario específico. Sirve para vincular campos que representan ubicaciones
    geográficas o dependencias entre preguntas.

    Parámetros:
    -----------
    relation : QuestionLocationRelationCreate
        Objeto con los datos necesarios para crear la relación:
        - `form_id` (int): ID del formulario donde se establece la relación.
        - `origin_question_id` (int): ID de la pregunta origen (por ejemplo, departamento).
        - `target_question_id` (int): ID de la pregunta destino (por ejemplo, municipio).

    db : Session
        Sesión de base de datos proporcionada por la dependencia `get_db`.

    Retorna:
    --------
    dict:
        - `message`: Mensaje de confirmación.
        - `id`: ID de la relación creada.

    Lanza:
    ------
    HTTPException:
        - 400: Si ya existe una relación con los mismos `form_id`, `origin_question_id` y `target_question_id`.
    """
    # Validación opcional: evita duplicados exactos
    existing = db.query(QuestionLocationRelation).filter_by(
        form_id=relation.form_id,
        origin_question_id=relation.origin_question_id,
        target_question_id=relation.target_question_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Relation already exists.")

    new_relation = QuestionLocationRelation(
        form_id=relation.form_id,
        origin_question_id=relation.origin_question_id,
        target_question_id=relation.target_question_id
    )

    db.add(new_relation)
    db.commit()
    db.refresh(new_relation)
    return {"message": "Relation created successfully", "id": new_relation.id}

@router.get("/location-relation/{form_id}", response_model=List[QuestionLocationRelationOut])
def get_location_relations_by_form_id(form_id: int, db: Session = Depends(get_db)):
    """
    Obtiene las relaciones de ubicación asociadas a un formulario específico.

    Este endpoint retorna todas las relaciones entre preguntas de ubicación (por ejemplo, 
    departamento → municipio) registradas para un formulario dado.

    Parámetros:
    -----------
    form_id : int
        ID del formulario del cual se desean obtener las relaciones de ubicación.

    db : Session
        Sesión activa de la base de datos proporcionada por la dependencia `get_db`.

    Lanza:
    ------
    HTTPException:
        - 404: Si no se encuentran relaciones para el formulario especificado.
    """
    relations = db.query(QuestionLocationRelation).filter_by(form_id=form_id).all()

    if not relations:
        raise HTTPException(status_code=404, detail="No se encontraron relaciones para este formulario")

    return relations

@router.post("/categories", status_code=201)
def create_question_category(
    category: QuestionCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to create categories"
        )

    existing = db.query(QuestionCategory).filter(QuestionCategory.name == category.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="La categoría ya existe")

    new_category = QuestionCategory(name=category.name, parent_id=category.parent_id)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)

    return {"id": new_category.id, "name": new_category.name, "parent_id": new_category.parent_id}


@router.get("/categories", response_model=List[QuestionCategoryOut])
def get_all_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get categories"
        )

    # Solo las categorías raíz (padre None)
    root_categories = db.query(QuestionCategory).filter(QuestionCategory.parent_id == None).all()
    return root_categories



@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    category = db.query(QuestionCategory).filter(QuestionCategory.id == category_id).first()
    
    if not category:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")

    # Poner id_category = NULL en las preguntas relacionadas
    db.query(Question).filter(Question.id_category == category_id).update(
        {Question.id_category: None}
    )

    # Eliminar la categoría
    db.delete(category)
    db.commit()
    return


@router.get("/categories/all", response_model=List[QuestionCategoryOut])
def get_all_categories_including_subcategories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get categories"
        )
    
    # Obtener todas las categorías (incluyendo subcategorías)
    all_categories = db.query(QuestionCategory).all()
    return all_categories

@router.put("/{question_id}/category")
def update_question_category(
    question_id: int,
    category_data: UpdateQuestionCategory,
    db: Session = Depends(get_db),current_user: User = Depends(get_current_user)
):
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")

    if category_data.id_category is not None:
        category = db.query(QuestionCategory).filter(QuestionCategory.id == category_data.id_category).first()
        if not category:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")

    question.id_category = category_data.id_category
    db.commit()
    db.refresh(question)

    return {
        "message": "Categoría actualizada correctamente",
        "question_id": question.id,
        "new_category_id": question.id_category
    }
    
@router.get("/get_questions_by_category/", response_model=List[QuestionWithCategory])
def get_questions_by_category(
    category_id: Optional[int] = Query(None, description="ID de la categoría. Si es null, trae preguntas sin categoría"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene las preguntas filtradas por categoría.

    Este endpoint permite recuperar preguntas de una categoría específica.
    - Si se proporciona category_id: trae preguntas de esa categoría
    - Si category_id es null: trae preguntas sin categoría asignada

    Parámetros:
    -----------
    category_id : Optional[int]
        ID de la categoría para filtrar. Si es None, trae preguntas sin categoría.
    
    db : Session
        Sesión de base de datos proporcionada por la dependencia `get_db`.

    current_user : User
        Usuario autenticado, extraído mediante `get_current_user`.

    Retorna:
    --------
    List[QuestionWithCategory]:
        Lista de preguntas filtradas según la categoría.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get questions"
        )
    
    # Traer preguntas filtradas por categoría
    questions = get_questions_by_category_id(db, category_id)
    return questions


def generate_deterministic_color(source_id: int) -> str:
    """
    Genera un color único y consistente basado en el ID del formato origen.
    El mismo formato siempre tendrá el mismo color.
    """
    # Paleta de colores
    color_palette = [
        "#FF6B6B",  # Rojo coral
        "#4ECDC4",  # Turquesa
        "#45B7D1",  # Azul cielo
         "#FFD93D",  # Amarillo brillante
        "#FFA07A",  # Salmón
        "#98D8C8",  # Verde menta
        "#F7DC6F",  # Amarillo suave
        "#BB8FCE",  # Púrpura
        "#85C1E2",  # Azul claro
        "#F8B195",  # Durazno
        "#C06C84",  # Rosa oscuro
        "#A8E6CF",  # Verde agua pastel
       
        "#6BCF7F",  # Verde lima
        "#FF85A2",  # Rosa chicle
        "#95E1D3",  # Turquesa claro
    ]
    
    # Generar hash del ID y convertir a índice
    hash_object = hashlib.md5(str(source_id).encode())
    hash_int = int(hash_object.hexdigest(), 16)
    color_index = hash_int % len(color_palette)
    
    return color_palette[color_index]

@router.post("/detect-select-relations")
def detect_select_relations(
    payload: DetectSelectRelationsRequest,
    db: Session = Depends(get_db)
):
    question_ids = payload.question_ids
    
    # 📊 PASO 1: Obtener preguntas TABLE y SELECT
    questions = db.query(Question).filter(
        Question.id.in_(question_ids),
        Question.question_type.in_([
            QuestionType.table.value,
            QuestionType.one_choice.value
        ])
    ).all()

    # 🗺️ PASO 2: Construir mapa de relaciones POR FORMATO ORIGEN
    formats_map = {}
    
    for question in questions:
        # Buscar la relación de esta pregunta
        relation = db.query(QuestionTableRelation).filter(
            QuestionTableRelation.question_id == question.id
        ).first()

        if not relation or not relation.related_question_id:
            continue

        # 🔍 VERIFICAR: ¿La pregunta relacionada está en OTRO formato?
        form_question = db.query(FormQuestion).filter(
            FormQuestion.question_id == relation.related_question_id
        ).first()

        if not form_question:
            continue

        # Obtener datos de la pregunta relacionada
        related_question = db.query(Question).filter(
            Question.id == relation.related_question_id
        ).first()

        if not related_question:
            continue

        # ✅ AGRUPAR POR FORMATO ORIGEN (form_id)
        form_key = form_question.form_id
        
        if form_key not in formats_map:
            formats_map[form_key] = []

        # Evitar duplicados
        field_data = {
            "question_id": question.id,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "related_question_id": related_question.id,
            "related_question_text": related_question.question_text
        }
        
        # Verificar si ya existe este campo
        exists = any(
            f["question_id"] == question.id 
            for f in formats_map[form_key]
        )
        
        if not exists:
            formats_map[form_key].append(field_data)

    # 🎨 PASO 3: Crear grupos con colores DETERMINÍSTICOS
    autocomplete_groups = []
    
    # Ordenar por form_id para consistencia
    sorted_form_ids = sorted(formats_map.keys())
    
    for form_id in sorted_form_ids:
        fields = formats_map[form_id]
        
        if len(fields) >= 2:
            # ✅ Color determinístico basado en form_id
            assigned_color = generate_deterministic_color(form_id)
            
            autocomplete_groups.append({
                "relation_group_id": f"group_{form_id}",  # ID consistente
                "source_form_id": form_id,
                "color": assigned_color,
                "total_fields": len(fields),
                "fields": fields
            })

    return {
        "can_autocomplete": bool(autocomplete_groups),
        "total_groups": len(autocomplete_groups),
        "autocomplete_groups": autocomplete_groups
    }


@router.get(
    "/questions/{question_id}/answers",
    response_model=List[AnswerByQuestionResponse]
)
def get_answers_by_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to view answers"
        )

    answers = get_answers_by_question_id(db, question_id)

    return answers