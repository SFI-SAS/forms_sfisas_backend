# Changes to be committed:
#	modified:   app/api/endpoints/questions.py
#

import logging
import unicodedata
from collections import defaultdict
import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger(__name__)
from fastapi.params import Query
from pydantic import BaseModel, Field
from pymysql import IntegrityError
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.database import get_db
from app.models import Answer, Response, Form, Alias, FormQuestion, Question, QuestionCategory, QuestionFilterCondition, QuestionLocationRelation, QuestionTableRelation, QuestionType, RelationQuestionRule, User, UserType
from app.crud import  create_question_table_relation_logic, delete_question_from_db, get_answers_by_question, get_answers_by_question_id, get_filtered_questions, get_question_by_id_with_category, get_questions_by_category_id, get_related_or_filtered_answers_optimized, get_related_or_filtered_answers_with_forms, get_unrelated_questions, update_question, get_questions, get_question_by_id, create_options, get_options_by_question_id
from app.schemas import AnswerByQuestionResponse, AnswerSchema, DetectSelectRelationsRequest, QuestionCategoryCreate, QuestionCategoryOut, QuestionCreate, QuestionLocationRelationCreate, QuestionLocationRelationOut, QuestionTableRelationCreate, QuestionUpdate, QuestionResponse, OptionResponse, OptionCreate, QuestionUpdatePayload, QuestionWithCategory, RelationQuestionRuleCreate, RelationQuestionRuleResponse, UpdateQuestionCategory
from app.core.security import get_current_user, require_roles

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Unicidad de question_text (insensible a mayúsculas, acentos y espacios).
# No se permite crear/editar una pregunta cuyo texto ya exista. No hay constraint
# en BD (existen duplicados históricos); la regla se aplica solo a NUEVAS
# colisiones a nivel de aplicación.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_question_text(text: Optional[str]) -> str:
    """Normaliza para comparar unicidad: minúsculas, sin acentos, espacios
    colapsados/recortados."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def _find_duplicate_question(db: Session, text: str, exclude_id: Optional[int] = None):
    """Devuelve (id, texto) de la primera pregunta con texto normalizado idéntico,
    o None. Compara en Python para honrar la insensibilidad a acentos sin depender
    de extensiones de Postgres."""
    norm = _normalize_question_text(text)
    if not norm:
        return None
    q = db.query(Question.id, Question.question_text)
    if exclude_id is not None:
        q = q.filter(Question.id != exclude_id)
    for qid, qtext in q.all():
        if _normalize_question_text(qtext) == norm:
            return (qid, qtext)
    return None


@router.get("/check-text")
def check_question_text(
    question_text: str = Query(..., min_length=1),
    exclude_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Indica si ya existe una pregunta con el mismo texto (comparación insensible
    a mayúsculas, acentos y espacios). Para validación en vivo en el frontend.
    `exclude_id` excluye la propia pregunta al editar. Debe ir ANTES de cualquier
    ruta GET `/{question_id}` para no colisionar con el parámetro de ruta."""
    dup = _find_duplicate_question(db, question_text, exclude_id)
    if dup:
        return {"exists": True, "existing_id": dup[0], "existing_text": dup[1]}
    return {"exists": False}


def _normalize_answer_value(value: Optional[str]) -> str:
    """Normaliza un valor de respuesta para comparar unicidad: recorta y colapsa
    espacios y pasa a minúsculas. No quita acentos (valores como teléfonos/correos
    rara vez los usan y preferimos no fusionar valores legítimamente distintos)."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


@router.get("/{question_id}/answer-exists")
def check_answer_exists(
    question_id: int,
    value: str = Query(..., min_length=1),
    exclude_response_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Indica si `value` ya fue registrado para esta pregunta en CUALQUIER
    respuesta (alcance global por pregunta). Alimenta la validación de
    "respuestas no repetidas" al diligenciar. `exclude_response_id` ignora la
    propia respuesta al editar."""
    norm = _normalize_answer_value(value)
    if not norm:
        return {"exists": False}
    rows = get_answers_by_question_id(db, question_id)
    for r in rows:
        if exclude_response_id is not None and r.response_id == exclude_response_id:
            continue
        if _normalize_answer_value(r.answer_text) == norm:
            return {"exists": True, "response_id": r.response_id}
    return {"exists": False}


