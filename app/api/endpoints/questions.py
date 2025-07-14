from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Question, QuestionCategory, QuestionLocationRelation, User, UserType
from app.crud import create_question, create_question_table_relation_logic, delete_question_from_db, get_answers_by_question, get_filtered_questions, get_related_or_filtered_answers, get_unrelated_questions, update_question, get_questions, get_question_by_id, create_options, get_options_by_question_id
from app.schemas import AnswerSchema, QuestionCategoryCreate, QuestionCategoryOut, QuestionCreate, QuestionLocationRelationCreate, QuestionLocationRelationOut, QuestionTableRelationCreate, QuestionUpdate, QuestionResponse, OptionResponse, OptionCreate, QuestionWithCategory, UpdateQuestionCategory
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question_endpoint(
    question: QuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea una nueva pregunta en el sistema.

    Solo los usuarios con rol de **administrador** pueden crear preguntas.  
    Este endpoint guarda una nueva pregunta en la base de datos, incluyendo el texto, tipo y configuración.

    Parámetros:
    -----------
    question : QuestionCreate
        Objeto con los datos de la nueva pregunta:
        - `question_text` (str): Texto de la pregunta.
        - `question_type` (str): Tipo de pregunta (por ejemplo: "text", "select").
        - `required` (bool): Si la pregunta es obligatoria o no.
        - `root` (bool): Si la pregunta es una pregunta raíz o no.

    db : Session
        Sesión de base de datos proporcionada por la dependencia `get_db`.

    current_user : User
        Usuario autenticado, extraído mediante `get_current_user`.

    Retorna:
    --------
    QuestionResponse:
        Objeto con los datos de la pregunta creada.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no tiene permisos para crear preguntas.
        - 400: Si ocurre un error de integridad al guardar la pregunta.
    """
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
    """
    Obtiene respuestas dinámicas relacionadas o filtradas para una pregunta específica.

    Este endpoint verifica si una pregunta tiene una condición de filtro (`QuestionFilterCondition`)
    o una relación con otra pregunta o una tabla externa (`QuestionTableRelation`).
    Dependiendo de eso, retorna las respuestas correspondientes.

    Parámetros:
    -----------
    question_id : int
        ID de la pregunta para la que se buscan respuestas relacionadas o filtradas.

    db : Session
        Sesión activa de base de datos proporcionada por `get_db`.

    current_user : User
        Usuario autenticado requerido para acceder al recurso.

    Retorna:
    --------
    dict:
        Diccionario con los campos:
        - `source` (str): origen de los datos (`condicion_filtrada`, `pregunta_relacionada`, `usuarios`, etc.).
        - `data` (List[dict]): lista de respuestas con el campo `name`.

    Lanza:
    ------
    HTTPException:
        - 403: Si el usuario no está autenticado.
        - 404: Si no se encuentra relación para la pregunta.
        - 400: Si la tabla o campo especificado no es válido.
    """
    if current_user == None:
        raise HTTPException(   
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get all questions"
            )
    else: 
        return get_related_or_filtered_answers(db, question_id)


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