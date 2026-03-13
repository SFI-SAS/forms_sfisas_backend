"""
email_service.py — SafeMetrics
v3.1 — Adjuntos FUNCIONALES en correos de cierre de formato

FIX v3.1:
  ✅ send_action_notification_email ahora busca la respuesta más reciente
     y genera PDF/Excel INTERNAMENTE — ya no depende de pdf_bytes externo
  ✅ send_download_link  → Adjunta Excel (.xlsx) con diseño completo
  ✅ send_pdf_attachment → Adjunta PDF (.pdf) con diseño completo
  ✅ generate_report     → Adjunta PDF (.pdf) con diseño completo
  ✅ Nuevo parámetro response_id (opcional, retrocompatible)
"""

import mimetypes
import os
import smtplib
import json
import io
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime
from typing import List, Dict, Optional

from fastapi import UploadFile

from app.api.controllers.excel_form_exporter import generate_form_excel
from app.api.controllers.pdf_form_exporter import FormPdfExporter
from app.models import Response, Form, Answer, FormAnswer, User
from app.schemas import EmailAnswerItem


# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN SMTP
# ═══════════════════════════════════════════════════════════════

MAIL_HOST_ALT = os.getenv("MAIL_HOST_ALT")
MAIL_PORT_ALT = os.getenv("MAIL_PORT_ALT")
MAIL_USERNAME_ALT = os.getenv("MAIL_USERNAME_ALT")
MAIL_PASSWORD_ALT = os.getenv("MAIL_PASSWORD_ALT")
MAIL_FROM_ADDRESS_ALT = os.getenv("MAIL_FROM_ADDRESS_ALT")

# ── Paleta corporativa ──
_C = {
    "brand":      "#0F8594",
    "brand_dark": "#0A5F6A",
    "brand_bg":   "#EDF7F8",
    "text":       "#1F2937",
    "text_sec":   "#4B5563",
    "text_muted": "#9CA3AF",
    "border":     "#E5E7EB",
    "bg":         "#F9FAFB",
    "white":      "#FFFFFF",
    "red":        "#DC2626",
    "red_bg":     "#FEF2F2",
    "red_dark":   "#991B1B",
    "amber":      "#D97706",
    "amber_bg":   "#FFFBEB",
    "amber_dark": "#92400E",
    "green":      "#059669",
    "green_bg":   "#ECFDF5",
    "green_dark": "#065F46",
}


# ═══════════════════════════════════════════════════════════════
# TEMPLATE BASE — HTML profesional reutilizable
# ═══════════════════════════════════════════════════════════════

def _base_email_html(title: str, body_content: str, footer_note: str = "") -> str:
    """Genera el wrapper HTML de todos los correos."""
    year = datetime.now().year
    date_str = datetime.now().strftime("%d/%m/%Y · %H:%M")

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Helvetica,Arial,sans-serif;background-color:#F3F4F6;color:{_C['text']};line-height:1.6;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#F3F4F6;padding:40px 16px;">
<tr><td align="center">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background-color:{_C['white']};border:1px solid {_C['border']};border-radius:6px;">

    <!-- HEADER -->
    <tr><td style="padding:20px 32px;border-bottom:2px solid {_C['brand']};">
        <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
            <td style="font-size:17px;font-weight:700;color:{_C['brand']};letter-spacing:-0.2px;">SafeMetrics</td>
            <td align="right" style="font-size:12px;color:{_C['text_muted']};">{date_str}</td>
        </tr>
        </table>
    </td></tr>

    <!-- TITULO -->
    <tr><td style="padding:28px 32px 12px;">
        <h1 style="margin:0;font-size:19px;font-weight:600;color:{_C['text']};">{title}</h1>
    </td></tr>

    <!-- CUERPO -->
    <tr><td style="padding:0 32px 32px;">
        {body_content}
    </td></tr>

    <!-- FOOTER -->
    <tr><td style="padding:18px 32px;background-color:{_C['bg']};border-top:1px solid {_C['border']};">
        {f'<p style="margin:0 0 6px;font-size:11px;color:{_C["text_muted"]};text-align:center;">{footer_note}</p>' if footer_note else ''}
        <p style="margin:0;font-size:11px;color:{_C['text_muted']};text-align:center;">&copy; {year} SafeMetrics &mdash; Correo generado automáticamente.</p>
    </td></tr>

</table>
</td></tr>
</table>

