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
