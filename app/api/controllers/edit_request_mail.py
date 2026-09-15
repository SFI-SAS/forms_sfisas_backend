"""
Aviso al usuario cuando el administrador atiende su solicitud de edición.

Módulo ADITIVO, como `password_reset_mail.py` y `aviso_asignacion.py`: importa
los ayudantes de `mail.py` —plantilla, construcción del mensaje y envío SMTP—
pero NO lo modifica (intocable #10). Duplicar credenciales y maquetación sería
peor: dos sitios que mantener y dos que se desincronizan.

Regla de oro: **avisar nunca puede impedir resolver.** Si el correo falla, el
administrador ya aprobó o rechazó y eso está guardado. Ninguna función de aquí
lanza excepciones hacia arriba.
"""

import logging
from typing import List, Optional

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


def _lista_campos(labels: List[str]) -> str:
    if not labels:
        return "la respuesta completa"
    return ", ".join(labels)


def avisar_solicitud_resuelta(
    *,
    to_email: str,
    to_name: str,
    form_title: str,
    response_id: int,
    aprobada: bool,
    campos: Optional[List[str]] = None,
    todos: bool = False,
    revisado_por: str = "",
    mensaje_admin: Optional[str] = None,
) -> bool:
    """Le avisa a quien pidió editar que ya hay respuesta.

    Devuelve True/False, nunca levanta: quien llama no debe poder fallar por
    esto.
    """
    try:
        nombre = to_name or "Hola"

        if aprobada:
            titulo = "Ya puedes corregir tu respuesta"
            cuerpo = _p(
                f"<strong>{nombre}</strong>, tu solicitud para editar la respuesta "
                f"de <strong>{form_title}</strong> fue <strong>aprobada</strong>."
            )
        else:
            titulo = "Tu solicitud de edición no fue aprobada"
            cuerpo = _p(
                f"<strong>{nombre}</strong>, tu solicitud para editar la respuesta "
                f"de <strong>{form_title}</strong> fue <strong>rechazada</strong>."
            )

        filas = _info_row("Formato", form_title)
        filas += _info_row("Respuesta", f"#{response_id}")
        filas += _info_row(
            "Lo que pediste",
            "La respuesta completa" if todos else _lista_campos(campos or []),
        )
        if revisado_por:
            filas += _info_row("Lo atendió", revisado_por)
        cuerpo += _info_block("Detalle", filas)

        if mensaje_admin:
            cuerpo += _callout(
                f"Nota del administrador: <em>{mensaje_admin}</em>",
                "info" if aprobada else "warning",
            )

        if aprobada:
            # Lo que tiene que hacer ahora, y el límite, que es lo que más se
            # olvida: el permiso se gasta al guardar.
            cuerpo += _callout(
                "Entra a <strong>Consultar</strong>, abre esa respuesta y usa el botón "
                "de editar. Solo se guardará lo que cambies en los campos autorizados, "
                "y el permiso sirve <strong>una sola vez</strong>.",
                "success",
            )
            cuerpo += _btn(_APP_URL, "Ir a corregir")
        else:
            cuerpo += _p(
                f'<span style="font-size:13px;color:{_C["text_muted"]};">'
                f"Si sigues necesitando el cambio, puedes volver a pedirlo explicando "
                f"el motivo con más detalle.</span>"
            )

        html = _base_email_html(titulo, cuerpo)
        msg = _new_msg(f"{titulo} — {form_title}", to_email, to_name or "")
        msg.set_content(
            f"{nombre}, tu solicitud para editar la respuesta #{response_id} de "
            f"{form_title} fue {'aprobada' if aprobada else 'rechazada'}."
            + (f"\nNota: {mensaje_admin}" if mensaje_admin else "")
            + (
                "\n\nEntra a Consultar, abre esa respuesta y usa el botón de editar. "
                "El permiso sirve una sola vez."
                if aprobada else ""
            )
        )
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception:
        logger.warning(
            "Error enviando aviso de solicitud de edición",
            extra={"event": "edit_request_mail_fail"},
        )
        return False