</body>
</html>"""


# ── Helpers de contenido ──

def _p(text: str) -> str:
    return f'<p style="font-size:14px;color:{_C["text_sec"]};margin:0 0 14px;">{text}</p>'


def _info_row(label: str, value: str) -> str:
    return f"""<tr>
        <td style="padding:5px 0;color:{_C['text_muted']};font-size:13px;width:38%;vertical-align:top;">{label}</td>
        <td style="padding:5px 0;color:{_C['text']};font-size:13px;vertical-align:top;">{value}</td>
    </tr>"""


def _info_block(heading: str, rows_html: str) -> str:
    return f"""<div style="margin:18px 0;">
        <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C['text']};text-transform:uppercase;letter-spacing:0.5px;">{heading}</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {_C['border']};">{rows_html}</table>
    </div>"""


def _callout(text: str, style: str = "info") -> str:
    """Cuadro lateral (info / success / warning / error)."""
    m = {
        "info":    (_C["brand"],  _C["brand_bg"],  _C["brand_dark"]),
        "success": (_C["green"],  _C["green_bg"],  _C["green_dark"]),
        "warning": (_C["amber"],  _C["amber_bg"],  _C["amber_dark"]),
        "error":   (_C["red"],    _C["red_bg"],    _C["red_dark"]),
    }
    bdr, bg, clr = m.get(style, m["info"])
    return f'<div style="margin:14px 0;padding:11px 14px;border-left:3px solid {bdr};background:{bg};border-radius:2px;"><p style="margin:0;font-size:13px;color:{clr};">{text}</p></div>'


def _btn(url: str, label: str = "Ir a SafeMetrics") -> str:
    return f"""<div style="margin:22px 0;text-align:center;">
        <a href="{url}" style="display:inline-block;padding:10px 26px;background-color:{_C['brand']};color:#fff;text-decoration:none;border-radius:4px;font-size:13px;font-weight:600;">{label}</a>
    </div>"""

_APP_URL = "https://forms.sfisas.com.co/"
_API_URL = "https://api-forms-sfi.service.saferut.com"


# ── SMTP ──

def _send_msg(msg: EmailMessage) -> bool:
    try:
        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"❌ Error SMTP: {e}")
        return False


def _new_msg(subject: str, to_email: str, to_name: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("SafeMetrics", MAIL_FROM_ADDRESS_ALT))
    msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
    return msg


# ═══════════════════════════════════════════════════════════════
# RECONSTRUCCIÓN DE repeated_id  (para adjuntos con diseño)
# ═══════════════════════════════════════════════════════════════

def _reconstruct_repeated_ids(form_design: list, answers_list: list, repeated_question_ids: set):
    """Reconstruye repeated_id sin columna en modelo Answer."""
    repeaters = []

    def _find(items):
        for it in items:
            if it.get("type") == "repeater":
                repeaters.append(it)
            for ch in (it.get("children") or []):
                _find([ch])
    _find(form_design)

    if not repeaters:
        return

    elem_map, q_map = {}, {}
    for rep in repeaters:
        rid = rep.get("id")
        if not rid:
            continue
        for ch in (rep.get("children") or []):
            cid = ch.get("id")
            if cid:
                elem_map[cid] = rid
            lid = ch.get("linkExternalId")
            if lid is not None:
                q_map[int(lid)] = rid
            sqid = (ch.get("props") or {}).get("sourceQuestionId")
            if sqid is not None:
                q_map[int(sqid)] = rid

    for ans in answers_list:
        if ans.get("repeated_id"):
            continue
        eid = ans.get("form_design_element_id")
        qid = ans.get("question_id")

        if eid and eid in elem_map:
            ans["repeated_id"] = elem_map[eid]
        elif qid is not None and qid in q_map:
            ans["repeated_id"] = q_map[qid]
        elif qid is not None and qid in repeated_question_ids:
            ans["repeated_id"] = repeaters[0].get("id")


def _serialize_answers_for_export(answers_orm, db, form_id: int, form_design: list) -> list:
    """Serializa answers ORM → dicts y reconstruye repeated_id."""
    answers = []
    for ans in answers_orm:
        answers.append({
            "id_answer":              ans.id,
            "question_id":            ans.question_id,
            "question_text":          ans.question.question_text if ans.question else "",
            "question_type":          (ans.question.question_type.value if ans.question and ans.question.question_type else "text"),
            "answer_text":            ans.answer_text or "",
            "file_path":              ans.file_path or "",
            "repeated_id":            None,
            "form_design_element_id": getattr(ans, "form_design_element_id", None),
        })

    rqids = {
        fa.question_id
        for fa in db.query(FormAnswer.question_id)
            .filter(FormAnswer.form_id == form_id, FormAnswer.is_repeated == True).all()
    }
    _reconstruct_repeated_ids(form_design, answers, rqids)
    return answers


def _extract_style_config(form_design: list):
    for item in form_design:
        props = item.get("props") or {}
        if props.get("styleConfig"):
            return props["styleConfig"]
        if item.get("headerTable") and not item.get("type"):
            return item
    return None


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN DE ADJUNTOS CON DISEÑO COMPLETO
# ═══════════════════════════════════════════════════════════════


def _filter_form_design_for_email(form_design: list, selected_fields: list) -> list:
    """Filtra form_design dejando solo campos en selected_fields. Decorativos siempre pasan."""
    if not selected_fields:
        return form_design
    qid_set = set(str(q) for q in selected_fields)

    def _item_matches(item: dict) -> bool:
        lex  = str(item.get("linkExternalId") or "")
        sqid = str((item.get("props") or {}).get("sourceQuestionId") or "")
        return lex in qid_set or sqid in qid_set

    def _filter_items(items: list) -> list:
        result = []
        for item in items:
            t = item.get("type", "")
            if not t:
                result.append(item)
                continue
            if t in ("horizontalLayout", "verticalLayout"):
                ch = _filter_items(item.get("children") or [])
                if ch:
                    result.append({**item, "children": ch})
            elif t == "repeater":
                ch = _filter_items(item.get("children") or [])
                if ch:
                    result.append({**item, "children": ch})
            elif t in ("label", "divider", "helpText", "image"):
                result.append(item)
            elif _item_matches(item):
                result.append(item)
        return result

    return _filter_items(form_design)


def generate_custom_template_pdf_bytes(db, form, response_obj, selected_fields: list) -> Optional[bytes]:
    """PDF con SOLO los campos del DownloadTemplate vinculado."""
    from sqlalchemy.orm import joinedload
    try:
        fd = form.form_design
        if isinstance(fd, str):
            fd = json.loads(fd)
        if not fd or not isinstance(fd, list):
            return None
        answers_orm = (
            db.query(Answer).options(joinedload(Answer.question))
            .filter(Answer.response_id == response_obj.id).all()
        )
        if not answers_orm:
            return None
        # Serializar con diseño COMPLETO (no pierde ningún answer)
        answers         = _serialize_answers_for_export(answers_orm, db, form.id, fd)
        sc              = _extract_style_config(fd)
        # Renderizar solo los campos del template
        filtered_design = _filter_form_design_for_email(fd, selected_fields)
        exporter = FormPdfExporter(
            form_design=filtered_design,
            answers=answers,
            style_config=sc,
            form_title=form.title,
            response_id=response_obj.id,
        )
        result = exporter.generate().getvalue()
        print(f"✅ PDF personalizado: {len(result)} bytes — response #{response_obj.id} — {len(selected_fields)} campos")
        return result
    except Exception as e:
        print(f"❌ Error PDF personalizado response {response_obj.id}: {e}")
        import traceback; traceback.print_exc()
        return None
def generate_response_pdf_bytes(db, form, response_obj) -> Optional[bytes]:
    """Genera PDF con diseño completo (soporta repeaters). Retorna bytes o None."""
    from sqlalchemy.orm import joinedload
    try:
        fd = form.form_design
        if isinstance(fd, str):
            fd = json.loads(fd)
        if not fd or not isinstance(fd, list):
            print(f"⚠️ form_design vacío o inválido para form {form.id}")
            return None

        answers_orm = (
            db.query(Answer).options(joinedload(Answer.question))
            .filter(Answer.response_id == response_obj.id).all()
        )
        if not answers_orm:
            print(f"⚠️ No se encontraron answers para response {response_obj.id}")
            return None

        answers = _serialize_answers_for_export(answers_orm, db, form.id, fd)
        sc = _extract_style_config(fd)

        exporter = FormPdfExporter(
            form_design=fd, answers=answers, style_config=sc,
            form_title=form.title, response_id=response_obj.id,
        )
        result = exporter.generate().getvalue()
        print(f"✅ PDF generado: {len(result)} bytes para response #{response_obj.id}")
        return result
    except Exception as e:
        print(f"❌ Error PDF response {response_obj.id}: {e}")
        import traceback; traceback.print_exc()
        return None


def generate_response_excel_bytes(db, form, response_obj) -> Optional[bytes]:
    """Genera Excel con diseño completo (soporta repeaters). Retorna bytes o None."""
    from sqlalchemy.orm import joinedload
    try:
        fd = form.form_design
        if isinstance(fd, str):
            fd = json.loads(fd)
        if not fd or not isinstance(fd, list):
            print(f"⚠️ form_design vacío o inválido para form {form.id}")
            return None

        answers_orm = (
            db.query(Answer).options(joinedload(Answer.question))
            .filter(Answer.response_id == response_obj.id).all()
        )
        if not answers_orm:
            print(f"⚠️ No se encontraron answers para response {response_obj.id}")
            return None

        answers = _serialize_answers_for_export(answers_orm, db, form.id, fd)
        sc = _extract_style_config(fd)

        buf = generate_form_excel(
            form_design=fd, answers=answers, style_config=sc,
            form_title=form.title, response_id=response_obj.id,
        )
        result = buf.getvalue()
        print(f"✅ Excel generado: {len(result)} bytes para response #{response_obj.id}")
        return result
    except Exception as e:
        print(f"❌ Error Excel response {response_obj.id}: {e}")
        import traceback; traceback.print_exc()
        return None


# ═══════════════════════════════════════════════════════════════
#  1. FORMULARIOS PENDIENTES (diario)
# ═══════════════════════════════════════════════════════════════

def send_email_daily_forms(user_email: str, user_name: str, forms: List[Dict]) -> bool:
    try:
        if not user_email or not user_name or not forms:
            return False

        rows = ""
        for i, f in enumerate(forms):
            bg = _C['bg'] if i % 2 == 0 else _C['white']
            rows += f"""<tr style="background:{bg};">
                <td style="padding:9px 12px;border-bottom:1px solid {_C['border']};font-size:13px;font-weight:600;">{f.get('title','Sin título')}</td>
                <td style="padding:9px 12px;border-bottom:1px solid {_C['border']};font-size:13px;color:{_C['text_sec']};">{f.get('description','Sin descripción')}</td>
            </tr>"""

        hdr_s = f'padding:9px 12px;text-align:left;font-size:11px;font-weight:600;color:{_C["text_muted"]};text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid {_C["border"]};'

        body = _p(f'Estimado/a <strong>{user_name}</strong>, tiene formularios pendientes de completar:')
        body += f"""<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C['border']};border-collapse:collapse;border-radius:4px;overflow:hidden;">
            <thead><tr style="background:{_C['bg']};">
                <th style="{hdr_s}">Formulario</th>
                <th style="{hdr_s}">Descripción</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>"""
        body += _btn(_APP_URL)

        html = _base_email_html("Formularios pendientes", body)
        msg = _new_msg(f"Formularios pendientes — {datetime.now().strftime('%d/%m/%Y')}", user_email, user_name)
        msg.set_content(f"Tiene {len(forms)} formularios pendientes. Ingrese a SafeMetrics para completarlos.")
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo diario a {user_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  2. ADJUNTO DE RESPUESTAS
# ═══════════════════════════════════════════════════════════════

def send_email_with_attachment(
    to_email: str, name_form: str, to_name: str, upload_file: UploadFile,
) -> bool:
    try:
        body = _p(f'Se adjunta el archivo con las respuestas del formulario <strong>"{name_form}"</strong> del usuario <strong>{to_name}</strong>.')
        body += _callout(f'Archivo adjunto: <strong>{upload_file.filename}</strong>', 'info')
        body += _p(f'<span style="color:{_C["text_muted"]};font-size:12px;">Revise el documento adjunto para consultar las respuestas completas.</span>')

        html = _base_email_html(f"Respuestas — {name_form}", body)
        msg = _new_msg(f"Respuestas adjuntas — {name_form}", to_email, to_name)
        msg.set_content(f'Se adjuntan las respuestas del formulario "{name_form}".')
        msg.add_alternative(html, subtype="html")

        upload_file.file.seek(0)
        data = upload_file.file.read()
        mt, _ = mimetypes.guess_type(upload_file.filename)
        main, sub = ("application", "octet-stream") if not mt else mt.split("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=upload_file.filename)

        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo adjunto a {to_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  3. BIENVENIDA
# ═══════════════════════════════════════════════════════════════

def send_welcome_email(email: str, name: str, password: str) -> bool:
    try:
        body = _p(f'Estimado/a <strong>{name}</strong>, su cuenta ha sido creada exitosamente.')
        body += _info_block("Credenciales de acceso",
            _info_row("Correo", email) +
            _info_row("Contraseña", f'<code style="background:{_C["bg"]};padding:2px 8px;border-radius:3px;font-family:monospace;font-size:13px;">{password}</code>')
        )
        body += _callout('Se recomienda cambiar la contraseña después del primer ingreso.', 'warning')
        body += _btn(_APP_URL, "Ingresar a SafeMetrics")

        html = _base_email_html("Bienvenido a SafeMetrics", body)
        msg = _new_msg("Bienvenido a SafeMetrics", email, name)
        msg.set_content(f"Bienvenido {name}. Email: {email} | Contraseña: {password}")
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo bienvenida a {email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  4. ESTADO DE APROBACIÓN
# ═══════════════════════════════════════════════════════════════

def send_email_plain_approval_status(
    to_email: str, name_form: str, to_name: str, body_text: str, subject: str
) -> bool:
    try:
        body = _p(f'El formato <strong>"{name_form}"</strong> ha sido procesado.')
        body += f'<div style="margin:14px 0;padding:12px 14px;background:{_C["bg"]};border:1px solid {_C["border"]};border-radius:4px;"><pre style="margin:0;font-family:\'Segoe UI\',sans-serif;font-size:13px;color:{_C["text"]};white-space:pre-wrap;word-wrap:break-word;">{body_text}</pre></div>'

        html = _base_email_html(subject, body)
        msg = _new_msg(subject, to_email, to_name)
        msg.set_content(f"Estimado/a {to_name},\n\n{body_text}")
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo aprobación a {to_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  5. APROBACIONES VENCIDAS
# ═══════════════════════════════════════════════════════════════

def send_email_plain_approval_status_vencidos(
    to_email: str, name_form: str, to_name: str, body_html: str, subject: str
) -> bool:
    try:
        body = _p(f'Se han detectado aprobaciones vencidas para el formato <strong>"{name_form}"</strong>.')
        body += body_html

        html = _base_email_html(subject, body)
        msg = _new_msg(subject, to_email, to_name)
        msg.set_content(f"Aprobaciones vencidas para {name_form}.")
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo vencidos a {to_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  6. SIGUIENTE APROBADOR
# ═══════════════════════════════════════════════════════════════

def send_email_aprovall_next(
    to_email: str, name_form: str, to_name: str, body_html: str, subject: str
) -> bool:
    try:
        body = _p(f'Tiene una aprobación pendiente para el formato <strong>"{name_form}"</strong>.')
        body += body_html
        body += _btn(_APP_URL, "Revisar en SafeMetrics")

        html = _base_email_html(subject, body)
        msg = _new_msg(subject, to_email, to_name)
        msg.set_content(f"Aprobación pendiente para {name_form}.")
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo aprobador a {to_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  7. RECHAZO
# ═══════════════════════════════════════════════════════════════

def _approvers_table(approvers: list) -> str:
    """Genera tabla de cadena de aprobación."""
    rows = ""
    for ap in approvers:
        sv = ap['status'].value.capitalize() if hasattr(ap['status'], 'value') else str(ap['status'])
        rows += f"""<tr>
            <td style="padding:7px 10px;border-bottom:1px solid {_C['border']};font-size:12px;text-align:center;">{ap['secuencia']}</td>
            <td style="padding:7px 10px;border-bottom:1px solid {_C['border']};font-size:12px;">{ap['nombre']}</td>
            <td style="padding:7px 10px;border-bottom:1px solid {_C['border']};font-size:12px;">{ap['email']}</td>
            <td style="padding:7px 10px;border-bottom:1px solid {_C['border']};font-size:12px;text-align:center;">{sv}</td>
            <td style="padding:7px 10px;border-bottom:1px solid {_C['border']};font-size:12px;">{ap.get('mensaje','—')}</td>
        </tr>"""

    hdr_s = f'padding:8px 10px;text-align:left;font-size:11px;font-weight:600;color:{_C["text_muted"]};text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid {_C["border"]};'
    return f"""<div style="margin:18px 0;">
        <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C['text']};text-transform:uppercase;letter-spacing:.5px;">Cadena de aprobación</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C['border']};border-collapse:collapse;">
        <thead><tr style="background:{_C['bg']};">
            <th style="{hdr_s}text-align:center;">Seq</th>
            <th style="{hdr_s}">Nombre</th>
            <th style="{hdr_s}">Email</th>
            <th style="{hdr_s}text-align:center;">Estado</th>
            <th style="{hdr_s}">Mensaje</th>
        </tr></thead>
        <tbody>{rows}</tbody>
        </table>
    </div>"""


def send_rejection_email(
    to_email: str, to_name: str, formato: dict,
    usuario_respondio: dict, aprobador_rechazo: dict, todos_los_aprobadores: list
):
    try:
        body = _p(f'Estimado/a <strong>{to_name}</strong>, las respuestas al formulario <strong>"{formato["titulo"]}"</strong> han sido <span style="color:{_C["red"]};font-weight:600;">rechazadas</span>.')

        body += _info_block("Formulario",
            _info_row("Título", formato['titulo']) +
            _info_row("Descripción", formato['descripcion']) +
            _info_row("Tipo", formato['tipo_formato'].capitalize()) +
            _info_row("Creado por", f"{formato['creado_por']['nombre']} ({formato['creado_por']['email']})")
        )
        body += _info_block("Respondido por",
            _info_row("Nombre", usuario_respondio['nombre']) +
            _info_row("Correo", usuario_respondio['email']) +
            _info_row("Documento", usuario_respondio['num_documento'])
        )
        body += _info_block("Rechazado por",
            _info_row("Nombre", f"{aprobador_rechazo['nombre']} ({aprobador_rechazo['email']})") +
            _info_row("Motivo", aprobador_rechazo.get('mensaje', 'Sin mensaje')) +
            _info_row("Fecha", aprobador_rechazo.get('reviewed_at', 'No disponible'))
        )
        body += _approvers_table(todos_los_aprobadores)

        html = _base_email_html(f"Formulario rechazado — {formato['titulo']}", body)
        msg = _new_msg(f"Formulario rechazado: {formato['titulo']}", to_email, to_name)
        msg.set_content(f'El formulario "{formato["titulo"]}" ha sido rechazado.')
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo rechazo a {to_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  8. RECONSIDERACIÓN
# ═══════════════════════════════════════════════════════════════

def send_reconsideration_email(
    to_email: str, to_name: str, formato: dict,
    usuario_solicita: dict, mensaje_reconsideracion: str,
    aprobador_que_rechazo: dict, todos_los_aprobadores: list
):
    try:
        body = _p(f'Estimado/a <strong>{to_name}</strong>, el usuario <strong>{usuario_solicita["nombre"]}</strong> ha solicitado reconsideración para el formulario <strong>"{formato["titulo"]}"</strong>.')
        body += _callout(f'<strong>Motivo de reconsideración:</strong><br>{mensaje_reconsideracion}', 'warning')

        body += _info_block("Solicitante",
            _info_row("Nombre", usuario_solicita['nombre']) +
            _info_row("Correo", usuario_solicita['email']) +
            _info_row("Documento", usuario_solicita['num_documento'])
        )
        body += _info_block("Rechazo original",
            _info_row("Por", f"{aprobador_que_rechazo['nombre']} ({aprobador_que_rechazo['email']})") +
            _info_row("Motivo", aprobador_que_rechazo.get('mensaje', 'Sin mensaje')) +
            _info_row("Fecha", aprobador_que_rechazo.get('reviewed_at', 'No disponible'))
        )
        body += _approvers_table(todos_los_aprobadores)
        body += _callout('Se solicita revisar nuevamente las respuestas considerando la justificación proporcionada.', 'info')
        body += _btn(_APP_URL, "Revisar en SafeMetrics")

        html = _base_email_html(f"Solicitud de reconsideración — {formato['titulo']}", body)
        msg = _new_msg(f"Reconsideración solicitada: {formato['titulo']}", to_email, to_name)
        msg.set_content(f'Reconsideración solicitada para "{formato["titulo"]}" por {usuario_solicita["nombre"]}.')
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo reconsideración a {to_email}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  9. NOTIFICACIÓN DE ACCIÓN AL CERRAR FORMATO  ★ CORREGIDO v3.1 ★
# ═══════════════════════════════════════════════════════════════

def _generate_report_table_html(form_data) -> str:
    """Tabla de reporte para correo de generate_report."""
    if not form_data or not form_data.get('questions'):
        return _callout("No hay datos disponibles para mostrar.", "warning")

    hdr_s = f'padding:8px 10px;text-align:left;font-size:11px;font-weight:600;color:{_C["text_muted"]};border-bottom:1px solid {_C["border"]};'

    if not form_data.get('responses'):
        rows = ""
        for i, q in enumerate(form_data['questions']):
            bg = _C['bg'] if i % 2 == 0 else _C['white']
            req = "Sí" if q.get('required') else "No"
            rows += f'<tr style="background:{bg};"><td style="padding:7px 10px;border-bottom:1px solid {_C["border"]};font-size:12px;">{q["question_text"]}</td><td style="padding:7px 10px;border-bottom:1px solid {_C["border"]};font-size:12px;text-align:center;">{q["question_type"].capitalize()}</td><td style="padding:7px 10px;border-bottom:1px solid {_C["border"]};font-size:12px;text-align:center;">{req}</td></tr>'
        return f"""<div style="margin:18px 0;">
            <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C['text']};text-transform:uppercase;letter-spacing:.5px;">Estructura del formulario</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C['border']};border-collapse:collapse;">
            <thead><tr style="background:{_C['bg']};">
                <th style="{hdr_s}">Pregunta</th><th style="{hdr_s}text-align:center;">Tipo</th><th style="{hdr_s}text-align:center;">Requerida</th>
            </tr></thead><tbody>{rows}</tbody></table>
            <p style="margin:8px 0 0;font-size:12px;color:{_C['text_muted']};">Sin respuestas registradas.</p>
        </div>"""

    headers = [q['question_text'] for q in form_data['questions']]
    hcells = f'<th style="{hdr_s}text-align:center;">ID</th>'
    for h in headers:
        hcells += f'<th style="{hdr_s}">{h}</th>'

    brows = ""
    for i, resp in enumerate(form_data['responses']):
        bg = _C['bg'] if i % 2 == 0 else _C['white']
        amap = {a['question_id']: a['answer_text'] for a in resp.get('answers', [])}
        cells = f'<td style="padding:7px 10px;border-bottom:1px solid {_C["border"]};font-size:12px;font-weight:600;text-align:center;">{resp["id"]}</td>'
        for q in form_data['questions']:
            v = amap.get(q['id'], '—')
            if len(str(v)) > 80:
                v = str(v)[:80] + "…"
            cells += f'<td style="padding:7px 10px;border-bottom:1px solid {_C["border"]};font-size:12px;">{v}</td>'
        brows += f'<tr style="background:{bg};">{cells}</tr>'

    return f"""<div style="margin:18px 0;">
        <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C['text']};text-transform:uppercase;letter-spacing:.5px;">Reporte de respuestas ({len(form_data['responses'])})</p>
        <div style="overflow-x:auto;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C['border']};border-collapse:collapse;">
        <thead><tr style="background:{_C['bg']};">{hcells}</tr></thead>
        <tbody>{brows}</tbody></table></div>
    </div>"""


# Alias para compatibilidad
generate_report_table_html = _generate_report_table_html


async def send_action_notification_email(
    action: str, recipient: str, form, current_date: str,
    pdf_bytes=None, pdf_filename=None, db=None, current_user=None,
    response_id: int = None,
    action_meta: dict = None,
):
    """
    ★ CORREGIDO v3.1 ★
    Notificación de acción de cierre de formato.
    Ahora busca la respuesta y genera PDF/Excel INTERNAMENTE.

    Acciones:
      send_download_link  → Adjunta Excel (.xlsx) con la respuesta
      send_pdf_attachment → Adjunta PDF (.pdf) con la respuesta
      generate_report     → Adjunta PDF (.pdf) con la respuesta

    Si no se pasa response_id, busca la respuesta más reciente del form.
    """
    try:
        titles = {
                    'send_download_link':    ("Respuestas adjuntas en Excel", "Se adjunta el archivo Excel con las respuestas del formulario."),
                    'send_pdf_attachment':   ("Respuestas adjuntas en PDF",   "Se adjunta el PDF con las respuestas del formulario."),
                    'generate_report':       ("Reporte de respuesta",         "Se adjunta el reporte en PDF con las respuestas del formulario."),
                    'send_custom_template':  ("PDF personalizado de cierre",  "Se adjunta el PDF con los campos configurados en la plantilla de cierre."),
                }
        title, desc = titles.get(action, ("Notificación", f"Acción ejecutada: {action}"))

        # ── Info del formulario ──
        body = _p(desc)
        body += _info_block("Formulario",
            _info_row("Título", form.title) +
            _info_row("Descripción", form.description or 'Sin descripción') +
            _info_row("Tipo", form.format_type.value.capitalize()) +
            _info_row("Creado por", f"{form.user.name} ({form.user.email})")
        )

        # ══════════════════════════════════════════════════════════
        # ★ PASO 1: BUSCAR LA RESPUESTA
        # ══════════════════════════════════════════════════════════
        response_obj = None
        if db:
            if response_id:
                response_obj = db.query(Response).filter(Response.id == response_id).first()
                if response_obj:
                    print(f"📋 Usando response_id proporcionado: #{response_id}")

            if not response_obj:
                # Fallback: respuesta más reciente del formulario
                response_obj = (
                    db.query(Response)
                    .filter(Response.form_id == form.id)
                    .order_by(Response.id.desc())
                    .first()
                )
                if response_obj:
                    print(f"📋 Usando respuesta más reciente: #{response_obj.id}")
                else:
                    print(f"⚠️ No se encontraron respuestas para form {form.id}")

        # Mostrar info de la respuesta en el correo
        if response_obj:
            resp_user = db.query(User).filter(User.id == response_obj.user_id).first()
            resp_user_name = resp_user.name if resp_user else f"Usuario {response_obj.user_id}"
            submitted = current_date
            if hasattr(response_obj, 'submitted_at') and response_obj.submitted_at:
                submitted = str(response_obj.submitted_at)[:19]
            elif hasattr(response_obj, 'created_at') and response_obj.created_at:
                submitted = str(response_obj.created_at)[:19]

            body += _info_block("Respuesta",
                _info_row("ID", f'#{response_obj.id}') +
                _info_row("Usuario", resp_user_name) +
                _info_row("Fecha", submitted)
            )

        # ══════════════════════════════════════════════════════════
        # ★ PASO 2: GENERAR ADJUNTO SEGÚN LA ACCIÓN
        # ══════════════════════════════════════════════════════════
        attachment_bytes = None
        attachment_filename = None
        attachment_maintype = "application"
        attachment_subtype = "octet-stream"

        safe_title = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in form.title)

        if response_obj and db:

            # ── Esperar a que los answers estén guardados ──
            # (el background task puede arrancar antes de que se guarden)
            import time
            for attempt in range(1, 8):  # hasta 7 intentos (~7 seg máx)
                answer_count = db.query(Answer).filter(
                    Answer.response_id == response_obj.id
                ).count()
                if answer_count > 0:
                    print(f"✅ Answers encontrados: {answer_count} para response #{response_obj.id} (intento {attempt})")
                    break
                print(f"⏳ Esperando answers para response #{response_obj.id}... (intento {attempt}/7)")
                db.expire_all()  # forzar re-lectura de la DB
                time.sleep(1)
            else:
                print(f"⚠️ Timeout: no se encontraron answers para response #{response_obj.id} después de 7 intentos")

            if action == 'send_download_link':
                # ★ EXCEL adjunto
                print(f"📊 Generando Excel para response #{response_obj.id}...")
                attachment_bytes = generate_response_excel_bytes(db, form, response_obj)
                if attachment_bytes:
                    attachment_filename = f"Respuesta_{response_obj.id}_{safe_title}.xlsx"
                    attachment_subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    body += _callout(f'Archivo adjunto: <strong>{attachment_filename}</strong>', 'success')
                    print(f"✅ Excel listo: {attachment_filename} ({len(attachment_bytes)} bytes)")
                else:
                    body += _callout('No se pudo generar el archivo Excel adjunto.', 'warning')
                    print(f"❌ Falló generación de Excel para response #{response_obj.id}")

            elif action == 'send_pdf_attachment':
                # ★ PDF adjunto
                print(f"📄 Generando PDF para response #{response_obj.id}...")
                attachment_bytes = generate_response_pdf_bytes(db, form, response_obj)
                if attachment_bytes:
                    attachment_filename = f"Respuesta_{response_obj.id}_{safe_title}.pdf"
                    attachment_subtype = "pdf"
                    body += _callout(f'Archivo adjunto: <strong>{attachment_filename}</strong>', 'success')
                    print(f"✅ PDF listo: {attachment_filename} ({len(attachment_bytes)} bytes)")
                elif pdf_bytes:
                    # Fallback: pdf_bytes externo (compatibilidad con código viejo)
                    attachment_bytes = pdf_bytes
                    attachment_filename = pdf_filename or f"Formato_{safe_title}.pdf"
                    attachment_subtype = "pdf"
                    body += _callout(f'Archivo adjunto: <strong>{attachment_filename}</strong>', 'info')
                    print(f"📎 Usando pdf_bytes fallback: {attachment_filename}")
                else:
                    body += _callout('No se pudo generar el archivo PDF adjunto.', 'warning')
                    print(f"❌ Falló generación de PDF para response #{response_obj.id}")

            elif action == 'generate_report':
                # ★ PDF adjunto (reporte)
                print(f"📊 Generando reporte PDF para response #{response_obj.id}...")
                attachment_bytes = generate_response_pdf_bytes(db, form, response_obj)
                if attachment_bytes:
                    attachment_filename = f"Reporte_{response_obj.id}_{safe_title}.pdf"
                    attachment_subtype = "pdf"
                    body += _callout(f'Reporte adjunto: <strong>{attachment_filename}</strong>', 'success')
                    print(f"✅ Reporte PDF listo: {attachment_filename} ({len(attachment_bytes)} bytes)")
                else:
                    body += _callout('No se pudo generar el reporte PDF adjunto.', 'warning')
                    print(f"❌ Falló generación de reporte PDF para response #{response_obj.id}")

            elif action == 'send_custom_template':
                meta        = action_meta or {}
                template_id = meta.get('custom_template_id')
                include_pdf = meta.get('include_pdf', False)

                if not template_id:
                    body += _callout('No hay plantilla personalizada configurada.', 'warning')
                    print(f"⚠️ send_custom_template sin template_id para form {form.id}")
                else:
                    from app.models import DownloadTemplate as DLTemplate
                    tpl = db.query(DLTemplate).filter(DLTemplate.id == template_id).first()

                    if not tpl:
                        body += _callout(f'Plantilla #{template_id} no encontrada.', 'warning')
                        print(f"❌ Plantilla #{template_id} no existe en DB")
                    else:
                        selected_fields = tpl.selected_fields or []
                        print(f"📋 Plantilla #{template_id} — {len(selected_fields)} campos")

                        # PDF personalizado con solo los campos del template
                        attachment_bytes = generate_custom_template_pdf_bytes(
                            db, form, response_obj, selected_fields
                        )
                        if attachment_bytes:
                            attachment_filename = f"Plantilla_{response_obj.id}_{safe_title}.pdf"
                            attachment_subtype  = "pdf"
                            body += _callout(
                                f'PDF personalizado adjunto: <strong>{attachment_filename}</strong>',
                                'success'
                            )
                            print(f"✅ PDF personalizado listo: {attachment_filename} ({len(attachment_bytes)} bytes)")
                        else:
                            body += _callout('No se pudo generar el PDF personalizado.', 'warning')

                        # Si include_pdf=True → adjuntar también el PDF completo normal
                        if include_pdf:
                            normal_pdf = generate_response_pdf_bytes(db, form, response_obj)
                            if normal_pdf:
                                normal_filename = f"Completo_{response_obj.id}_{safe_title}.pdf"
                                html_2 = _base_email_html(title, body)
                                msg_2  = _new_msg(f"{title} — {form.title}", recipient)
                                msg_2.set_content(f"{title}: {form.title}")
                                msg_2.add_alternative(html_2, subtype="html")
                                if attachment_bytes:
                                    msg_2.add_attachment(
                                        attachment_bytes,
                                        maintype="application", subtype="pdf",
                                        filename=attachment_filename,
                                    )
                                msg_2.add_attachment(
                                    normal_pdf,
                                    maintype="application", subtype="pdf",
                                    filename=normal_filename,
                                )
                                print(f"📎 Correo con 2 PDFs → {recipient}")
                                return _send_msg(msg_2)
                            else:
                                body += _callout('No se pudo generar el PDF completo adicional.', 'warning')


        elif not response_obj:
            body += _callout('No se encontraron respuestas para adjuntar.', 'warning')

        # ══════════════════════════════════════════════════════════
        # ★ PASO 3: CONSTRUIR Y ENVIAR CORREO
        # ══════════════════════════════════════════════════════════
        html = _base_email_html(title, body)
        msg = _new_msg(f"{title} — {form.title}", recipient)
        msg.set_content(f"{title}: {form.title}")
        msg.add_alternative(html, subtype="html")

        # Adjuntar archivo si se generó
        if attachment_bytes and attachment_filename:
            msg.add_attachment(
                attachment_bytes,
                maintype=attachment_maintype,
                subtype=attachment_subtype,
                filename=attachment_filename,
            )
            print(f"📎 Adjunto añadido al correo: {attachment_filename}")
        else:
            print(f"⚠️ Correo '{action}' se envía SIN adjunto a {recipient}")

        return _send_msg(msg)

    except Exception as e:
        print(f"❌ Error correo acción '{action}' a {recipient}: {e}")
        import traceback; traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════
#  10. CORREO CON RESPUESTAS DETALLADAS
# ═══════════════════════════════════════════════════════════════

def send_response_answers_email(
    to_emails: list[str],
    form_title: str,
    response_id: int,
    answers: list[EmailAnswerItem],
):
    try:
        rows = ""
        for i, item in enumerate(answers):
            bg = _C['bg'] if i % 2 == 0 else _C['white']
            val = item.answer_text or f'<span style="color:{_C["text_muted"]};font-style:italic;">Sin respuesta</span>'
            if item.file_path:
                val += f'<br><a href="{item.file_path}" style="display:inline-block;margin-top:5px;padding:3px 10px;background:{_C["brand_bg"]};color:{_C["brand"]};text-decoration:none;border-radius:3px;font-size:12px;font-weight:500;">Ver archivo</a>'
            rows += f"""<tr style="background:{bg};">
                <td style="padding:10px 12px;border-bottom:1px solid {_C['border']};font-size:13px;font-weight:500;color:{_C['text']};width:40%;vertical-align:top;">{item.question_text}</td>
                <td style="padding:10px 12px;border-bottom:1px solid {_C['border']};font-size:13px;color:{_C['text_sec']};vertical-align:top;">{val}</td>
            </tr>"""

        hdr_s = f'padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:{_C["text_muted"]};text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid {_C["border"]};'

        body = _p(f'Se ha registrado una nueva respuesta para el formulario <strong>"{form_title}"</strong>.')
        body += _info_block("Información",
            _info_row("Formulario", form_title) +
            _info_row("ID Respuesta", f'<strong>#{response_id}</strong>') +
            _info_row("Fecha", datetime.now().strftime("%d/%m/%Y %H:%M"))
        )
        body += f"""<div style="margin:18px 0;">
            <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C['text']};text-transform:uppercase;letter-spacing:.5px;">Respuestas</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C['border']};border-collapse:collapse;border-radius:4px;overflow:hidden;">
            <thead><tr style="background:{_C['bg']};">
                <th style="{hdr_s}">Pregunta</th><th style="{hdr_s}">Respuesta</th>
            </tr></thead>
            <tbody>{rows}</tbody></table>
        </div>"""

        html = _base_email_html(f"Nueva respuesta — {form_title}", body)

        for email in to_emails:
            msg = _new_msg(f"Nueva respuesta: {form_title} (#{response_id})", email)
            msg.set_content(f"Nueva respuesta #{response_id} para {form_title}.")
            msg.add_alternative(html, subtype="html")
            _send_msg(msg)
        return True
    except Exception as e:
        print(f"❌ Error correo respuestas: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  11. ALERTA DE VENCIMIENTO (REGLAS)
# ═══════════════════════════════════════════════════════════════

def send_rule_notification_email(
    user_email: str, user_name: str, form_title: str, form_description: str,
    response_id: int, date_limit: str, days_remaining: int,
    days_before_alert: int, question_text: str,
    user_document: str, user_telephone: str
) -> bool:
    try:
        try:
            d = datetime.strptime(str(date_limit), "%Y-%m-%d") if isinstance(date_limit, str) else date_limit
            fdate = d.strftime("%d/%m/%Y")
        except:
            fdate = str(date_limit)

        if days_remaining <= 2:
            urg, sty = "URGENTE", "error"
        elif days_remaining <= 5:
            urg, sty = "IMPORTANTE", "warning"
        else:
            urg, sty = "RECORDATORIO", "info"

        day_word = "día" if days_remaining == 1 else "días"

        body = _callout(f'<strong>{urg}</strong> — Quedan <strong>{days_remaining} {day_word}</strong> para el vencimiento.', sty)
        body += _p(f'Estimado/a <strong>{user_name}</strong>, se acerca la fecha límite para una respuesta del formulario.')

        body += _info_block("Formulario",
            _info_row("Título", form_title) +
            _info_row("Descripción", form_description) +
            _info_row("ID Respuesta", f'#{response_id}') +
            _info_row("Pregunta relacionada", f'<em>"{question_text}"</em>')
        )
        body += _info_block("Fechas",
            _info_row("Fecha límite", f'<strong>{fdate}</strong>') +
            _info_row("Días restantes", f'<strong>{days_remaining}</strong>') +
            _info_row("Alerta configurada", f'{days_before_alert} días antes')
        )
        body += _info_block("Destinatario",
            _info_row("Nombre", user_name) +
            _info_row("Correo", user_email) +
            _info_row("Documento", user_document) +
            _info_row("Teléfono", user_telephone)
        )
        body += _btn(_APP_URL)

        html = _base_email_html(
            f"{urg}: Vencimiento próximo — {form_title}", body,
            footer_note="Alerta generada por el sistema de reglas de SafeMetrics."
        )
        msg = _new_msg(f"{urg}: Vencimiento próximo — {form_title}", user_email, user_name)
        msg.set_content(f"{urg}: Quedan {days_remaining} {day_word} para {form_title}. Respuesta #{response_id}.")
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception as e:
        print(f"❌ Error correo alerta a {user_email}: {e}")
        return False