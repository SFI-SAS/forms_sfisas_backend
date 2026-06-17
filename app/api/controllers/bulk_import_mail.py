"""
Correo resumen de importación masiva por Excel.

Módulo ADITIVO: reutiliza los helpers de plantilla de `mail.py` SIN modificarlo
(intocable #10). Solo importa los helpers; no cambia ninguna plantilla, la
config SMTP ni las funciones de envío existentes.

A diferencia del diligenciamiento normal, la importación masiva NO envía un
correo por registro (eso satura al proveedor SMTP). En su lugar, al terminar el
job se envía UN solo correo al usuario que hizo la importación, con el total de
registros procesados y cuántos quedaron OK / fallidos.
"""

import logging

from app.api.controllers.mail import (
    _APP_URL,
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


def send_bulk_import_summary_email(
    email: str,
    name: str,
    form_title: str,
    total: int,
    ok: int,
    failed: int,
) -> bool:
    """Envía al usuario el resumen de su importación masiva por Excel."""
    try:
        body = _p(
            f'Estimado/a <strong>{name}</strong>, su importación masiva de '
            f'registros para el formato <strong>{form_title}</strong> ha '
            f'finalizado.'
        )
        body += _info_block(
            "Resumen de la importación",
            _info_row("Formato", form_title)
            + _info_row("Registros en el archivo", str(total))
            + _info_row("Procesados correctamente", str(ok))
            + _info_row("Con errores", str(failed)),
        )
        if failed > 0:
            body += _callout(
                f'{failed} registro(s) no se pudieron procesar. Revise el '
                f'detalle de la importación en SafeMetrics para corregirlos y '
                f'volver a cargarlos.',
                'warning',
            )
        else:
            body += _callout(
                'Todos los registros se procesaron correctamente.',
                'info',
            )
        body += _btn(_APP_URL, "Ir a SafeMetrics")

        html = _base_email_html("Importación masiva finalizada", body)
        msg = _new_msg(
            "Importación masiva finalizada — SafeMetrics", email, name
        )
        msg.set_content(
            f"Hola {name}. Su importación masiva para el formato "
            f"'{form_title}' finalizó.\n"
            f"Registros en el archivo: {total}\n"
            f"Procesados correctamente: {ok}\n"
            f"Con errores: {failed}\n"
        )
        msg.add_alternative(html, subtype="html")
        return _send_msg(msg)
    except Exception:
        logger.warning(
            "Error enviando correo resumen de importación masiva",
            extra={"event": "bulk_import_summary_mail_fail"},
        )
        return False
