"""
Endpoints para Actividades Genéricas (Generic Activities).

Una actividad genérica agrupa un conjunto de formatos y, por cada formato,
define quién lo diligencia. El diligenciador NO se elige directamente de la
lista global de usuarios, sino a través de un PERFIL (Profile): se elige un
perfil, se listan sus usuarios y se escoge uno. Un mismo formato puede tener
varios diligenciadores (varias filas formato↔usuario).

Esta capa SOLO guarda/edita/elimina la configuración. La lista de perfiles y
sus usuarios se consulta vía los endpoints existentes de /profiles (solo
lectura) — este módulo NO modifica el módulo de perfiles ni la lógica viva.

Solo administradores (UserType.admin) gestionan estas tablas.
"""

from typing import List, Set, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.api.controllers.mail import send_generic_activity_assignment_email
from app.core.security import get_current_user, require_roles
from app.database import get_db
from app.models import (
    Answer,
    Form,
    FormQuestion,
    FormServiceClassification,
    GenericActivity,
    GenericActivityForm,
    GenericActivityFormLink,
    Profile,
    ProfileUser,
    Question,
    QuestionType,
    Response,
    ResponseServiceLink,
    User,
    UserType,
)
from app.schemas import (
    ClassifiableQuestionOut,
    FormServiceClassificationOut,
    FormServiceClassificationSet,
    GenericActivityCreate,
    GenericActivityFormItem,
    GenericActivityFormLinkOut,
    GenericActivityFormOut,
    GenericActivityFormsUpdate,
    GenericActivityMineOut,
    GenericActivityOut,
    GenericActivitySummaryOut,
    GenericActivityUpdate,
    ResponseServiceLinkCreate,
    ResponseServiceLinkDetailOut,
    ResponseServiceLinkOut,
    ServiceAssignmentsAdd,
    ServiceFormLinksAdd,
    ServiceSelectableOut,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_item(link: GenericActivityForm) -> GenericActivityFormOut:
    return GenericActivityFormOut(
        id=link.id,
        form_id=link.form_id,
        form_title=link.form.title if link.form else f"Formato #{link.form_id}",
        profile_id=link.profile_id,
        profile_name=link.profile.name if link.profile else None,
        user_id=link.user_id,
        user_name=link.user.name if link.user else f"Usuario #{link.user_id}",
        user_email=link.user.email if link.user else None,
    )


def _serialize_activity(a: GenericActivity) -> GenericActivityOut:
    return GenericActivityOut(
        id=a.id,
        name=a.name,
        description=a.description,
        is_active=a.is_active,
        created_by=a.created_by,
        created_at=a.created_at,
        updated_at=a.updated_at,
        forms=[
            GenericActivityFormLinkOut(
                id=l.id,
                form_id=l.form_id,
                form_title=l.form.title if l.form else f"Formato #{l.form_id}",
            )
            for l in a.service_form_links
        ],
        items=[_serialize_item(link) for link in a.form_links],
        classification_form_id=a.classification_form_id,
        classification_form_title=(
            a.classification_form.title if a.classification_form else None
        ),
        classification_question_id=a.classification_question_id,
        classification_question_text=(
            a.classification_question.question_text if a.classification_question else None
        ),
        classification_value=a.classification_value,
    )


def _classification_values_by_activity(db: Session, activity_ids) -> dict:
    """Valor(es) de clasificacion de cada servicio, derivado de las RELACIONES
    respuesta-servicio (la clasificacion unificada). Usa el valor guardado en el
    link o, si falta, el Answer real de la pregunta clasificadora. Devuelve los
    valores distintos unidos por coma."""
    ids = set(activity_ids)
    if not ids:
        return {}
    rows = (
        db.query(
            ResponseServiceLink.activity_id,
            func.coalesce(
                ResponseServiceLink.classification_value, Answer.answer_text
            ).label("val"),
        )
        .outerjoin(
            Answer,
            and_(
                Answer.response_id == ResponseServiceLink.response_id,
                Answer.question_id == ResponseServiceLink.question_id,
            ),
        )
        .filter(ResponseServiceLink.activity_id.in_(ids))
        .all()
    )
    acc: dict = {}
    for aid, val in rows:
        if val:
            acc.setdefault(aid, set()).add(str(val))
    return {aid: ", ".join(sorted(vals)) for aid, vals in acc.items()}


def _summary(a: GenericActivity, classification_value=None) -> GenericActivitySummaryOut:
    # Los formatos del servicio viven en service_form_links (feature "Servicios").
    # Se unen con los form_id de las asignaciones (legacy) para no perder los que
    # solo existian como asignacion usuario-formato.
    form_ids = {l.form_id for l in a.service_form_links} | {l.form_id for l in a.form_links}
    return GenericActivitySummaryOut(
        id=a.id,
        name=a.name,
        description=a.description,
        is_active=a.is_active,
        form_count=len(form_ids),
        assignment_count=len(a.form_links),
        created_at=a.created_at,
        updated_at=a.updated_at,
        # Clasificacion unificada: la de las relaciones; si no hay, la legacy.
        classification_value=classification_value or a.classification_value,
    )


def _load_full(db: Session, activity_id: int) -> GenericActivity:
    activity = (
        db.query(GenericActivity)
        .options(
            joinedload(GenericActivity.form_links).joinedload(GenericActivityForm.form),
            joinedload(GenericActivity.form_links).joinedload(GenericActivityForm.profile),
            joinedload(GenericActivity.form_links).joinedload(GenericActivityForm.user),
            joinedload(GenericActivity.service_form_links).joinedload(GenericActivityFormLink.form),
            joinedload(GenericActivity.classification_form),
            joinedload(GenericActivity.classification_question),
        )
        .filter(GenericActivity.id == activity_id)
        .first()
    )
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Actividad no encontrada"
        )
    return activity


