"""
Correo con el código de firma de quien no usa biometría.

Módulo ADITIVO, igual que `password_reset_mail.py` y `external_signoff_mail.py`:
reutiliza los helpers de plantilla de `mail.py` SIN modificarlo (intocable #10).
No cambia ninguna plantilla existente, ni la config SMTP, ni las funciones de
envío.

El código es FIJO: no vence y no cambia solo. Se manda al registrar a la persona
y cada vez que un administrador genere uno nuevo (que reemplaza al anterior).
Este es el ÚNICO lugar por donde el código sale en claro: en la base solo queda
su hash, así que si se pierde no se puede consultar, hay que generar otro.
"""

import logging

from app.api.controllers.mail import (
    _C,
    _base_email_html,
    _callout,
    _info_block,
    _info_row,
    _new_msg,
    _p,
    _send_msg,
)

logger = logging.getLogger(__name__)


def send_signature_code_email(
    *,
    email: str,
    name: str,
    code: str,
    es_nuevo: bool = False,
) -> bool:
    """Manda a la persona su código de firma.

    `es_nuevo` cambia el texto: cuando un administrador lo regenera hay que
    decirle que el anterior dejó de servir, o seguirá intentando con el viejo.
    """
    try:
        titulo = "Su nuevo código de firma" if es_nuevo else "Su código de firma"

        if es_nuevo:
            body = _p(
                f'Hola <strong>{name}</strong>, un administrador generó un '
                f'código de firma nuevo para usted. El código anterior ya no sirve.'
            )
        else:
            body = _p(
                f'Hola <strong>{name}</strong>, quedó registrado para firmar '
                f'documentos en Safemetrics con un código, en vez de con '
                f'reconocimiento facial.'
            )

        body += _info_block(
            "Código de firma",
            _info_row(
                "Código",
                f'<code style="background:{_C["bg"]};padding:4px 14px;'
                f'border-radius:4px;font-family:monospace;font-size:22px;'
                f'letter-spacing:4px;font-weight:bold;">{code}</code>',
            )
            + _info_row("A nombre de", name),
        )

        body += _p(
            'Cuando tenga que firmar un documento, se le pedirá este código. '
            'No vence: es el mismo siempre, hasta que se genere uno nuevo.'
        )

        body += _callout(
            'Guárdelo y no lo comparta: quien tenga este código puede firmar '
            'en su nombre. Si cree que alguien más lo conoce, pida a un '
            'administrador que le genere uno nuevo.',
            'warning',
        )

        html = _base_email_html(titulo, body)
        msg = _new_msg(f"{titulo} — Safemetrics", email, name)
        msg.set_content(
            f"Hola {name}.\n"
            f"{'Su código de firma nuevo es' if es_nuevo else 'Su código de firma es'}: {code}\n"
            f"Se le pedirá cada vez que tenga que firmar un documento. No vence.\n"
            f"No lo comparta: quien lo tenga puede firmar en su nombre."
        )
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception:
        logger.warning(
            "Error enviando el código de firma",
            extra={"event": "signature_code_mail_fail"},
        )
        return False
