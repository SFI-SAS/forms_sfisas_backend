"""
Aviso por correo al aprobar o rechazar un formato.

Mismo patrón que aviso_asignacion.py: importa los ayudantes de mail.py,
nunca lanza excepción, se despacha en segundo plano.
"""
from __future__ import annotations

import logging
import os

from app.api.controllers.mail import (
    _base_email_html,
    _btn,
    _callout,
    _info_block,
    _info_row,
    _new_msg,
    _p,
    _send_msg,
)

logger = logging.getLogger(__name__)

URL_APP = (os.getenv("PUBLIC_APP_URL") or "").strip().rstrip("/")


def avisar_formato_aprobado(
    *,
    nombre_creador: str,
    correo_creador: str,
    titulo_formato: str,
    form_id: int,
    aprobado_por: str,
    categoria: str | None = None,
) -> bool:
    """Avisa al creador que su formato fue aprobado y publicado."""
    if not correo_creador or "@" not in correo_creador:
        return False

    try:
        filas = (
            _info_row("Formato", f"#{form_id} — {titulo_formato}")
            + _info_row("Aprobado por", aprobado_por)
        )
        if categoria:
            filas += _info_row("Categoría", categoria)

        cuerpo = (
            _p(f"Hola {nombre_creador or ''},".strip())
            + _p("Tu formato fue <b>aprobado y publicado</b> en SafeMetrics. Ya está disponible para que los usuarios lo diligencien.")
            + _info_block("Detalle", filas)
            + _callout(
                "El formato ya aparece en la sección <b>Diligenciar</b> para los usuarios asignados.",
                "success",
            )
        )
        if URL_APP:
            cuerpo += _btn(f"{URL_APP}/home/edit_forms?formId={form_id}", "Ver formato")

        html = _base_email_html("Formato aprobado", cuerpo)

        msg = _new_msg(
            f"Tu formato fue aprobado: {titulo_formato}",
            correo_creador,
            nombre_creador or "",
        )
        msg.set_content(
            f"Hola {nombre_creador or ''},\n\n"
            f"Tu formato \"{titulo_formato}\" (#{form_id}) fue aprobado y publicado "
            f"por {aprobado_por} en SafeMetrics.\n"
            f"Ya está disponible para diligenciar.\n"
        )
        msg.add_alternative(html, subtype="html")

        enviado = _send_msg(msg)
        if not enviado:
            logger.warning("No se pudo enviar aviso de aprobación de formato",
                           extra={"event": "aviso_formato_aprobado_fallido"})
        return enviado

    except Exception:
        logger.warning("Fallo al componer aviso de aprobación de formato",
                       extra={"event": "aviso_formato_aprobado_error"}, exc_info=True)
        return False


def avisar_formato_rechazado(
    *,
    nombre_creador: str,
    correo_creador: str,
    titulo_formato: str,
    form_id: int,
    rechazado_por: str,
    motivo: str | None = None,
    categoria: str | None = None,
) -> bool:
    """Avisa al creador que su formato fue rechazado con observaciones."""
    if not correo_creador or "@" not in correo_creador:
        return False

    try:
        filas = (
            _info_row("Formato", f"#{form_id} — {titulo_formato}")
            + _info_row("Rechazado por", rechazado_por)
        )
        if categoria:
            filas += _info_row("Categoría", categoria)

        cuerpo = (
            _p(f"Hola {nombre_creador or ''},".strip())
            + _p("Tu formato fue <b>devuelto con observaciones</b>. Puedes corregirlo y reenviarlo, o descartarlo si ya no lo necesitas.")
            + _info_block("Detalle", filas)
        )

        if motivo:
            cuerpo += _callout(
                f"<b>Motivo:</b> {motivo}",
                "warning",
            )
        else:
            cuerpo += _callout(
                "No se especificó un motivo. Revisa las observaciones dentro del formato.",
                "warning",
            )

        if URL_APP:
            cuerpo += _btn(f"{URL_APP}/home/my_drafts", "Ver mis borradores")

        html = _base_email_html("Formato rechazado", cuerpo)

        msg = _new_msg(
            f"Tu formato fue rechazado: {titulo_formato}",
            correo_creador,
            nombre_creador or "",
        )
        msg.set_content(
            f"Hola {nombre_creador or ''},\n\n"
            f"Tu formato \"{titulo_formato}\" (#{form_id}) fue rechazado "
            f"por {rechazado_por} en SafeMetrics.\n"
            f"Motivo: {motivo or 'Sin motivo especificado'}\n\n"
            f"Puedes corregirlo y reenviarlo desde Mis borradores.\n"
        )
        msg.add_alternative(html, subtype="html")

        enviado = _send_msg(msg)
        if not enviado:
            logger.warning("No se pudo enviar aviso de rechazo de formato",
                           extra={"event": "aviso_formato_rechazado_fallido"})
        return enviado

    except Exception:
        logger.warning("Fallo al componer aviso de rechazo de formato",
                       extra={"event": "aviso_formato_rechazado_error"}, exc_info=True)
        return False


