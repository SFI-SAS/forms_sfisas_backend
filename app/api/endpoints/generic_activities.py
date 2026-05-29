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
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.controllers.mail import send_generic_activity_assignment_email
from app.core.security import get_current_user, require_roles
from app.database import get_db
from app.models import (
    Form,
    GenericActivity,
    GenericActivityForm,
    Profile,
    ProfileUser,
    User,
    UserType,
)
from app.schemas import (
    GenericActivityCreate,
    GenericActivityFormItem,
    GenericActivityFormOut,
    GenericActivityFormsUpdate,
    GenericActivityMineOut,
    GenericActivityOut,
    GenericActivitySummaryOut,
    GenericActivityUpdate,
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
        items=[_serialize_item(link) for link in a.form_links],
    )


def _summary(a: GenericActivity) -> GenericActivitySummaryOut:
    form_ids = {link.form_id for link in a.form_links}
    return GenericActivitySummaryOut(
        id=a.id,
        name=a.name,
        description=a.description,
        is_active=a.is_active,
        form_count=len(form_ids),
        assignment_count=len(a.form_links),
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _load_full(db: Session, activity_id: int) -> GenericActivity:
    activity = (
        db.query(GenericActivity)
        .options(
            joinedload(GenericActivity.form_links).joinedload(GenericActivityForm.form),
            joinedload(GenericActivity.form_links).joinedload(GenericActivityForm.profile),
            joinedload(GenericActivity.form_links).joinedload(GenericActivityForm.user),
        )
        .filter(GenericActivity.id == activity_id)
        .first()
    )
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Actividad no encontrada"
        )
    return activity


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
    q = db.query(GenericActivity).options(joinedload(GenericActivity.form_links))
    if only_active:
        q = q.filter(GenericActivity.is_active.is_(True))
    activities = q.order_by(GenericActivity.created_at.desc()).all()
    return [_summary(a) for a in activities]


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
            )
        )
    return result


@router.get("/{activity_id}", response_model=GenericActivityOut)
def get_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
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
