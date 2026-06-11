"""
Correo de restablecimiento de contraseña (acción de administrador).

Módulo ADITIVO: reutiliza los helpers de plantilla de `mail.py` SIN modificarlo
(intocable #10). Solo importa los helpers; no cambia ninguna plantilla, la
config SMTP ni las funciones de envío existentes.

Flujo: un administrador restablece la contraseña de un usuario desde la pantalla
de gestión de usuarios; el backend genera una contraseña nueva y la envía al
correo del usuario con esta función.
"""

import logging

from app.api.controllers.mail import (
    _APP_URL,
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


def send_password_reset_email(email: str, name: str, new_password: str) -> bool:
    """Envía al usuario su nueva contraseña tras un reseteo hecho por un admin."""
    try:
        body = _p(
            f'Estimado/a <strong>{name}</strong>, un administrador ha '
            f'restablecido su contraseña de acceso a SafeMetrics.'
        )
        body += _info_block(
            "Nueva contraseña de acceso",
            _info_row("Correo", email)
            + _info_row(
                "Contraseña",
                f'<code style="background:{_C["bg"]};padding:2px 8px;'
                f'border-radius:3px;font-family:monospace;font-size:13px;">'
                f'{new_password}</code>',
            ),
        )
        body += _callout(
            'Por seguridad, cambie esta contraseña después de ingresar. '
            'Si usted no solicitó este cambio, comuníquese con el administrador.',
            'warning',
        )
        body += _btn(_APP_URL, "Ingresar a SafeMetrics")

        html = _base_email_html("Restablecimiento de contraseña", body)
        msg = _new_msg("Restablecimiento de contraseña — SafeMetrics", email, name)
        msg.set_content(
            f"Hola {name}. Su contraseña de SafeMetrics fue restablecida por un "
            f"administrador.\nCorreo: {email}\nNueva contraseña: {new_password}\n"
            f"Por seguridad, cámbiela después de ingresar."
        )
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception:
        logger.warning(
            "Error enviando correo de reseteo de contraseña",
            extra={"event": "reset_mail_fail"},
        )
        return False