def avisar_pendientes_vencidos(
    *,
    nombre_aprobador: str,
    correo_aprobador: str,
    pendientes: list[dict],
    es_escalamiento: bool = False,
) -> bool:
    """
    Correo resumen diario de formatos pendientes vencidos — Guía v3 §5.6.

    Se envía máximo una vez al día. Cada item en `pendientes` tiene:
      id, title, age_days, user_name
    """
    if not correo_aprobador or "@" not in correo_aprobador:
        return False
    if not pendientes:
        return False

    try:
        oldest = max(p["age_days"] for p in pendientes)
        count = len(pendientes)

        filas_html = ""
        for p in sorted(pendientes, key=lambda x: -x["age_days"]):
            dias = p["age_days"]
            color = "#dc2626" if dias >= 5 else "#f59e0b"
            filas_html += (
                f'<tr>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;color:#6b7280;">#{p["id"]}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#1f2937;">{p["title"]}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280;">{p.get("user_name", "")}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:700;color:{color};">hace {dias} día{"s" if dias != 1 else ""}</td>'
                f'</tr>'
            )

        tabla = (
            '<table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;">'
            '<thead><tr style="background:#f3f4f6;">'
            '<th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;">#</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;">Formato</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;">Creado por</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;">Antigüedad</th>'
            '</tr></thead>'
            f'<tbody>{filas_html}</tbody></table>'
        )

        tipo_aviso = "Escalamiento" if es_escalamiento else "Resumen diario"
        cuerpo = (
            _p(f"Hola {nombre_aprobador or ''},".strip())
            + _p(
                f"Tienes <b>{count} formato{'s' if count != 1 else ''}</b> esperando tu revisión "
                f"que {'superaron' if count > 1 else 'superó'} el tiempo comprometido."
            )
            + _callout(
                f"El más antiguo lleva <b>{oldest} día{'s' if oldest != 1 else ''}</b>.",
                "warning" if oldest < 5 else "error",
            )
            + tabla
        )

        if es_escalamiento:
            cuerpo += _callout(
                "Este correo es un <b>escalamiento</b>: estos formatos llevan más de 5 días "
                "hábiles sin atención y se le notifica como administrador.",
                "error",
            )

        if URL_APP:
            cuerpo += _btn(f"{URL_APP}/home/pending_approval", "Ver pendientes")

        html = _base_email_html(f"{tipo_aviso} · {count} pendiente{'s' if count != 1 else ''}", cuerpo)

        asunto = (
            f"SafeMetrics · {count} formato{'s' if count != 1 else ''} "
            f"pendiente{'s' if count != 1 else ''} de aprobación"
        )
        if es_escalamiento:
            asunto = f"[ESCALAMIENTO] {asunto}"

        msg = _new_msg(asunto, correo_aprobador, nombre_aprobador or "")
        # Texto plano
        lineas = "\n".join(
            f"  #{p['id']} — {p['title']}  ·  hace {p['age_days']} días"
            for p in sorted(pendientes, key=lambda x: -x["age_days"])
        )
        msg.set_content(
            f"Hola {nombre_aprobador or ''},\n\n"
            f"Tienes {count} formato(s) esperando tu revisión:\n\n"
            f"{lineas}\n\n"
            f"El más antiguo lleva {oldest} día(s).\n"
        )
        msg.add_alternative(html, subtype="html")

        enviado = _send_msg(msg)
        if not enviado:
            logger.warning("No se pudo enviar resumen de pendientes vencidos",
                           extra={"event": "aviso_pendientes_fallido"})
        return enviado

    except Exception:
        logger.warning("Fallo al componer resumen de pendientes vencidos",
                       extra={"event": "aviso_pendientes_error"}, exc_info=True)
        return False