def _apply_classification(
    db: Session,
    activity: GenericActivity,
    form_id,
    question_id,
    value,
) -> None:
    """Fija o limpia la clasificación de la actividad.

    - Para FIJARLA se requieren los tres: formato, pregunta y valor.
    - Para LIMPIARLA, enviar los tres vacíos/None.
    Valida que el formato y la pregunta existan y que la pregunta pertenezca al
    formato indicado.
    """
    clean_value = (value or "").strip()
    if not form_id and not question_id and not clean_value:
        activity.classification_form_id = None
        activity.classification_question_id = None
        activity.classification_value = None
        return

    if not (form_id and question_id and clean_value):
        raise HTTPException(
            400,
            "La clasificación requiere formato, pregunta y valor (o los tres vacíos para quitarla)",
        )

    if not db.query(Form.id).filter(Form.id == form_id).first():
        raise HTTPException(404, "Formato de clasificación no encontrado")

    # La pregunta debe existir y estar vinculada al formato (form_questions).
    belongs = (
        db.query(FormQuestion.id)
        .filter(
            FormQuestion.form_id == form_id,
            FormQuestion.question_id == question_id,
        )
        .first()
    )
    if not belongs:
        raise HTTPException(
            404, "La pregunta de clasificación no pertenece al formato indicado"
        )

    activity.classification_form_id = form_id
    activity.classification_question_id = question_id
    activity.classification_value = clean_value


