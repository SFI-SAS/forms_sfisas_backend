"""
Correo de registro externo: el botón que le llega a alguien sin usuario.

Módulo ADITIVO, igual que `password_reset_mail.py`: reutiliza los helpers de
plantilla de `mail.py` SIN modificarlo (intocable #10). No cambia ninguna
plantilla existente, ni la config SMTP, ni las funciones de envío.

Quien lo recibe no es usuario de Safemetrics y no va a serlo: no se le habla de
ingresar, ni de contraseñas, ni de la plataforma. Se le pide una sola cosa.
"""

import logging

from app.api.controllers.mail import (
    _C,
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


def send_external_signoff_email(
    *,
    to_email: str,
    to_name: str,
    form_title: str,
    requested_by_name: str,
    link: str,
    action_label: str = "Registrar mi salida",
    subject_text: str | None = None,
    expires_text: str | None = None,
) -> bool:
    """Manda el correo con el botón del registro externo.

    `link` ya viene firmado y con el token dentro; aquí no se genera nada.
    """
    try:
        saludo = f"Hola <strong>{to_name}</strong>, " if to_name else "Hola, "
        body = _p(
            f"{saludo}<strong>{requested_by_name}</strong> te está pidiendo que "
            f"registres tu hora en <strong>{form_title}</strong>."
        )

        filas = _info_row("Formato", form_title) + _info_row("Lo solicita", requested_by_name)
        if expires_text:
            filas += _info_row("El enlace vence", expires_text)
        body += _info_block("Detalle", filas)

        body += _btn(link, action_label)

        body += _callout(
            "Al tocar el botón se abre una página que te va a pedir permiso para "
            "usar tu ubicación. Toca <strong>Permitir</strong> y listo: la hora y "
            "el lugar quedan registrados solos, no tienes que escribir nada.",
            "info",
        )
        body += _p(
            f'<span style="font-size:12px;color:{_C["text_muted"]};">'
            f"Si el botón no abre, copia y pega esta dirección en tu navegador:<br>"
            f'<span style="word-break:break-all;">{link}</span></span>'
        )

        titulo = subject_text or "Registro de hora"
        html = _base_email_html(titulo, body, footer_note=(
            "Este enlace es personal y sirve una sola vez."
        ))

        asunto = f"{subject_text} — {form_title}" if subject_text else f"Registro de hora — {form_title}"
        msg = _new_msg(asunto, to_email, to_name or "")
        msg.set_content(
            f"Hola {to_name or ''}. {requested_by_name} te pide registrar tu hora "
            f"en {form_title}.\n\n"
            f"Abre este enlace y permite el acceso a tu ubicación:\n{link}\n\n"
            f"El enlace es personal y sirve una sola vez."
        )
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception:
        logger.warning(
            "Error enviando correo de registro externo",
            extra={"event": "external_signoff_mail_fail"},
        )
        return False
