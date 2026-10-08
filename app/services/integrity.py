"""
Regla permanente de integridad — Guía v3 §6.

  6.2 — Campo consumido no se borra.
  6.4 — Formato consumido no se borra ni desactiva.
"""

from collections import defaultdict
from sqlalchemy.orm import Session
from app.models import (
    Form, FormQuestion, Question,
    QuestionTableRelation, QuestionFilterCondition, ApprovalRequirement,
)


def get_question_consumers(db: Session, question_id: int) -> list[dict]:
    """Lista formatos que consumen este campo."""
    own_forms = {fid for (fid,) in db.query(FormQuestion.form_id).filter(FormQuestion.question_id == question_id).all()}
    consumers, seen = [], set()

    # QuestionTableRelation: alguien trae este campo
    for qtr in db.query(QuestionTableRelation).filter(QuestionTableRelation.related_question_id == question_id).all():
        for (fid,) in db.query(FormQuestion.form_id).filter(FormQuestion.question_id == qtr.question_id).all():
            if fid not in own_forms and fid not in seen:
                seen.add(fid)
                f = db.query(Form).filter(Form.id == fid).first()
                consumers.append({"form_id": fid, "form_title": f.title if f else f"#{fid}", "type": "dato"})

    # QuestionFilterCondition
    for qfc in db.query(QuestionFilterCondition).filter(
        (QuestionFilterCondition.source_question_id == question_id) | (QuestionFilterCondition.condition_question_id == question_id)
    ).all():
        if qfc.form_id not in own_forms and qfc.form_id not in seen:
            seen.add(qfc.form_id)
            f = db.query(Form).filter(Form.id == qfc.form_id).first()
            consumers.append({"form_id": qfc.form_id, "form_title": f.title if f else f"#{qfc.form_id}", "type": "condición"})

    return consumers


def get_form_consumers(db: Session, form_id: int) -> list[dict]:
    """Lista formatos que consumen campos de este formato."""
    my_qids = {qid for (qid,) in db.query(FormQuestion.question_id).filter(FormQuestion.form_id == form_id).all()}
    consumers, seen = [], set()

    if my_qids:
        for qtr in db.query(QuestionTableRelation).filter(
            (QuestionTableRelation.related_question_id.in_(my_qids)) | (QuestionTableRelation.related_form_id == form_id)
        ).all():
            for (fid,) in db.query(FormQuestion.form_id).filter(FormQuestion.question_id == qtr.question_id).all():
                if fid != form_id and fid not in seen:
                    seen.add(fid)
                    f = db.query(Form).filter(Form.id == fid).first()
                    consumers.append({"form_id": fid, "form_title": f.title if f else f"#{fid}", "type": "dato"})

    for ar in db.query(ApprovalRequirement).filter(ApprovalRequirement.required_form_id == form_id).all():
        if ar.form_id != form_id and ar.form_id not in seen:
            seen.add(ar.form_id)
            f = db.query(Form).filter(Form.id == ar.form_id).first()
            consumers.append({"form_id": ar.form_id, "form_title": f.title if f else f"#{ar.form_id}", "type": "aprob"})

    return consumers


def check_can_delete_question(db: Session, question_id: int) -> dict:
    consumers = get_question_consumers(db, question_id)
    if not consumers:
        return {"allowed": True}
    q = db.query(Question).filter(Question.id == question_id).first()
    names = ", ".join(f"#{c['form_id']} {c['form_title']}" for c in consumers[:5])
    return {
        "allowed": False,
        "consumers": consumers,
        "message": f"El campo «{q.question_text if q else question_id}» lo leen {len(consumers)} formato(s): {names}. Para cambiarlo hay que crear una versión nueva.",
    }


def check_can_delete_form(db: Session, form_id: int) -> dict:
    consumers = get_form_consumers(db, form_id)
    if not consumers:
        return {"allowed": True}
    f = db.query(Form).filter(Form.id == form_id).first()
    names = ", ".join(f"#{c['form_id']} {c['form_title']}" for c in consumers[:5])
    return {
        "allowed": False,
        "consumers": consumers,
        "message": f"El formato «{f.title if f else form_id}» lo leen {len(consumers)} formato(s): {names}. No se puede borrar ni desactivar.",
    }