def _validate_items(
    db: Session, items: List[GenericActivityFormItem]
) -> List[GenericActivityFormItem]:
    """Valida formatos, usuarios y perfiles; deduplica por (form_id, user_id).

    Si se especifica profile_id, valida que el usuario sea miembro de ese perfil
    (coherente con el flujo: el usuario se eligió DESDE los miembros del perfil).
    """
    # Dedup por (formato, usuario) preservando el primer profile_id visto.
    seen: dict = {}
    for it in items:
        key = (it.form_id, it.user_id)
        if key not in seen:
            seen[key] = it
    deduped = list(seen.values())

    form_ids = {it.form_id for it in deduped}
    user_ids = {it.user_id for it in deduped}
    profile_ids = {it.profile_id for it in deduped if it.profile_id}

    if form_ids:
        found = {f.id for f in db.query(Form.id).filter(Form.id.in_(form_ids)).all()}
        missing = form_ids - found
        if missing:
            raise HTTPException(404, f"Formatos no encontrados: {sorted(missing)}")

    if user_ids:
        found = {u.id for u in db.query(User.id).filter(User.id.in_(user_ids)).all()}
        missing = user_ids - found
        if missing:
            raise HTTPException(404, f"Usuarios no encontrados: {sorted(missing)}")

    if profile_ids:
        found = {
            p.id for p in db.query(Profile.id).filter(Profile.id.in_(profile_ids)).all()
        }
        missing = profile_ids - found
        if missing:
            raise HTTPException(404, f"Perfiles no encontrados: {sorted(missing)}")

        memberships = {
            (m.profile_id, m.user_id)
            for m in db.query(ProfileUser.profile_id, ProfileUser.user_id)
            .filter(ProfileUser.profile_id.in_(profile_ids))
            .all()
        }
        for it in deduped:
            if it.profile_id and (it.profile_id, it.user_id) not in memberships:
                raise HTTPException(
                    400,
                    f"El usuario {it.user_id} no pertenece al perfil {it.profile_id}",
                )

    return deduped


