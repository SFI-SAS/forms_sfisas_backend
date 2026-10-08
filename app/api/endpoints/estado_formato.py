"""Estado completo de un formato en UNA lectura.

Para saber cómo quedó un formato hacía falta juntar form-details (datos y diseño), /questions
(tipos y opciones) y, por CADA campo, su origen de lista y su categoría: más de 40 llamadas para un
formato de 20 campos. ArIA lo necesita antes y después de cada cambio para comparar lo pedido con lo
que de verdad quedó (diseño "estado deseado"); sirve igual a cualquier otro cliente.

Solo lee.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database import get_db
from app.models import (Form, FormCategory, FormModerators, FormQuestion, Option, Question, QuestionCategory,
                        QuestionFilterCondition, QuestionTableRelation, User, UserType)

router = APIRouter()


@router.get("/formatos/{form_id}")
def estado_formato(form_id: int, db: Session = Depends(get_db),
                   current_user: User = Depends(require_roles([UserType.admin, UserType.creator]))):
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail=f"El formato {form_id} no existe.")
    carpeta = db.query(FormCategory).filter(FormCategory.id == form.id_category).first() \
        if form.id_category else None

    qids = [r.question_id for r in db.query(FormQuestion).filter(FormQuestion.form_id == form_id)
            .order_by(FormQuestion.id)]
    preguntas = {q.id: q for q in db.query(Question).filter(Question.id.in_(qids))} if qids else {}
    cats = {c.id: c for c in db.query(QuestionCategory)}
    opciones = {}
    for o in db.query(Option).filter(Option.question_id.in_(qids)).order_by(Option.id) if qids else []:
        opciones.setdefault(o.question_id, []).append(o.option_text)
    origen = {r.question_id: r for r in db.query(QuestionTableRelation)
              .filter(QuestionTableRelation.question_id.in_(qids))} if qids else {}
    filtros = {}
    for c in db.query(QuestionFilterCondition).filter(QuestionFilterCondition.form_id == form_id):
        filtros.setdefault(c.filtered_question_id, []).append({
            "fuente": c.source_question_id, "condicion": c.condition_question_id,
            "operador": c.operator, "valor": c.expected_value, "solo_ultimo": c.use_latest_only})

    campos = []
    for qid in qids:
        q = preguntas.get(qid)
        if not q:
            continue
        cat = cats.get(q.id_category)
        padre = cats.get(cat.parent_id) if cat and cat.parent_id else None
        r = origen.get(qid)
        campos.append({
            "id": q.id, "texto": q.question_text, "tipo": q.question_type.value
            if hasattr(q.question_type, "value") else q.question_type,
            "propio": q.id_form == form_id, "obligatorio": bool(q.required), "unico": bool(q.unique_answer),
            "descripcion": q.description,
            "categoria": {"id": cat.id, "nombre": cat.name, "padre": padre.name if padre else None} if cat else None,
            "opciones": opciones.get(qid, []),
            "origen": {"tabla": r.name_table, "campo": r.field_name, "formato": r.related_form_id,
                       "pregunta": r.related_question_id, "usuario_logueado": r.logged_user_part} if r else None,
            "filtros": filtros.get(qid, []),
        })

    diseno = form.form_design
    if isinstance(diseno, str):
        try:
            diseno = json.loads(diseno)
        except ValueError:
            diseno = []
    return {
        "formato": {"id": form.id, "titulo": form.title, "descripcion": form.description,
                    "tipo": form.format_type.value if hasattr(form.format_type, "value") else form.format_type,
                    "publicado": bool(form.is_enabled),
                    # Guía v3: borrador → publicar es POST /forms/publish/{id}; el toggle viejo solo toca is_enabled
                    "estado": getattr(getattr(form, "form_status", None), "value", None),
                    "carpeta": {"id": carpeta.id, "nombre": carpeta.name} if carpeta else None,
                    "modo_aprobacion": form.approval_mode, "creador": form.user_id,
                    # quién puede diligenciarlo: los asignados del formato son sus moderadores
                    "asignados": [{"id": u.id, "nombre": u.name, "email": u.email, "documento": u.num_document}
                                  for u in db.query(User).join(FormModerators, FormModerators.user_id == User.id)
                                  .filter(FormModerators.form_id == form.id).order_by(User.name)]},
        "campos": campos,
        "diseno": diseno or [],
    }
