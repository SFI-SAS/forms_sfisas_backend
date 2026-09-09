"""
Aviso por correo cuando alguien tiene un formato esperándolo.

Módulo NUEVO y aparte, con el mismo criterio que `aviso_asignacion.py`: no
modifica `mail.py`, solo **importa** sus ayudantes (plantilla HTML de la casa,
construcción del mensaje y envío SMTP), porque duplicar maquetación y
credenciales sería peor.

Por qué existe
──────────────
El aviso de "tienes esto pendiente" se estaba mandando con
`send_email_plain_approval_status_vencidos`, que es la función de **aprobaciones
VENCIDAS**: su primera línea, fija, dice "Se han detectado aprobaciones vencidas
para el formato X". Así que a todo el mundo —aprobadores y recibidores— le
llegaba un correo que abría hablando de vencimientos y de aprobación, aunque el
cuerpo dijera otra cosa y aunque a esa persona solo le tocara recibir.

Aquí la primera línea la pone el papel de quien lo recibe.
"""
from __future__ import annotations

import logging

from app.api.controllers.mail import (
    _base_email_html,
    _new_msg,
    _p,
    _send_msg,
)

logger = logging.getLogger(__name__)


def avisar_pendiente(
    *,
    correo: str,
    nombre: str,
    titulo_formato: str,
    cuerpo_html: str,
    asunto: str,
    es_recibidor: bool = False,
) -> bool:
    """Avisa a un participante que tiene un formato esperándolo.

    `es_recibidor`: al que solo recibe no se le habla de aprobar.

    Devuelve True si el correo salió. NUNCA lanza excepción: avisar no puede
    tumbar el guardado de la respuesta.
    """
    if not correo or "@" not in correo:
        logger.info(
            "Pendiente sin aviso: el participante no tiene correo válido",
            extra={"event": "aviso_pendiente_sin_correo"},
        )
        return False

    try:
        if es_recibidor:
            intro = (
                f'Le entregaron el formato <strong>"{titulo_formato}"</strong> '
                f"para que confirme su recepción."
            )
            plano = f"Tiene un formato por recibir: {titulo_formato}."
        else:
            intro = (
                f'Tiene pendiente la aprobación del formato '
                f'<strong>"{titulo_formato}"</strong>.'
            )
            plano = f"Tiene una aprobación pendiente: {titulo_formato}."

        cuerpo = _p(intro) + (cuerpo_html or "")

        html = _base_email_html(asunto, cuerpo)
        msg = _new_msg(asunto, correo, nombre)
        msg.set_content(f"Estimado/a {nombre or ''},\n\n{plano}".strip())
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception:
        logger.warning(
            "Error enviando el aviso de pendiente",
            extra={"event": "aviso_pendiente_fail"},
        )
        return False