def _schedule_notifications(
    background_tasks: BackgroundTasks,
    activity: GenericActivity,
    new_pairs: Set[Tuple[int, int]],
) -> None:
    """Agenda (en background, sin bloquear la respuesta) un email por cada
    diligenciador recién asignado, listando sus formatos en esta actividad.
    `new_pairs` es el conjunto de (form_id, user_id) a notificar."""
    by_user: dict = {}
    for link in activity.form_links:
        if (link.form_id, link.user_id) not in new_pairs:
            continue
        if not link.user or not link.user.email:
            continue
        entry = by_user.setdefault(
            link.user_id,
            {"email": link.user.email, "name": link.user.name, "titles": []},
        )
        entry["titles"].append(
            link.form.title if link.form else f"Formato #{link.form_id}"
        )

    for u in by_user.values():
        background_tasks.add_task(
            send_generic_activity_assignment_email,
            u["email"],
            u["name"],
            activity.name,
            u["titles"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints (admin-only)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[GenericActivitySummaryOut])
def list_activities(
    only_active: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Lista todas las actividades genéricas con conteos."""
    q = db.query(GenericActivity).options(
        joinedload(GenericActivity.form_links),
        joinedload(GenericActivity.service_form_links),
    )
    if only_active:
        q = q.filter(GenericActivity.is_active.is_(True))
    activities = q.order_by(GenericActivity.created_at.desc()).all()
    cls_map = _classification_values_by_activity(db, {a.id for a in activities})
    return [_summary(a, cls_map.get(a.id)) for a in activities]


@router.get("/me", response_model=List[GenericActivityMineOut])
def list_my_activities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actividades activas donde el usuario actual es diligenciador asignado,
    con el conteo de formatos que LE corresponden (para la pantalla Diligenciar).
    Se omiten las actividades sin formatos asignados al usuario.
    """
    activity_ids = (
        select(GenericActivityForm.activity_id)
        .where(GenericActivityForm.user_id == current_user.id)
        .distinct()
    )
    activities = (
        db.query(GenericActivity)
        .options(joinedload(GenericActivity.form_links))
        .filter(
            GenericActivity.id.in_(activity_ids),
            GenericActivity.is_active.is_(True),
        )
        .order_by(GenericActivity.name.asc())
        .all()
    )

    cls_map = _classification_values_by_activity(db, {a.id for a in activities})
    result: List[GenericActivityMineOut] = []
    for a in activities:
        my_form_ids = {
            link.form_id for link in a.form_links if link.user_id == current_user.id
        }
        if not my_form_ids:
            continue
        result.append(
            GenericActivityMineOut(
                id=a.id,
                name=a.name,
                description=a.description,
                form_count=len(my_form_ids),
                # Clasificacion unificada (de las relaciones); si no hay, la legacy.
                classification_value=cls_map.get(a.id) or a.classification_value,
            )
        )
    return result


@router.get("/classification-values")
def classification_values(
    form_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Valores DISTINCT ya respondidos para una pregunta de un formato. El admin
    elige uno como clasificación de la actividad."""
    rows = (
        db.query(Answer.answer_text)
        .join(Response, Answer.response_id == Response.id)
        .filter(
            Response.form_id == form_id,
            Answer.question_id == question_id,
            Answer.answer_text.isnot(None),
            Answer.answer_text != "",
        )
        .distinct()
        .order_by(Answer.answer_text.asc())
        .all()
    )
    return {"values": [r[0] for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# Feature "Servicios" — pregunta clasificadora + relación respuesta↔servicio.
# ─────────────────────────────────────────────────────────────────────────────

# Tipos de pregunta que pueden clasificar servicios: texto y selección.
_CLASSIFIABLE_TYPES = {
    QuestionType.text,
    QuestionType.multiple_choice,
    QuestionType.one_choice,
}


def _qtype_str(qt) -> str:
    return qt.value if hasattr(qt, "value") else str(qt)


@router.get("/selectable", response_model=List[ServiceSelectableOut])
def list_selectable_services(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Servicios activos (id+nombre) para el modal de relación al diligenciar.
    Accesible a cualquier usuario autenticado. Debe ir ANTES de /{activity_id}
    para no colisionar con el parámetro de ruta."""
    rows = (
        db.query(GenericActivity.id, GenericActivity.name)
        .filter(GenericActivity.is_active.is_(True))
        .order_by(GenericActivity.name)
        .all()
    )
    return [ServiceSelectableOut(id=r.id, name=r.name) for r in rows]


@router.get("/{activity_id}", response_model=GenericActivityOut)
def get_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    # Cualquier usuario autenticado: quien diligencia un formato puede gestionar
    # formatos/diligenciadores del servicio desde el modal (no solo admin).
    current_user: User = Depends(get_current_user),
):
    return _serialize_activity(_load_full(db, activity_id))


@router.post("/", response_model=GenericActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(
    payload: GenericActivityCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    name = payload.name.strip()
    if db.query(GenericActivity.id).filter(GenericActivity.name == name).first():
        raise HTTPException(400, "Ya existe una actividad con ese nombre")

    items = _validate_items(db, payload.items)

    activity = GenericActivity(
        name=name,
        description=payload.description,
        created_by=current_user.id,
        is_active=True,
    )
    _apply_classification(
        db,
        activity,
        payload.classification_form_id,
        payload.classification_question_id,
        payload.classification_value,
    )
    db.add(activity)
    db.flush()

    for it in items:
        db.add(
            GenericActivityForm(
                activity_id=activity.id,
                form_id=it.form_id,
                profile_id=it.profile_id,
                user_id=it.user_id,
            )
        )

    # Feature "Servicios": formatos del servicio = form_ids explícitos ∪ los
    # form_id de las asignaciones. Los usuarios siguen siendo opcionales.
    link_form_ids = set(payload.form_ids) | {it.form_id for it in items}
    if link_form_ids:
        existing_forms = {
            row.id for row in db.query(Form.id).filter(Form.id.in_(link_form_ids)).all()
        }
        missing = link_form_ids - existing_forms
        if missing:
            raise HTTPException(400, f"Formatos inexistentes: {sorted(missing)}")
        for fid in link_form_ids:
            db.add(GenericActivityFormLink(activity_id=activity.id, form_id=fid))

    db.commit()
    activity = _load_full(db, activity.id)
    # Notificar a todos los diligenciadores (todas las asignaciones son nuevas).
    _schedule_notifications(
        background_tasks,
        activity,
        {(link.form_id, link.user_id) for link in activity.form_links},
    )
    return _serialize_activity(activity)


@router.put("/{activity_id}", response_model=GenericActivityOut)
def update_activity(
    activity_id: int,
    payload: GenericActivityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    activity = db.query(GenericActivity).filter(GenericActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(404, "Actividad no encontrada")

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(400, "El nombre no puede estar vacio")
        if (
            db.query(GenericActivity.id)
            .filter(GenericActivity.name == new_name, GenericActivity.id != activity.id)
            .first()
        ):
            raise HTTPException(400, "Ya existe otra actividad con ese nombre")
        activity.name = new_name

    if payload.description is not None:
        activity.description = payload.description

    if payload.is_active is not None:
        activity.is_active = payload.is_active

    # Solo tocar la clasificación si el payload incluyó alguno de sus campos.
    cls_fields = {
        "classification_form_id",
        "classification_question_id",
        "classification_value",
    }
    if cls_fields & payload.model_fields_set:
        _apply_classification(
            db,
            activity,
            payload.classification_form_id,
            payload.classification_question_id,
            payload.classification_value,
        )

    db.commit()
    return _serialize_activity(_load_full(db, activity.id))


@router.delete("/{activity_id}")
def delete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    activity = db.query(GenericActivity).filter(GenericActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(404, "Actividad no encontrada")
    db.delete(activity)
    db.commit()
    return {"deleted": True, "id": activity_id}


@router.put("/{activity_id}/forms", response_model=GenericActivityOut)
def set_activity_forms(
    activity_id: int,
    payload: GenericActivityFormsUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Reemplaza por completo el conjunto de asignaciones (formato↔usuario) de
    la actividad. Notifica solo a los diligenciadores recién agregados."""
    activity = db.query(GenericActivity).filter(GenericActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(404, "Actividad no encontrada")

    items = _validate_items(db, payload.items)

    # Asignaciones previas, para notificar solo las NUEVAS (no re-notificar).
    old_pairs: Set[Tuple[int, int]] = {
        (fid, uid)
        for fid, uid in db.query(
            GenericActivityForm.form_id, GenericActivityForm.user_id
        ).filter(GenericActivityForm.activity_id == activity.id).all()
    }

    db.query(GenericActivityForm).filter(
        GenericActivityForm.activity_id == activity.id
    ).delete(synchronize_session=False)

    for it in items:
        db.add(
            GenericActivityForm(
                activity_id=activity.id,
                form_id=it.form_id,
                profile_id=it.profile_id,
                user_id=it.user_id,
            )
        )

    db.commit()
    activity = _load_full(db, activity.id)
    new_pairs = {
        (link.form_id, link.user_id) for link in activity.form_links
    } - old_pairs
    _schedule_notifications(background_tasks, activity, new_pairs)
    return _serialize_activity(activity)


# ─────────────────────────────────────────────────────────────────────────────
# Pregunta clasificadora por formato (la marca el creador del formato).
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/forms/{form_id}/classifiable-questions",
    response_model=List[ClassifiableQuestionOut],
)
def list_classifiable_questions(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Preguntas tipo texto/select del formato (candidatas a clasificar servicios)."""
    rows = (
        db.query(Question)
        .join(FormQuestion, FormQuestion.question_id == Question.id)
        .filter(
            FormQuestion.form_id == form_id,
            Question.question_type.in_(_CLASSIFIABLE_TYPES),
        )
        .all()
    )
    return [
        ClassifiableQuestionOut(
            question_id=q.id,
            question_text=q.question_text,
            question_type=_qtype_str(q.question_type),
        )
        for q in rows
    ]


@router.get(
    "/forms/{form_id}/classification",
    response_model=FormServiceClassificationOut,
)
def get_form_classification(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pregunta clasificadora actual del formato (o vacío). Accesible a cualquier
    autenticado: el diligenciador necesita saber si el formato la tiene."""
    rec = (
        db.query(FormServiceClassification)
        .filter(FormServiceClassification.form_id == form_id)
        .first()
    )
    if not rec:
        return FormServiceClassificationOut(form_id=form_id)
    q = db.query(Question).filter(Question.id == rec.question_id).first()
    return FormServiceClassificationOut(
        form_id=form_id,
        question_id=rec.question_id,
        question_text=q.question_text if q else None,
    )


@router.put(
    "/forms/{form_id}/classification",
    response_model=FormServiceClassificationOut,
)
def set_form_classification(
    form_id: int,
    payload: FormServiceClassificationSet,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Marca (o limpia con question_id=null) la pregunta clasificadora del formato."""
    if not db.query(Form.id).filter(Form.id == form_id).first():
        raise HTTPException(404, "Formato no encontrado")

    rec = (
        db.query(FormServiceClassification)
        .filter(FormServiceClassification.form_id == form_id)
        .first()
    )

    # question_id=null → limpiar la clasificación del formato.
    if payload.question_id is None:
        if rec:
            db.delete(rec)
            db.commit()
        return FormServiceClassificationOut(form_id=form_id)

    q = (
        db.query(Question)
        .join(FormQuestion, FormQuestion.question_id == Question.id)
        .filter(FormQuestion.form_id == form_id, Question.id == payload.question_id)
        .first()
    )
    if not q:
        raise HTTPException(400, "La pregunta no pertenece al formato")
    if q.question_type not in _CLASSIFIABLE_TYPES:
        raise HTTPException(400, "La pregunta debe ser de tipo texto o select")

    if rec:
        rec.question_id = q.id
    else:
        db.add(FormServiceClassification(form_id=form_id, question_id=q.id))
    db.commit()
    return FormServiceClassificationOut(
        form_id=form_id,
        question_id=q.id,
        question_text=q.question_text,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Relación respuesta↔servicio (la "clasificación" al diligenciar).
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/responses/{response_id}/service-link",
    response_model=ResponseServiceLinkOut,
)
def link_response_to_service(
    response_id: int,
    payload: ResponseServiceLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Relaciona una respuesta con un servicio (la 'clasificación' al diligenciar).
    Permitido al dueño de la respuesta o a admin. Idempotente por (respuesta,
    servicio): si ya existe, actualiza el valor."""
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        raise HTTPException(404, "Respuesta no encontrada")
    if response.user_id != current_user.id and current_user.user_type != UserType.admin:
        raise HTTPException(403, "No puedes relacionar esta respuesta")

    activity = (
        db.query(GenericActivity)
        .filter(GenericActivity.id == payload.activity_id)
        .first()
    )
    if not activity:
        raise HTTPException(404, "Servicio no encontrado")

    link = (
        db.query(ResponseServiceLink)
        .filter(
            ResponseServiceLink.response_id == response_id,
            ResponseServiceLink.activity_id == payload.activity_id,
        )
        .first()
    )
    if link:
        link.question_id = payload.question_id
        link.classification_value = payload.classification_value
    else:
        link = ResponseServiceLink(
            response_id=response_id,
            activity_id=payload.activity_id,
            question_id=payload.question_id,
            classification_value=payload.classification_value,
        )
        db.add(link)
    db.commit()
    db.refresh(link)
    return ResponseServiceLinkOut(
        id=link.id,
        response_id=link.response_id,
        activity_id=link.activity_id,
        activity_name=activity.name,
        question_id=link.question_id,
        classification_value=link.classification_value,
    )


@router.get(
    "/{activity_id}/response-links",
    response_model=List[ResponseServiceLinkDetailOut],
)
def list_response_links(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Respuestas relacionadas con el servicio al diligenciar (clasificación a
    nivel de respuesta). Es lo que se ve en el apartado de Servicios."""
    rows = (
        db.query(ResponseServiceLink)
        .options(
            joinedload(ResponseServiceLink.response).joinedload(Response.form),
            joinedload(ResponseServiceLink.response).joinedload(Response.user),
        )
        .filter(ResponseServiceLink.activity_id == activity_id)
        .order_by(ResponseServiceLink.created_at.desc())
        .all()
    )
    result: List[ResponseServiceLinkDetailOut] = []
    for r in rows:
        resp = r.response
        # Si el valor no quedó guardado en el link, recuperarlo del Answer real
        # (la respuesta a la pregunta clasificadora de ese response).
        value = r.classification_value
        if not value and r.question_id is not None:
            ans = (
                db.query(Answer.answer_text)
                .filter(
                    Answer.response_id == r.response_id,
                    Answer.question_id == r.question_id,
                )
                .first()
            )
            if ans and ans[0]:
                value = ans[0]
        result.append(
            ResponseServiceLinkDetailOut(
                response_id=r.response_id,
                form_id=resp.form_id if resp else 0,
                form_title=(
                    resp.form.title if resp and resp.form else f"Formato #{r.response_id}"
                ),
                user_name=resp.user.name if resp and resp.user else "—",
                classification_value=value,
                submitted_at=resp.submitted_at if resp else None,
            )
        )
    return result


@router.delete("/{activity_id}/response-links/{response_id}")
def delete_response_link(
    activity_id: int,
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin, UserType.creator])),
):
    """Elimina la relación respuesta↔servicio (la clasificación de esa respuesta)."""
    link = (
        db.query(ResponseServiceLink)
        .filter(
            ResponseServiceLink.activity_id == activity_id,
            ResponseServiceLink.response_id == response_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(404, "Clasificación no encontrada")
    db.delete(link)
    db.commit()
    return {"deleted": True, "response_id": response_id, "activity_id": activity_id}


# ─────────────────────────────────────────────────────────────────────────────
# F5 extendido: gestionar formatos/diligenciadores de un servicio desde el modal
# al diligenciar. Additivo (no reemplaza nada). Cualquier usuario autenticado.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{activity_id}/form-links", response_model=GenericActivityOut)
def add_service_form_links(
    activity_id: int,
    payload: ServiceFormLinksAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agrega formatos al servicio (additivo, no quita los existentes)."""
    activity = db.query(GenericActivity).filter(GenericActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(404, "Servicio no encontrado")

    form_ids = set(payload.form_ids)
    if form_ids:
        existing_forms = {
            row[0] for row in db.query(Form.id).filter(Form.id.in_(form_ids)).all()
        }
        missing = form_ids - existing_forms
        if missing:
            raise HTTPException(400, f"Formatos inexistentes: {sorted(missing)}")
        already = {
            row[0]
            for row in db.query(GenericActivityFormLink.form_id)
            .filter(GenericActivityFormLink.activity_id == activity_id)
            .all()
        }
        for fid in form_ids - already:
            db.add(GenericActivityFormLink(activity_id=activity_id, form_id=fid))
        db.commit()

    return _serialize_activity(_load_full(db, activity_id))


@router.post("/{activity_id}/assignments", response_model=GenericActivityOut)
def add_service_assignments(
    activity_id: int,
    payload: ServiceAssignmentsAdd,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Asigna diligenciadores a un formato del servicio (additivo). Notifica a los
    nuevos y asegura que el formato esté en los formatos del servicio."""
    activity = db.query(GenericActivity).filter(GenericActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(404, "Servicio no encontrado")

    # Valida formatos/usuarios/perfiles y deduplica (reusa _validate_items).
    items = _validate_items(
        db,
        [
            GenericActivityFormItem(
                form_id=payload.form_id, user_id=uid, profile_id=payload.profile_id
            )
            for uid in payload.user_ids
        ],
    )

    existing_pairs = {
        (fid, uid)
        for fid, uid in db.query(
            GenericActivityForm.form_id, GenericActivityForm.user_id
        )
        .filter(GenericActivityForm.activity_id == activity_id)
        .all()
    }
    new_pairs: Set[Tuple[int, int]] = set()
    for it in items:
        if (it.form_id, it.user_id) in existing_pairs:
            continue
        db.add(
            GenericActivityForm(
                activity_id=activity_id,
                form_id=it.form_id,
                profile_id=it.profile_id,
                user_id=it.user_id,
            )
        )
        new_pairs.add((it.form_id, it.user_id))

    # Asegurar que el formato esté en los formatos del servicio (form_links).
    link_exists = (
        db.query(GenericActivityFormLink.id)
        .filter(
            GenericActivityFormLink.activity_id == activity_id,
            GenericActivityFormLink.form_id == payload.form_id,
        )
        .first()
    )
    if not link_exists:
        db.add(GenericActivityFormLink(activity_id=activity_id, form_id=payload.form_id))

    db.commit()
    activity = _load_full(db, activity_id)
    _schedule_notifications(background_tasks, activity, new_pairs)
    return _serialize_activity(activity)
