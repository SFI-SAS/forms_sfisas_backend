"""
Versiones de un formato publicado.

Editar un formato publicado nunca toca la versión vigente: lo que se guarda va
a un BORRADOR de versión (POST /forms/create-version) que el autor envía al
administrador. Al aprobarlo (POST /forms/publish):

  1. `archivar_version` congela la versión vigente en `form_versions` (+ sus
     campos en `form_version_questions`) y queda OBSOLETA.
  2. `aplicar_borrador` pasa todo lo del borrador al formato vigente, que
     conserva su id: relaciones, movimientos, perfiles y respuestas siguen
     apuntándolo sin que nada se rompa.
  3. El borrador se borra.

Una versión obsoleta solo se consulta. Sus respuestas son las del formato que
se enviaron mientras estuvo vigente (valid_from ≤ submitted_at < valid_until).

Rutas (prefijo /forms):
  GET /versions/obsolete                          — Consultar → Obsoletos
  GET /versions/of/{form_id}                      — línea de tiempo de un formato
  GET /versions/{version_id}                      — cómo era (diseño, campos, participantes)
  GET /versions/{version_id}/responses            — respuestas de esa versión
  GET /versions/{version_id}/responses/{resp_id}  — una respuesta, con el diseño de esa versión
  GET /versions/impact/{draft_id}                 — campos que el borrador quita y otros formatos usan
  GET /versions/ranges/{form_id}                  — de cuándo a cuándo fue vigente cada versión (marcar respuestas)
  GET /versions/{version_id}/design               — diseño de esa versión, para pintar una respuesta vieja
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, inspect as sa_inspect
from sqlalchemy.orm import Session, joinedload

from app.core import response_scope
from app.core.security import get_current_user
from app.database import get_db
from app.models import (
    Answer, Form, FormApproval, FormApprovalFieldAccess, FormCloseConfig,
    FormExternalSignoff, FormModerators, FormQuestion, FormVersion,
    FormVersionQuestion, Question, QuestionFilterCondition, QuestionTableRelation,
    RelationOperationMath, Response, ResponseApproval, ResponseStatus, User,
    UserType,
)


# ─────────────────────────────────────────────────────────────────────────────
# Copiar configuración entre un formato y su borrador
# ─────────────────────────────────────────────────────────────────────────────

# Lo que se edita DESDE EL DISEÑADOR (sobre el borrador) y vive en tablas
# aparte del formato. El borrador nace con una copia de cada una
# (create-version) y al aprobarse reemplaza a la del vigente, así lo que se
# quitó en el borrador también se va.
#
# Moderadores, cierre y palabras clave NO van: se editan en Editar formato
# directo sobre el vigente, y reemplazarlos al aprobar borraría lo que se haya
# cambiado ahí mientras el borrador esperaba.
_TABLAS_CONFIG = [
    (FormApproval, 'form_id'),
    (FormApprovalFieldAccess, 'form_id'),
    (FormExternalSignoff, 'form_id'),
    (QuestionFilterCondition, 'form_id'),
    (RelationOperationMath, 'id_form'),
]

_NO_COPIAR = {'id', 'created_at', 'updated_at'}


def _clonar_filas(db: Session, modelo, col_form: str, origen_id: int, destino_id: int):
    columnas = [c.key for c in sa_inspect(modelo).mapper.column_attrs]
    for fila in db.query(modelo).filter(getattr(modelo, col_form) == origen_id).all():
        datos = {c: getattr(fila, c) for c in columnas if c not in _NO_COPIAR}
        datos[col_form] = destino_id
        db.add(modelo(**datos))


def copiar_configuracion(db: Session, origen_id: int, destino_id: int, reemplazar: bool = False):
    """Copia participantes, campos por aprobador, registro externo,
    condiciones y fórmulas de un formato a otro.

    reemplazar=True borra antes lo que tenga el destino (al aprobar)."""
    for modelo, col in _TABLAS_CONFIG:
        if reemplazar:
            db.query(modelo).filter(getattr(modelo, col) == destino_id).delete(synchronize_session=False)
        _clonar_filas(db, modelo, col, origen_id, destino_id)
    db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Archivar la versión vigente (queda obsoleta)
# ─────────────────────────────────────────────────────────────────────────────

def _participantes(db: Session, form_id: int) -> list:
    filas = (
        db.query(FormApproval)
        .options(joinedload(FormApproval.user))
        .filter(FormApproval.form_id == form_id)
        .order_by(FormApproval.sequence_number)
        .all()
    )
    return [{
        "user_id": p.user_id,
        "name": p.user.name if p.user else None,
        "email": p.user.email if p.user else None,
        "participant_role": p.participant_role or "approver",
        "sequence_number": p.sequence_number,
        "is_mandatory": p.is_mandatory,
        "deadline_days": p.deadline_days,
        "is_active": p.is_active,
        "firm_mode": p.firm_mode,
        "receive_timing": p.receive_timing,
        "receives_from_user_ids": p.receives_from_user_ids,
    } for p in filas]


def _moderadores(db: Session, form_id: int) -> list:
    filas = (
        db.query(FormModerators, User)
        .join(User, User.id == FormModerators.user_id)
        .filter(FormModerators.form_id == form_id)
        .all()
    )
    return [{"user_id": u.id, "name": u.name, "email": u.email} for _, u in filas]


def _cierre(db: Session, form_id: int) -> Optional[dict]:
    c = db.query(FormCloseConfig).filter(FormCloseConfig.form_id == form_id).first()
    if not c:
        return None
    columnas = [x.key for x in sa_inspect(FormCloseConfig).mapper.column_attrs]
    return {k: getattr(c, k) for k in columnas if k not in _NO_COPIAR and k != 'form_id'}


def _enum(v):
    return v.value if hasattr(v, 'value') else v


def archivar_version(db: Session, form: Form, archivado_por: int, nueva_version: int) -> FormVersion:
    """Congela cómo está HOY el formato. Llamarla antes de aplicarle el borrador."""
    ahora = datetime.now(timezone.utc)
    version = form.version or 1

    # Un reintento tras un fallo a medias no debe chocar con la UNIQUE.
    previa = db.query(FormVersion).filter(FormVersion.form_id == form.id, FormVersion.version == version).first()
    if previa:
        db.delete(previa)
        db.flush()

    # Vigente desde que terminó la versión anterior. La primera que se archiva
    # cubre todo lo de antes: published_at se reescribe al re-publicar, y con
    # él quedaban por fuera respuestas que sí se hicieron con este diseño.
    anterior = (
        db.query(FormVersion)
        .filter(FormVersion.form_id == form.id, FormVersion.version < version)
        .order_by(FormVersion.version.desc())
        .first()
    )
    desde = anterior.valid_until if anterior else None

    fv = FormVersion(
        form_id=form.id,
        version=version,
        title=form.title,
        description=form.description,
        format_type=_enum(form.format_type),
        approval_mode=form.approval_mode,
        form_design=form.form_design,
        participants=_participantes(db, form.id),
        moderators=_moderadores(db, form.id),
        close_config=_cierre(db, form.id),
        change_note=form.change_note,
        valid_from=desde,
        valid_until=ahora,
        published_by=form.published_by,
        archived_by=archivado_por,
        replaced_by_version=nueva_version,
    )
    db.add(fv)
    db.flush()

    preguntas = (
        db.query(Question)
        .join(FormQuestion, FormQuestion.question_id == Question.id)
        .options(joinedload(Question.options))
        .filter(FormQuestion.form_id == form.id)
        .order_by(FormQuestion.id)
        .all()
    )
    vistas = set()
    for pos, q in enumerate(preguntas):
        if q.id in vistas:
            continue
        vistas.add(q.id)
        db.add(FormVersionQuestion(
            form_version_id=fv.id,
            question_id=q.id,
            question_text=q.question_text,
            description=q.description,
            question_type=_enum(q.question_type),
            required=q.required,
            options=[o.option_text for o in (q.options or [])],
            position=pos,
        ))
    db.flush()
    return fv


# ─────────────────────────────────────────────────────────────────────────────
# Aplicar el borrador al formato vigente
# ─────────────────────────────────────────────────────────────────────────────

def aplicar_borrador(db: Session, draft: Form, original: Form, publicado_por: int):
    """El vigente toma TODO lo del borrador. Conserva su id, sus respuestas y
    todo lo que lo nombra desde fuera."""
    ahora = datetime.now(timezone.utc)

    original.form_design = draft.form_design
    original.title = draft.title
    original.description = draft.description
    original.format_type = draft.format_type
    original.approval_mode = draft.approval_mode
    original.answer_editors_mode = draft.answer_editors_mode
    original.show_approver_answers_to_filler = draft.show_approver_answers_to_filler
    original.instructivo_url = draft.instructivo_url
    original.alert_message = draft.alert_message
    original.version = draft.version
    original.change_note = draft.change_note or f"Versión {draft.version}"
    original.published_by = publicado_por
    original.published_at = ahora
    original.valid_from = ahora
    original.valid_until = None

    # Campos: los mismos del borrador. Los quitados se desvinculan (la pregunta
    # y sus respuestas viejas siguen existiendo).
    del_borrador = [fq.question_id for fq in db.query(FormQuestion).filter(FormQuestion.form_id == draft.id).all()]
    db.query(FormQuestion).filter(FormQuestion.form_id == original.id).delete(synchronize_session=False)
    for qid in dict.fromkeys(del_borrador):
        db.add(FormQuestion(form_id=original.id, question_id=qid))

    copiar_configuracion(db, draft.id, original.id, reemplazar=True)
    db.flush()



# ─────────────────────────────────────────────────────────────────────────────
# Impacto de quitar campos
# ─────────────────────────────────────────────────────────────────────────────

def impacto_de_quitar(db: Session, draft: Form, original: Form) -> list:
    """Campos que el vigente tiene y el borrador quita, con los OTROS formatos
    que dependen de ellos. Al aprobar, esos formatos siguen viendo los datos
    viejos pero dejan de recibir datos nuevos de ese campo.

    Se miran tres dependencias:
      - lista / autocompletado: QuestionTableRelation.related_question_id
      - etiqueta del serial: relación de seriales al formato cuyo field_name es el campo
      - condición de filtro: QuestionFilterCondition (source / condition) en otro formato
    """
    antes = {fq.question_id for fq in db.query(FormQuestion).filter(FormQuestion.form_id == original.id).all()}
    despues = {fq.question_id for fq in db.query(FormQuestion).filter(FormQuestion.form_id == draft.id).all()}
    quitadas = antes - despues
    if not quitadas:
        return []

    preguntas = {q.id: q for q in db.query(Question).filter(Question.id.in_(quitadas)).all()}
    propios = {original.id, draft.id}
    usos = {qid: [] for qid in quitadas}

    def formatos_de(question_id: int) -> list:
        """Formatos (distintos al propio) que tienen esa pregunta."""
        filas = (
            db.query(Form.id, Form.title)
            .join(FormQuestion, FormQuestion.form_id == Form.id)
            .filter(FormQuestion.question_id == question_id, Form.id.notin_(propios),
                    Form.draft_class.is_(None))
            .distinct()
            .all()
        )
        return [{"id": f.id, "title": f.title} for f in filas]

    # 1. Listas y autocompletados que traen el dato de este campo.
    for rel in db.query(QuestionTableRelation).filter(QuestionTableRelation.related_question_id.in_(quitadas)).all():
        destino = db.query(Question).filter(Question.id == rel.question_id).first()
        for f in formatos_de(rel.question_id):
            usos[rel.related_question_id].append({
                "form_id": f["id"], "form_title": f["title"], "tipo": "lista",
                "detalle": f"«{destino.question_text if destino else rel.question_id}» trae sus datos (lista / autocompletado)",
            })

    # 2. Seriales de este formato que se etiquetan con este campo.
    for rel in db.query(QuestionTableRelation).filter(
        QuestionTableRelation.related_form_id == original.id,
        QuestionTableRelation.field_name.isnot(None),
    ).all():
        try:
            qid = int(rel.field_name)
        except (TypeError, ValueError):
            continue
        if qid not in usos:
            continue
        destino = db.query(Question).filter(Question.id == rel.question_id).first()
        for f in formatos_de(rel.question_id):
            usos[qid].append({
                "form_id": f["id"], "form_title": f["title"], "tipo": "serial",
                "detalle": f"«{destino.question_text if destino else rel.question_id}» lo usa como nombre del serial",
            })

    # 3. Condiciones de filtro de otros formatos que lo leen.
    conds = db.query(QuestionFilterCondition).filter(
        QuestionFilterCondition.form_id.notin_(propios),
        (QuestionFilterCondition.source_question_id.in_(quitadas)) | (QuestionFilterCondition.condition_question_id.in_(quitadas)),
    ).all()
    for c in conds:
        f = db.query(Form).filter(Form.id == c.form_id, Form.draft_class.is_(None)).first()
        if not f:
            continue
        for qid in {c.source_question_id, c.condition_question_id} & quitadas:
            usos[qid].append({
                "form_id": f.id, "form_title": f.title, "tipo": "condicion",
                "detalle": "lo usa en una condición de filtro",
            })

    out = []
    for qid, lista in usos.items():
        if not lista:
            continue
        # Sin repetir el mismo uso.
        vistos, unicos = set(), []
        for u in lista:
            k = (u["form_id"], u["tipo"], u["detalle"])
            if k not in vistos:
                vistos.add(k)
                unicos.append(u)
        q = preguntas.get(qid)
        out.append({
            "question_id": qid,
            "question_text": q.question_text if q else str(qid),
            "usos": unicos,
            "form_count": len({u["form_id"] for u in unicos}),
        })
    return sorted(out, key=lambda x: -x["form_count"])

# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

def _es_gestor(user: User) -> bool:
    return user.user_type in (UserType.admin, UserType.creator)


def _respuestas_de(db: Session, fv: FormVersion):
    """Diligenciamientos del formato enviados mientras esa versión estuvo vigente."""
    q = db.query(Response).filter(
        Response.form_id == fv.form_id,
        Response.parent_response_id.is_(None),
        Response.status != ResponseStatus.draft,
        Response.submitted_at < fv.valid_until,
    )
    if fv.valid_from is not None:
        q = q.filter(Response.submitted_at >= fv.valid_from)
    return q


def _resumen(fv: FormVersion, total: int, form: Optional[Form]) -> dict:
    return {
        "id": fv.id,
        "form_id": fv.form_id,
        "version": fv.version,
        "title": fv.title,
        "description": fv.description,
        "current_title": form.title if form else None,
        "current_version": form.version if form else None,
        "change_note": fv.change_note,
        "valid_from": fv.valid_from.isoformat() if fv.valid_from else None,
        "valid_until": fv.valid_until.isoformat() if fv.valid_until else None,
        "archived_at": fv.archived_at.isoformat() if fv.archived_at else None,
        "replaced_by_version": fv.replaced_by_version,
        "response_count": total,
        "question_count": len(fv.questions or []),
        "participant_count": len(fv.participants or []),
    }


def _version_o_404(db: Session, version_id: int) -> FormVersion:
    fv = (
        db.query(FormVersion)
        .options(joinedload(FormVersion.questions), joinedload(FormVersion.form))
        .filter(FormVersion.id == version_id)
        .first()
    )
    if not fv:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    return fv


def register_form_versions_routes(router):

    @router.get("/versions/impact/{draft_id}")
    def impacto_borrador(
        draft_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Lo que se rompe en otros formatos si se aprueba este borrador."""
        if not _es_gestor(current_user):
            raise HTTPException(status_code=403, detail="Solo administradores y creadores")
        draft = db.query(Form).filter(Form.id == draft_id).first()
        if not draft or not draft.lineage_id:
            raise HTTPException(status_code=404, detail="Borrador de versión no encontrado")
        original = (
            db.query(Form).filter(Form.id == draft.lineage_id).first()
            or db.query(Form).filter(Form.lineage_id == draft.lineage_id, Form.id != draft.id,
                                     Form.draft_class.is_(None)).first()
        )
        if not original:
            return {"campos": []}
        return {"campos": impacto_de_quitar(db, draft, original)}

    @router.get("/versions/ranges/{form_id}")
    def rangos_de_formato(
        form_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """De cuándo a cuándo estuvo vigente cada versión obsoleta. Con esto la
        pantalla de respuestas marca cuáles se enviaron con una versión
        anterior. Solo fechas y números: lo ve cualquiera que consulte."""
        form = db.query(Form).filter(Form.id == form_id).first()
        if not form:
            raise HTTPException(status_code=404, detail="Formato no encontrado")
        versiones = (
            db.query(FormVersion)
            .filter(FormVersion.form_id == form_id)
            .order_by(FormVersion.version.desc())
            .all()
        )
        return {
            "form_id": form_id,
            "current_version": form.version or 1,
            "versions": [{
                "id": fv.id,
                "version": fv.version,
                "valid_from": fv.valid_from.isoformat() if fv.valid_from else None,
                "valid_until": fv.valid_until.isoformat() if fv.valid_until else None,
            } for fv in versiones],
        }

    @router.get("/versions/{version_id}/design")
    def diseno_version(
        version_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Solo el diseño (como /forms/{id}/form_design), para pintar una
        respuesta con el formato que tenía cuando se envió."""
        fv = db.query(FormVersion).filter(FormVersion.id == version_id).first()
        if not fv:
            raise HTTPException(status_code=404, detail="Versión no encontrada")
        return {"id": fv.id, "form_id": fv.form_id, "version": fv.version, "title": fv.title,
                "form_design": fv.form_design or []}

    @router.get("/versions/obsolete")
    def listar_obsoletas(
        search: Optional[str] = Query(None),
        mine: bool = Query(False, description="Solo versiones con respuestas mías (Mis respuestas)"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Versiones obsoletas que el usuario puede consultar. Admin y creador
        ven todas; los demás, las que tengan respuestas suyas."""
        versiones = (
            db.query(FormVersion)
            .options(joinedload(FormVersion.questions), joinedload(FormVersion.form))
            .order_by(FormVersion.archived_at.desc())
            .all()
        )
        gestor = _es_gestor(current_user) and not mine
        termino = (search or "").strip().lower()
        out = []
        for fv in versiones:
            if termino and termino not in (fv.title or "").lower() and termino not in ((fv.form.title if fv.form else "") or "").lower():
                continue
            q = _respuestas_de(db, fv)
            if not gestor:
                q = q.filter(Response.user_id == current_user.id)
            total = q.count()
            if not gestor and total == 0:
                continue
            out.append(_resumen(fv, total, fv.form))
        return out

    @router.get("/versions/of/{form_id}")
    def versiones_de_formato(
        form_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Línea de tiempo: la vigente y las obsoletas, de la más nueva a la más vieja."""
        if not _es_gestor(current_user):
            raise HTTPException(status_code=403, detail="Solo administradores y creadores")
        form = db.query(Form).filter(Form.id == form_id).first()
        if not form:
            raise HTTPException(status_code=404, detail="Formato no encontrado")
        versiones = (
            db.query(FormVersion)
            .options(joinedload(FormVersion.questions))
            .filter(FormVersion.form_id == form_id)
            .order_by(FormVersion.version.desc())
            .all()
        )
        return {
            "form": {
                "id": form.id,
                "title": form.title,
                "version": form.version or 1,
                "valid_from": (form.valid_from or form.published_at or form.created_at).isoformat()
                if (form.valid_from or form.published_at or form.created_at) else None,
                "change_note": form.change_note,
                "form_status": _enum(form.form_status),
            },
            "versions": [_resumen(fv, _respuestas_de(db, fv).count(), form) for fv in versiones],
        }

    @router.get("/versions/{version_id}")
    def detalle_version(
        version_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Cómo era el formato en esa versión. Solo lectura."""
        fv = _version_o_404(db, version_id)
        if not _es_gestor(current_user):
            if _respuestas_de(db, fv).filter(Response.user_id == current_user.id).count() == 0:
                raise HTTPException(status_code=403, detail="No tienes acceso a esta versión")
        return {
            **_resumen(fv, _respuestas_de(db, fv).count(), fv.form),
            "format_type": fv.format_type,
            "approval_mode": fv.approval_mode,
            "form_design": fv.form_design or [],
            "participants": fv.participants or [],
            "moderators": fv.moderators or [],
            "close_config": fv.close_config,
            "questions": [{
                "question_id": q.question_id,
                "question_text": q.question_text,
                "description": q.description,
                "question_type": q.question_type,
                "required": q.required,
                "options": q.options or [],
            } for q in fv.questions],
        }

    @router.get("/versions/{version_id}/responses")
    def respuestas_version(
        version_id: int,
        page: int = Query(1, ge=1),
        page_size: int = Query(30, ge=1, le=200),
        mine: bool = Query(False),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        fv = _version_o_404(db, version_id)
        q = _respuestas_de(db, fv).options(joinedload(Response.user))
        if mine or not _es_gestor(current_user):
            q = q.filter(Response.user_id == current_user.id)
        total = q.count()
        filas = q.order_by(Response.submitted_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [{
                "id": r.id,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "status": _enum(r.status),
                "user_id": r.user_id,
                "user_name": r.user.name if r.user else None,
            } for r in filas],
        }

    @router.get("/versions/{version_id}/responses/{response_id}")
    def respuesta_version(
        version_id: int,
        response_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Una respuesta pintada con el diseño de la versión en que se envió."""
        fv = _version_o_404(db, version_id)
        r = _respuestas_de(db, fv).options(joinedload(Response.user)).filter(Response.id == response_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="La respuesta no pertenece a esta versión")
        if not _es_gestor(current_user) and r.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta respuesta")

        autores = {
            ra.user_id: ra.user.name
            for ra in db.query(ResponseApproval).options(joinedload(ResponseApproval.user))
            .filter(ResponseApproval.response_id == response_id).all()
            if ra.user
        }
        filas = (
            db.query(Answer, Question)
            .join(Question, Question.id == Answer.question_id)
            .filter(Answer.response_id.in_(response_scope.response_tree_ids(db, response_id)))
            .all()
        )
        return {
            "version": _resumen(fv, 0, fv.form),
            "response": {
                "id": r.id,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "status": _enum(r.status),
                "submitted_by": {"user_id": r.user.id, "name": r.user.name} if r.user else None,
            },
            "form_design": fv.form_design or [],
            "answers": [{
                "question_id": q.id,
                "question_text": q.question_text,
                "question_type": _enum(q.question_type),
                "answer_text": a.answer_text,
                "file_path": a.file_path,
                "answer_id": a.id,
                "form_design_element_id": a.form_design_element_id,
                "repeated_id": a.repeated_id,
                "repeater_row_index": a.repeater_row_index,
                "parent_repeated_id": a.parent_repeated_id,
                "answered_by_user_id": a.answered_by_user_id,
                "answered_by_name": autores.get(a.answered_by_user_id),
            } for a, q in filas],
        }
