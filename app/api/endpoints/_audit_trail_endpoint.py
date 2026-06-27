"""
Audit trail endpoint for movimientos.
This file is meant to be included/imported into forms.py router.
"""
from datetime import datetime as _dt
from typing import Optional

from fastapi import Query, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.core.security import get_current_user
from app.models import (
    AnswerHistory, Form, FormCloseConfig, FormMovimientos,
    RelationQuestionRule, Response, ResponseApproval, ResponseStatus, User,
)
from app.models_audit import NotificationSendLog


def _user_can_view_movimiento_audit(user, mov):
    from app.models import UserType
    if user.user_type.name == UserType.admin.name:
        return True
    if mov.user_id == user.id:
        return True
    return user.id in (mov.allowed_user_ids or [])


def register_audit_trail_route(router):
    """Call this from forms.py to register the audit-trail GET endpoint."""

    @router.get("/movimientos/{movement_id}/audit-trail", status_code=status.HTTP_200_OK)
    def get_movimiento_audit_trail(
        movement_id: int,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        form_id: Optional[int] = Query(None),
        user_id: Optional[int] = Query(None),
        response_status: Optional[str] = Query(None, alias="status"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Trazabilidad completa de los formatos asociados a un movimiento."""

        movimiento = db.query(FormMovimientos).filter(
            FormMovimientos.id == movement_id,
            FormMovimientos.is_enabled == True,
        ).first()
        if not movimiento:
            raise HTTPException(status_code=404, detail="Movimiento no encontrado")
        if not _user_can_view_movimiento_audit(current_user, movimiento):
            raise HTTPException(status_code=403, detail="No tienes permiso para ver este movimiento")

        target_form_ids = movimiento.form_ids or []
        if form_id is not None:
            if form_id not in target_form_ids:
                raise HTTPException(status_code=400, detail="El formato indicado no pertenece a este movimiento")
            target_form_ids = [form_id]

        if not target_form_ids:
            return {
                "movement_id": movement_id, "title": movimiento.title, "forms": [],
                "pagination": {"page": 1, "page_size": page_size, "total_rows": 0, "total_pages": 0},
                "rows": [],
            }

        forms_db = db.query(Form).filter(Form.id.in_(target_form_ids)).all()
        forms_map = {f.id: f for f in forms_db}
        forms_list = [{"form_id": f.id, "form_title": f.title} for f in forms_db]

        q = (
            db.query(Response)
            .filter(Response.form_id.in_(target_form_ids))
            .options(
                joinedload(Response.user),
                joinedload(Response.approvals).joinedload(ResponseApproval.user),
            )
        )
        if user_id is not None:
            q = q.filter(Response.user_id == user_id)
        if response_status is not None:
            try:
                q = q.filter(Response.status == ResponseStatus(response_status))
            except ValueError:
                pass

        # Date filter
        def _parse_dt(s, end_of_day=False):
            if not s:
                return None
            raw = str(s).strip()
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
                try:
                    return _dt.strptime(raw, fmt)
                except (TypeError, ValueError):
                    continue
            try:
                d = _dt.strptime(raw[:10], "%Y-%m-%d")
            except (TypeError, ValueError):
                return None
            return d.replace(hour=23, minute=59, second=59, microsecond=999999) if end_of_day else d

        dt_from = _parse_dt(date_from)
        dt_to = _parse_dt(date_to, end_of_day=True)
        if dt_from:
            _df = dt_from.replace(tzinfo=None) if dt_from.tzinfo else dt_from
            q = q.filter(Response.submitted_at >= _df)
        if dt_to:
            _dto = dt_to.replace(tzinfo=None) if dt_to.tzinfo else dt_to
            q = q.filter(Response.submitted_at <= _dto)

        q = q.order_by(Response.submitted_at.desc())
        total_rows = q.count()
        total_pages = max(1, -(-total_rows // page_size))
        responses = q.offset((page - 1) * page_size).limit(page_size).all()
        response_ids = [r.id for r in responses]

        # Bulk queries
        close_configs: dict = {}
        for cc in db.query(FormCloseConfig).filter(FormCloseConfig.form_id.in_(target_form_ids)).all():
            close_configs[cc.form_id] = cc

        send_logs: dict = {}
        if response_ids:
            for lg in db.query(NotificationSendLog).filter(NotificationSendLog.response_id.in_(response_ids)).all():
                send_logs.setdefault(lg.response_id, []).append(lg)

        rules_by_resp: dict = {}
        if response_ids:
            for r in db.query(RelationQuestionRule).filter(
                RelationQuestionRule.id_response.in_(response_ids)
            ).options(joinedload(RelationQuestionRule.question)).all():
                rules_by_resp.setdefault(r.id_response, []).append(r)

        history_by_resp: dict = {}
        if response_ids:
            for ah in db.query(AnswerHistory).filter(
                AnswerHistory.response_id.in_(response_ids)
            ).order_by(AnswerHistory.updated_at).all():
                history_by_resp.setdefault(ah.response_id, []).append(ah)

        # Build rows
        rows = []
        for resp in responses:
            usr = resp.user
            form_obj = forms_map.get(resp.form_id)

            approvals_data = []
            rejected_by = None
            for appr in sorted(resp.approvals, key=lambda a: a.sequence_number):
                approvals_data.append({
                    "sequence_number": appr.sequence_number,
                    "is_mandatory": appr.is_mandatory,
                    "status": appr.status.value if appr.status else "pendiente",
                    "reviewed_at": appr.reviewed_at.isoformat() if appr.reviewed_at else None,
                    "user": {"user_id": appr.user.id, "name": appr.user.name, "nickname": getattr(appr.user, "nickname", None)} if appr.user else None,
                    "message": appr.message,
                    "firm_mode": appr.firm_mode,
                    "has_firm_answer": appr.firm_answer_id is not None,
                    "attachment_count": len(appr.attachment_files) if appr.attachment_files else 0,
                })
                if appr.status and appr.status.value == "rechazado" and rejected_by is None:
                    rejected_by = {
                        "user_id": appr.user.id if appr.user else None,
                        "name": appr.user.name if appr.user else None,
                        "reviewed_at": appr.reviewed_at.isoformat() if appr.reviewed_at else None,
                        "message": appr.message,
                    }

            close_actions_data = []
            cc = close_configs.get(resp.form_id)
            if cc:
                resp_logs = send_logs.get(resp.id, [])
                for aname, enabled, recips, evt in [
                    ("send_download_link", cc.send_download_link, cc.download_link_recipients, "close_download_link"),
                    ("send_pdf_attachment", cc.send_pdf_attachment, cc.email_recipients, "close_pdf"),
                    ("generate_report", cc.generate_report, cc.report_recipients, "close_report"),
                    ("send_custom_template", cc.send_custom_template, cc.custom_template_recipients, "close_custom_template"),
                ]:
                    if not enabled:
                        continue
                    close_actions_data.append({
                        "action": aname,
                        "configured_recipients": recips or [],
                        "sends": [{"recipient_email": lg.recipient_email, "status": lg.status, "sent_at": lg.sent_at.isoformat() if lg.sent_at else None, "detail": lg.detail} for lg in resp_logs if lg.event_type == evt],
                    })

            reminders_data = []
            for rule in rules_by_resp.get(resp.id, []):
                r_logs = [lg for lg in send_logs.get(resp.id, []) if lg.event_type == "scheduled_reminder"]
                reminders_data.append({
                    "rule_id": rule.id,
                    "question_label": rule.question.question_text if rule.question else None,
                    "date_notification": rule.date_notification.isoformat() if rule.date_notification else None,
                    "time_alert": rule.time_alert,
                    "notification_email": rule.notification_email,
                    "enabled": rule.enabled,
                    "sends": [{"recipient_email": lg.recipient_email, "status": lg.status, "sent_at": lg.sent_at.isoformat() if lg.sent_at else None} for lg in r_logs],
                })

            rows.append({
                "response_id": resp.id,
                "form_id": resp.form_id,
                "form_title": form_obj.title if form_obj else "Desconocido",
                "submitted_at": resp.submitted_at.isoformat() if resp.submitted_at else None,
                "status": resp.status.value if resp.status else None,
                "submitted_by": {"user_id": usr.id, "name": usr.name, "nickname": getattr(usr, "nickname", None), "email": usr.email} if usr else None,
                "rejected_by": rejected_by,
                "approvals": approvals_data,
                "close_actions": close_actions_data,
                "reminders": reminders_data,
                "answer_changes": [{"updated_at": ah.updated_at.isoformat() if ah.updated_at else None, "previous_answer_id": ah.previous_answer_id, "current_answer_id": ah.current_answer_id} for ah in history_by_resp.get(resp.id, [])],
            })

        return {
            "movement_id": movement_id,
            "title": movimiento.title,
            "forms": forms_list,
            "pagination": {"page": page, "page_size": page_size, "total_rows": total_rows, "total_pages": total_pages},
            "rows": rows,
        }
