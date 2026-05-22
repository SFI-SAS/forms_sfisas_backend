"""
Endpoints para gestion de Perfiles (Profiles).

Un Profile agrupa:
  - un conjunto de usuarios
  - un conjunto de formatos (asignados directamente)
  - un conjunto de categorias (todos los formatos directos de cada categoria
    quedan disponibles para los miembros del perfil; no es recursivo: las
    subcategorias NO se incluyen)

Cuando un usuario es miembro de un perfil, puede diligenciar los formatos
"efectivos" del perfil = (formatos directos) UNION (formatos cuyas
form_categories esten asignadas al perfil).

La integracion con la query "formatos del usuario" vive en
`app/crud.py::get_forms_by_user[_summary]`.

Solo administradores (UserType.admin) gestionan estas tablas.
"""

from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.database import get_db
from app.models import (
    Form,
    FormCategory,
    Profile,
    ProfileCategory,
    ProfileForm,
    ProfileUser,
    User,
    UserType,
)
from app.schemas import (
    ProfileCategoriesUpdate,
    ProfileCategoryOut,
    ProfileCreate,
    ProfileFormOut,
    ProfileFormsUpdate,
    ProfileMemberOut,
    ProfileMembersUpdate,
    ProfileOut,
    ProfileSummaryOut,
    ProfileUpdate,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_member(u: User) -> ProfileMemberOut:
    return ProfileMemberOut(
        id=u.id,
        name=u.name,
        email=u.email,
        num_document=u.num_document,
        user_type=u.user_type.value if u.user_type else None,
    )


def _serialize_form(f: Form) -> ProfileFormOut:
    return ProfileFormOut(id=f.id, title=f.title, description=f.description)


def _serialize_category(c: FormCategory) -> ProfileCategoryOut:
    return ProfileCategoryOut(id=c.id, name=c.name, description=c.description)


def _serialize_profile(
    p: Profile,
    members: List[User],
    forms: List[Form],
    categories: List[FormCategory],
) -> ProfileOut:
    return ProfileOut(
        id=p.id,
        name=p.name,
        description=p.description,
        is_active=p.is_active,
        created_by=p.created_by,
        created_at=p.created_at,
        updated_at=p.updated_at,
        users=[_serialize_member(u) for u in members],
        forms=[_serialize_form(f) for f in forms],
        categories=[_serialize_category(c) for c in categories],
    )


def _load_profile_full(db: Session, profile_id: int) -> Profile:
    profile = (
        db.query(Profile)
        .options(
            joinedload(Profile.user_links).joinedload(ProfileUser.user),
            joinedload(Profile.form_links).joinedload(ProfileForm.form),
            joinedload(Profile.category_links).joinedload(ProfileCategory.category),
        )
        .filter(Profile.id == profile_id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Perfil no encontrado"
        )
    return profile


def _members_forms_categories(
    profile: Profile,
) -> Tuple[List[User], List[Form], List[FormCategory]]:
    members = [link.user for link in profile.user_links if link.user]
    forms = [link.form for link in profile.form_links if link.form]
    categories = [link.category for link in profile.category_links if link.category]
    return members, forms, categories


def _effective_form_count(db: Session, profile: Profile) -> int:
    """Cuenta de formatos distintos accesibles via este perfil:
    formatos directos UNION formatos cuyas categorias estan en el perfil.
    """
    direct_ids = {link.form_id for link in profile.form_links}
    category_ids = [link.category_id for link in profile.category_links]
    if category_ids:
        rows = (
            db.query(Form.id)
            .filter(Form.id_category.in_(category_ids))
            .all()
        )
        for (fid,) in rows:
            direct_ids.add(fid)
    return len(direct_ids)


def _summary(db: Session, p: Profile) -> ProfileSummaryOut:
    return ProfileSummaryOut(
        id=p.id,
        name=p.name,
        description=p.description,
        is_active=p.is_active,
        user_count=len(p.user_links),
        form_count=_effective_form_count(db, p),
        direct_form_count=len(p.form_links),
        category_count=len(p.category_links),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints para el USUARIO actual (cualquier rol autenticado)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=List[ProfileSummaryOut])
def list_my_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve los perfiles activos en los que el usuario actual es miembro,
    con conteos para el frontend (chips de Diligenciar formato).
    """
    profiles = (
        db.query(Profile)
        .join(ProfileUser, ProfileUser.profile_id == Profile.id)
        .options(
            joinedload(Profile.form_links),
            joinedload(Profile.user_links),
            joinedload(Profile.category_links),
        )
        .filter(
            ProfileUser.user_id == current_user.id,
            Profile.is_active.is_(True),
        )
        .order_by(Profile.name.asc())
        .all()
    )

    return [_summary(db, p) for p in profiles]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints (admin-only)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ProfileSummaryOut])
def list_profiles(
    only_active: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Lista todos los perfiles con conteos."""
    q = db.query(Profile).options(
        joinedload(Profile.user_links),
        joinedload(Profile.form_links),
        joinedload(Profile.category_links),
    )
    if only_active:
        q = q.filter(Profile.is_active.is_(True))
    profiles = q.order_by(Profile.created_at.desc()).all()
    return [_summary(db, p) for p in profiles]


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    profile = _load_profile_full(db, profile_id)
    members, forms, categories = _members_forms_categories(profile)
    return _serialize_profile(profile, members, forms, categories)


@router.post("/", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    name = payload.name.strip()
    if db.query(Profile.id).filter(Profile.name == name).first():
        raise HTTPException(400, "Ya existe un perfil con ese nombre")

    user_ids = list({uid for uid in payload.user_ids if uid})
    form_ids = list({fid for fid in payload.form_ids if fid})
    category_ids = list({cid for cid in payload.category_ids if cid})

    if user_ids:
        found = {u.id for u in db.query(User.id).filter(User.id.in_(user_ids)).all()}
        missing = set(user_ids) - found
        if missing:
            raise HTTPException(404, f"Usuarios no encontrados: {sorted(missing)}")

    if form_ids:
        found = {f.id for f in db.query(Form.id).filter(Form.id.in_(form_ids)).all()}
        missing = set(form_ids) - found
        if missing:
            raise HTTPException(404, f"Formatos no encontrados: {sorted(missing)}")

    if category_ids:
        found = {
            c.id
            for c in db.query(FormCategory.id)
            .filter(FormCategory.id.in_(category_ids))
            .all()
        }
        missing = set(category_ids) - found
        if missing:
            raise HTTPException(404, f"Categorias no encontradas: {sorted(missing)}")

    profile = Profile(
        name=name,
        description=payload.description,
        created_by=current_user.id,
        is_active=True,
    )
    db.add(profile)
    db.flush()

    for uid in user_ids:
        db.add(ProfileUser(profile_id=profile.id, user_id=uid))
    for fid in form_ids:
        db.add(ProfileForm(profile_id=profile.id, form_id=fid))
    for cid in category_ids:
        db.add(ProfileCategory(profile_id=profile.id, category_id=cid))

    db.commit()
    profile = _load_profile_full(db, profile.id)
    members, forms, categories = _members_forms_categories(profile)
    return _serialize_profile(profile, members, forms, categories)


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: int,
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Perfil no encontrado")

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(400, "El nombre no puede estar vacio")
        if (
            db.query(Profile.id)
            .filter(Profile.name == new_name, Profile.id != profile.id)
            .first()
        ):
            raise HTTPException(400, "Ya existe otro perfil con ese nombre")
        profile.name = new_name

    if payload.description is not None:
        profile.description = payload.description

    if payload.is_active is not None:
        profile.is_active = payload.is_active

    db.commit()
    profile = _load_profile_full(db, profile.id)
    members, forms, categories = _members_forms_categories(profile)
    return _serialize_profile(profile, members, forms, categories)


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Perfil no encontrado")
    db.delete(profile)
    db.commit()
    return {"deleted": True, "id": profile_id}


@router.put("/{profile_id}/users", response_model=ProfileOut)
def set_profile_users(
    profile_id: int,
    payload: ProfileMembersUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Reemplaza por completo el conjunto de usuarios asignados al perfil."""
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Perfil no encontrado")

    user_ids = list({uid for uid in payload.user_ids if uid})
    if user_ids:
        found = {u.id for u in db.query(User.id).filter(User.id.in_(user_ids)).all()}
        missing = set(user_ids) - found
        if missing:
            raise HTTPException(404, f"Usuarios no encontrados: {sorted(missing)}")

    db.query(ProfileUser).filter(ProfileUser.profile_id == profile.id).delete(
        synchronize_session=False
    )
    for uid in user_ids:
        db.add(ProfileUser(profile_id=profile.id, user_id=uid))

    db.commit()
    profile = _load_profile_full(db, profile.id)
    members, forms, categories = _members_forms_categories(profile)
    return _serialize_profile(profile, members, forms, categories)


@router.put("/{profile_id}/forms", response_model=ProfileOut)
def set_profile_forms(
    profile_id: int,
    payload: ProfileFormsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Reemplaza por completo el conjunto de formatos directos del perfil."""
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Perfil no encontrado")

    form_ids = list({fid for fid in payload.form_ids if fid})
    if form_ids:
        found = {f.id for f in db.query(Form.id).filter(Form.id.in_(form_ids)).all()}
        missing = set(form_ids) - found
        if missing:
            raise HTTPException(404, f"Formatos no encontrados: {sorted(missing)}")

    db.query(ProfileForm).filter(ProfileForm.profile_id == profile.id).delete(
        synchronize_session=False
    )
    for fid in form_ids:
        db.add(ProfileForm(profile_id=profile.id, form_id=fid))

    db.commit()
    profile = _load_profile_full(db, profile.id)
    members, forms, categories = _members_forms_categories(profile)
    return _serialize_profile(profile, members, forms, categories)


@router.put("/{profile_id}/categories", response_model=ProfileOut)
def set_profile_categories(
    profile_id: int,
    payload: ProfileCategoriesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserType.admin])),
):
    """Reemplaza por completo el conjunto de categorias del perfil.

    Los miembros del perfil tendran acceso a todos los formatos cuya
    categoria directa este en este conjunto (no recursivo).
    """
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Perfil no encontrado")

    category_ids = list({cid for cid in payload.category_ids if cid})
    if category_ids:
        found = {
            c.id
            for c in db.query(FormCategory.id)
            .filter(FormCategory.id.in_(category_ids))
            .all()
        }
        missing = set(category_ids) - found
        if missing:
            raise HTTPException(404, f"Categorias no encontradas: {sorted(missing)}")

    db.query(ProfileCategory).filter(ProfileCategory.profile_id == profile.id).delete(
        synchronize_session=False
    )
    for cid in category_ids:
        db.add(ProfileCategory(profile_id=profile.id, category_id=cid))

    db.commit()
    profile = _load_profile_full(db, profile.id)
    members, forms, categories = _members_forms_categories(profile)
    return _serialize_profile(profile, members, forms, categories)