@router.get("/forms/available")
def get_available_forms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna la lista de formatos disponibles para asignar a una pregunta.
    Usado en el modal de selección de formato al crear una pregunta.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autenticado",
        )

    forms = (
        db.query(Form.id, Form.title, Form.description, Form.format_type)
        .filter(Form.is_enabled == True)
        .order_by(Form.title)
        .all()
    )

    return [
        {
            "id": f.id,
            "title": f.title,
            "description": f.description,
            "format_type": f.format_type.value if f.format_type else None,
        }
        for f in forms
    ]


@router.get("/by-form/{form_id}")
def get_questions_by_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna todas las preguntas que tienen id_form igual al form_id recibido.
    Permite saber qué preguntas pertenecen originalmente a un formato.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autenticado",
        )

    questions = (
        db.query(Question)
        .options(
            joinedload(Question.category),
            joinedload(Question.options),
            joinedload(Question.alias),
        )
        .filter(Question.id_form == form_id)
        .order_by(Question.id)
        .all()
    )

    return questions


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

    # Validar que el formato exista si se especifica
    if question.id_form:
        form_exists = db.query(Form).filter(Form.id == question.id_form).first()
        if not form_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El formato especificado no existe"
            )

    # No permitir texto duplicado (insensible a mayúsculas/acentos/espacios).
    dup = _find_duplicate_question(db, question.question_text)
    if dup:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe una pregunta con ese texto (#{dup[0]}). No se permiten preguntas duplicadas."
        )

    try:
        db_question = Question(
            question_text=question.question_text.upper().strip() if question.question_text else question.question_text,
            description=question.description.upper().strip() if question.description else question.description,
            question_type=question.question_type,
            required=question.required,
            unique_answer=getattr(question, "unique_answer", False),
            root=question.root,
            id_category=question.id_category,
            id_alias=question.id_alias,
            id_form=question.id_form,
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

    # No permitir texto duplicado SOLO si el texto realmente cambia. Si se deja
    # igual (incluido un duplicado histórico), se permite guardar sin tocarlo.
    if (
        question.question_text is not None
        and _normalize_question_text(question.question_text)
        != _normalize_question_text(db_question.question_text)
    ):
        dup = _find_duplicate_question(db, question.question_text, exclude_id=question_id)
        if dup:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ya existe otra pregunta con ese texto (#{dup[0]}). No se permiten preguntas duplicadas."
            )

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

@router.get("/regisfacial/available")
def list_regisfacial_questions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista todas las preguntas tipo `regisfacial` del sistema con el formato
    al que están asociadas.

    Lo usa la UI de configuración de aprobadores: el admin selecciona aquí
    de qué pregunta de registro facial se validará al aprobador, igual que
    un campo `firm` selecciona su `sourceQuestionId`.

    Retorna:
        [{ id, question_text, form_id, form_name }, ...]
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autenticado",
        )

    rows = (
        db.query(
            Question.id.label("id"),
            Question.question_text.label("question_text"),
            Form.id.label("form_id"),
            Form.title.label("form_name"),
        )
        .outerjoin(FormQuestion, FormQuestion.question_id == Question.id)
        .outerjoin(Form, Form.id == FormQuestion.form_id)
        .filter(Question.question_type == QuestionType.regisfacial)
        .order_by(Form.title.nulls_last(), Question.question_text)
        .all()
    )

    # Una misma pregunta puede aparecer en varios formatos vía FormQuestion;
    # devolvemos cada combinación. La UI puede mostrarlo como "Pregunta — Formato".
    return [
        {
            "id": r.id,
            "question_text": r.question_text,
            "form_id": r.form_id,
            "form_name": r.form_name,
        }
        for r in rows
    ]


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
    if current_user is None:
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
    if current_user is None:
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
    if current_user is None:
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
        if current_user is None:
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
def get_unrelated_questions_endpoint(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """
    Obtiene todas las preguntas que no están relacionadas con un formulario específico.

    SECURITY (ID-005): requiere admin o creator (herramienta de diseño de forms).

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
    if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get options"
            )
    else: 

        return get_filtered_questions(db, current_user.id)


@router.post("/question-table-relation/")
def create_question_table_relation(
    relation_data: QuestionTableRelationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea una relación entre una pregunta y una tabla externa.

    Este endpoint permite establecer una relación entre una pregunta y una tabla externa
    (por ejemplo, para cargar datos dinámicamente) mediante un campo específico.
    Opcionalmente, también puede relacionarse con otra pregunta.

    SECURITY (ID-005 / ID-006): solo admin/creator pueden crear relaciones; además
    se bloquean campos sensibles (password, recognition_id, ...) en capa de creación
    y de lectura (ver app/crud.py: _BLOCKED_RELATION_FIELDS).

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
        - 403: Si el usuario no es admin o creator.
    """
    if current_user.user_type not in (UserType.admin, UserType.creator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo admin o creator pueden crear relaciones de tabla",
        )
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
            logger.error(f"Error procesando pregunta {question_id}: {e.detail}")
            continue
        except Exception as e:
            logger.error(f"Error inesperado procesando pregunta {question_id}: {str(e)}")
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """
    Crea una relación de ubicación entre dos preguntas dentro de un formulario.

    SECURITY (ID-005): requiere admin o creator (mutación de diseño de forms).

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
        - 403: Si el usuario no es admin o creator.
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
def get_location_relations_by_form_id(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene las relaciones de ubicación asociadas a un formulario específico.

    SECURITY (ID-005): requiere autenticación (lectura para diligenciamiento de forms).

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

    new_category = QuestionCategory(name=category.name.upper().strip() if category.name else category.name, parent_id=category.parent_id)
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
    if current_user is None:
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
    if current_user is None:
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

@router.post(
    "/relation-question-rule",
    response_model=RelationQuestionRuleResponse
)
def create_relation_question_rule(
    payload: RelationQuestionRuleCreate,
    db: Session = Depends(get_db)
):

    # 🔥 VALIDACIÓN PRO (evita basura en DB)

    form_exists = db.query(Form.id).filter(
        Form.id == payload.id_form
    ).first()

    if not form_exists:
        raise HTTPException(404, "El formulario no existe")


    question_exists = db.query(Question.id).filter(
        Question.id == payload.id_question
    ).first()

    if not question_exists:
        raise HTTPException(404, "La pregunta no existe")


    if payload.id_response:
        response_exists = db.query(Response.id).filter(
            Response.id == payload.id_response
        ).first()

        if not response_exists:
            raise HTTPException(404, "La response no existe")


    # 🔥 CREAR REGLA
    new_rule = RelationQuestionRule(
        id_form=payload.id_form,
        id_question=payload.id_question,
        id_response=payload.id_response,
        date_notification=payload.date_notification,
        time_alert=payload.time_alert,
        enabled=payload.enabled
    )

    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)

    return new_rule


# ═══════════════════════════════════════════════════════════════════════════
# ✅ NUEVO: ENDPOINT BULK PARA REGLAS DE RECORDATORIO POR EMAIL
# ───────────────────────────────────────────────────────────────────────────
# Este endpoint recibe N reglas de una sola vez, provenientes de los campos
# con `email_notification = true` del formato. Cada regla contiene:
#   - id_question       → la pregunta tipo email
#   - notification_email→ el correo digitado (destinatario del recordatorio)
#   - date_notification → fecha programada del recordatorio
#   - time_alert        → días de anticipación (frontend envía "0")
#   - notification_message → mensaje personalizado (opcional)
#
# NO reemplaza ni modifica el endpoint /relation-question-rule existente
# (que sigue funcionando igual para los campos tipo date_notification).
#
# NO bloquea el envío inmediato por correo — ese flujo ocurre antes,
# vía /forms/send-answers-by-email, y sigue funcionando como siempre.
# ═══════════════════════════════════════════════════════════════════════════

class BulkEmailNotificationRuleItem(BaseModel):
    id_question: int
    notification_email: str
    date_notification: datetime
    time_alert: str = "0"
    notification_message: Optional[str] = None
    enabled: bool = True


class BulkEmailNotificationRulesCreate(BaseModel):
    id_form: int
    id_response: Optional[int] = None
    rules: List[BulkEmailNotificationRuleItem] = Field(default_factory=list)


@router.post("/relation-question-rule/bulk-email-notifications")
def create_bulk_email_notification_rules(
    payload: BulkEmailNotificationRulesCreate,
    db: Session = Depends(get_db)
):
    """
    Crea en una sola transacción múltiples reglas de recordatorio por email,
    provenientes de campos con props.email_notification = true.

    Cada regla se guarda en la tabla `relation_question_rule` con
    `notification_email` poblado, lo que indica al scheduler diario
    (`notification_rules_task`) que el destinatario del recordatorio
    es ese correo específico (no el user.email del response).
    """

    # 🔥 Validación del formato
    form_exists = db.query(Form.id).filter(Form.id == payload.id_form).first()
    if not form_exists:
        raise HTTPException(404, "El formulario no existe")

    # 🔥 Validación de la response (si viene)
    if payload.id_response:
        response_exists = db.query(Response.id).filter(
            Response.id == payload.id_response
        ).first()
        if not response_exists:
            raise HTTPException(404, "La response no existe")

    if not payload.rules:
        return {
            "created": 0,
            "skipped": 0,
            "message": "No se recibieron reglas para crear",
            "rule_ids": []
        }

    # 🔥 Validar todas las question_ids en un solo query
    question_ids = [r.id_question for r in payload.rules]
    existing_questions = {
        q.id for q in db.query(Question.id).filter(
            Question.id.in_(question_ids)
        ).all()
    }

    created_rules = []
    skipped = []

    for rule_in in payload.rules:
        if rule_in.id_question not in existing_questions:
            skipped.append({
                "id_question": rule_in.id_question,
                "reason": "Question no existe"
            })
            continue

        # Validación básica del email (el front ya valida, esto es defensa)
        email_clean = (rule_in.notification_email or "").strip()
        if not email_clean or "@" not in email_clean:
            skipped.append({
                "id_question": rule_in.id_question,
                "reason": "Email inválido"
            })
            continue

        new_rule = RelationQuestionRule(
            id_form=payload.id_form,
            id_question=rule_in.id_question,
            id_response=payload.id_response,
            date_notification=rule_in.date_notification,
            time_alert=rule_in.time_alert or "0",
            enabled=rule_in.enabled,
            notification_email=email_clean,
            notification_message=rule_in.notification_message,
        )
        db.add(new_rule)
        created_rules.append(new_rule)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error guardando reglas: {str(e)}"
        )

    # Refrescar para obtener IDs
    rule_ids = []
    for r in created_rules:
        db.refresh(r)
        rule_ids.append(r.id)

    return {
        "created": len(created_rules),
        "skipped": len(skipped),
        "skipped_detail": skipped,
        "rule_ids": rule_ids,
        "message": (
            f"Se crearon {len(created_rules)} regla(s) de recordatorio por email"
            + (f" — se omitieron {len(skipped)}" if skipped else "")
        )
    }


from app.models import ResponseStatus  # agregar a los imports existentes si no está

@router.get("/question-table-relation/serials/{question_id}")
def get_serials_for_field(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autorizado")

    relation = (
        db.query(QuestionTableRelation)
        .filter(QuestionTableRelation.question_id == question_id)
        .first()
    )

    if not relation or not relation.related_form_id:
        return {"serials": [], "question_id": question_id}

    responses = (
        db.query(Response)
        .filter(
            Response.form_id == relation.related_form_id,
            Response.status.in_([
                ResponseStatus.submitted,
                ResponseStatus.approved
            ])
        )
        .order_by(Response.submitted_at.desc())
        .all()
    )

    serials = []
    for resp in responses:
        label = str(resp.id)
        if relation.field_name:
            try:
                label_q_id = int(relation.field_name)
                label_answer = next(
                    (a.answer_text for a in resp.answers
                     if a.question_id == label_q_id and a.answer_text),
                    None
                )
                if label_answer:
                    label = f"#{resp.id} — {label_answer}"
            except (ValueError, TypeError):
                pass

        serials.append({
            "response_id": resp.id,
            "label": label,
            "submitted_at": str(resp.submitted_at)[:19]
        })

    return {
        "serials": serials,
        "question_id": question_id,
        "related_form_id": relation.related_form_id
    }
    
    
@router.get("/serial-autofill/{response_id}")
def get_answers_map_for_serial(
    response_id: int,
    target_form_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(status_code=403, detail="No autorizado")

    answers = (
        db.query(Answer)
        .filter(Answer.response_id == response_id)
        .all()
    )

    if not answers:
        raise HTTPException(status_code=404, detail=f"No hay respuestas para el serial {response_id}")

    def is_useful(a) -> bool:
        fp = getattr(a, 'file_path', None)
        if fp and str(fp).strip():
            return False
        txt = getattr(a, 'answer_text', None)
        if not txt or not str(txt).strip():
            return False
        if str(txt).strip().startswith(("{", "[")):
            return False
        return True

    def get_pk(a) -> int:
        """Obtiene la PK del answer para ordenar por inserción."""
        for attr in ('id', 'id_answer', 'pk'):
            val = getattr(a, attr, None)
            if val is not None:
                return int(val)
        return 0

    useful = [a for a in answers if is_useful(a)]

    # ── Detectar campos de repetidor ─────────────────────────────────────────
    # Un question_id que aparece MÁS DE UNA VEZ en el mismo response
    # necesariamente proviene de filas de un repetidor.
    from collections import Counter
    q_count = Counter(a.question_id for a in useful)
    repeater_qids = {qid for qid, cnt in q_count.items() if cnt > 1}

    flat_answers     = [a for a in useful if a.question_id not in repeater_qids]
    repeater_answers = [a for a in useful if a.question_id in repeater_qids]

    # Mapa plano: question_id → answer_text  (solo campos no-repetidor)
    source_map = {str(a.question_id): a.answer_text for a in flat_answers}

    # ── Reconstruir filas del repetidor sin depender de repeater_row_index ───
    # Para cada question_id repetido, ordenar sus answers por PK (orden de inserción).
    # La i-ésima answer de cada campo corresponde a la fila i del repetidor.
    per_q: dict = defaultdict(list)
    for a in repeater_answers:
        per_q[a.question_id].append(a)

    for qid in per_q:
        per_q[qid].sort(key=get_pk)

    num_rows = max((len(v) for v in per_q.values()), default=0)

    repeater_rows_raw: list = []
    for row_idx in range(num_rows):
        row: dict = {}
        for qid, ans_list in per_q.items():
            if row_idx < len(ans_list):
                row[str(qid)] = ans_list[row_idx].answer_text
        if row:
            repeater_rows_raw.append(row)

    repeater_rows_source = (
        {"__repeater__": repeater_rows_raw} if repeater_rows_raw else {}
    )

    # ── Resolver hacia IDs del formulario destino ─────────────────────────────
    local_map: dict = {}
    repeater_rows_local: list = []

    if target_form_id:
        form_q_ids = [
            fq.question_id for fq in
            db.query(FormQuestion).filter(FormQuestion.form_id == target_form_id).all()
        ]
        form_q_ids_set = set(str(q) for q in form_q_ids)

        relations = db.query(QuestionTableRelation).filter(
            QuestionTableRelation.question_id.in_(form_q_ids)
        ).all()

        # related_question_id (origen) → question_id (destino local)
        rel_map = {
            str(r.related_question_id): str(r.question_id)
            for r in relations if r.related_question_id
        }

        # Mapa plano resuelto (campos flat)
        for rel in relations:
            if rel.related_question_id:
                val = source_map.get(str(rel.related_question_id))
                if val:
                    local_map[str(rel.question_id)] = val

        for src_qid, val in source_map.items():
            if src_qid in form_q_ids_set and src_qid not in local_map:
                local_map[src_qid] = val

        # Filas del repetidor resueltas
        for source_row in repeater_rows_raw:
            local_row: dict = {}
            for src_qid, val in source_row.items():
                local_qid = rel_map.get(src_qid)
                if local_qid:
                    local_row[local_qid] = val
                elif src_qid in form_q_ids_set:
                    local_row[src_qid] = val
            if local_row:
                repeater_rows_local.append(local_row)

    return {
        "response_id": response_id,
        "answers_by_question_id": source_map,
        "answers_by_local_question_id": local_map,
        "repeater_rows_local": repeater_rows_local,
        "repeater_rows_source": {str(k): v for k, v in repeater_rows_source.items()},
    }
    
    
@router.put("/update_question_endpoint/{question_id}")
def update_question_endpoint(
    question_id: int,
    payload: QuestionUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )

    # 1. Verificar que la pregunta existe
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pregunta no encontrada"
        )

    # 2. Solo bloquear el cambio de TIPO si está vinculada a formatos
    #    Nombre y descripción siempre se pueden editar.
    if payload.question_type is not None and payload.question_type != question.question_type:
        linked_count = (
            db.query(FormQuestion)
            .filter(FormQuestion.question_id == question_id)
            .count()
        )
        if linked_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede cambiar el tipo: vinculada a {linked_count} formato(s)"
            )

    # 2b. No permitir texto duplicado SOLO si el texto realmente cambia. Dejarlo
    # igual (incluido un duplicado histórico) se permite sin tocarlo.
    if (
        payload.question_text is not None
        and _normalize_question_text(payload.question_text)
        != _normalize_question_text(question.question_text)
    ):
        dup = _find_duplicate_question(db, payload.question_text, exclude_id=question_id)
        if dup:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ya existe otra pregunta con ese texto (#{dup[0]}). No se permiten preguntas duplicadas."
            )

    # 3. Aplicar los campos del payload
    if payload.question_text is not None:
        question.question_text = payload.question_text.strip().upper()
    if payload.description is not None:
        question.description = payload.description.strip().upper()
    if payload.question_type is not None:
        question.question_type = payload.question_type
    if payload.id_category is not None:
        question.id_category = payload.id_category
    if payload.id_alias is not None:
        question.id_alias = payload.id_alias
    elif payload.id_alias is None and "id_alias" in (payload.model_fields_set or set()):
        question.id_alias = None

    if payload.id_form is not None:
        form_exists = db.query(Form).filter(Form.id == payload.id_form).first()
        if not form_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El formato especificado no existe"
            )
        question.id_form = payload.id_form
    elif "id_form" in (payload.model_fields_set or set()):
        question.id_form = None

    db.commit()
    db.refresh(question)

    return {
        "message": "Pregunta actualizada correctamente",
        "id": question.id,
        "question_text": question.question_text
    }