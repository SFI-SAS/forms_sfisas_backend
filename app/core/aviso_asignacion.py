"""
Aviso por correo cuando a alguien le asignan un formato.

Módulo NUEVO y aparte: no modifica `mail.py`, que es intocable. Sí **importa**
sus ayudantes —la plantilla HTML de la casa, la construcción del mensaje y el
envío SMTP— porque duplicar credenciales y maquetación sería peor: dos sitios
que mantener y dos que se desincronizan.

Regla de oro: **avisar nunca puede impedir asignar.** Si el correo falla —SMTP
caído, dirección mal escrita, red lenta— la asignación ya está hecha y guardada.
Por eso ninguna función de aquí lanza excepciones hacia arriba y por eso el
envío se despacha en segundo plano.
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

# Base para el enlace del correo. Sin ella el aviso llega igual, solo que sin
# botón para entrar directo.
URL_APP = (os.getenv("PUBLIC_APP_URL") or "").strip().rstrip("/")


def avisar_formato_asignado(
    *,
    nombre_usuario: str,
    correo_usuario: str,
    titulo_formato: str,
    descripcion_formato: str | None = None,
    categoria: str | None = None,
    asignado_por: str | None = None,
    form_design=None,
) -> bool:
    """Avisa a una persona que le asignaron un formato.

    Devuelve True si el correo salió. NUNCA lanza excepción: quien llama sigue
    su camino pase lo que pase.
    """
    if not correo_usuario or "@" not in correo_usuario:
        logger.info(
            "Asignación sin aviso: el usuario no tiene correo válido",
            extra={"event": "aviso_asignacion_sin_correo"},
        )
        return False

    try:
        filas = _info_row("Formato", titulo_formato)
        if categoria:
            filas += _info_row("Categoría", categoria)
        if descripcion_formato:
            filas += _info_row("Descripción", descripcion_formato)
        if asignado_por:
            filas += _info_row("Asignado por", asignado_por)

        cuerpo = (
            _p(f"Hola {nombre_usuario or ''},".strip())
            + _p("Te asignaron un formato en SafeMetrics. Ya puedes diligenciarlo.")
            + _info_block("Detalle de la asignación", filas)
            + resumen_estructura_html(form_design)
            + _callout(
                "Lo encontrarás en la sección <b>Diligenciar</b>, dentro de su categoría.",
                "info",
            )
        )
        if URL_APP:
            cuerpo += _btn(f"{URL_APP}/home/listforms", "Ir a diligenciar")

        html = _base_email_html("Nuevo formato asignado", cuerpo)

        msg = _new_msg(
            f"Te asignaron el formato: {titulo_formato}",
            correo_usuario,
            nombre_usuario or "",
        )
        # Versión en texto plano: hay clientes de correo que no muestran HTML,
        # y sin ella el mensaje llegaría en blanco.
        msg.set_content(
            f"Hola {nombre_usuario or ''},\n\n"
            f"Te asignaron el formato \"{titulo_formato}\" en SafeMetrics.\n"
            f"Ya puedes diligenciarlo desde la sección Diligenciar.\n"
        )
        msg.add_alternative(html, subtype="html")

        enviado = _send_msg(msg)
        if not enviado:
            logger.warning(
                "No se pudo enviar el aviso de asignación",
                extra={"event": "aviso_asignacion_fallido"},
            )
        return enviado

    except Exception:
        # Un aviso jamás tumba una asignación.
        logger.warning(
            "Fallo al componer el aviso de asignación",
            extra={"event": "aviso_asignacion_error"},
            exc_info=True,
        )
        return False

# ─────────────────────────────────────────────────────────────────────────────
# La estructura del formato, tal como se diseñó
#
# Se reconstruye el árbol completo: los layouts horizontales ponen sus campos
# lado a lado, los verticales los apilan, y los repetidores se dibujan como un
# bloque aparte. NO es una lista plana: el orden y la disposición son parte de
# lo que se quiere comunicar.
#
# Todo va en <table> con estilos en línea. Es la única maquetación que respetan
# los clientes de correo: Outlook no entiende flexbox ni grid, y una hoja de
# estilos aparte se descarta.
# ─────────────────────────────────────────────────────────────────────────────

# Nombres legibles. Un usuario no sabe qué es un "mathoperations".
_NOMBRE_TIPO = {
    "input": "Texto", "textarea": "Texto largo", "number": "Número",
    "select": "Lista", "radio": "Opción única", "checkbox": "Casillas",
    "date": "Fecha", "time": "Hora", "datetime": "Fecha y hora",
    "file": "Archivo", "image": "Imagen", "location": "Ubicación",
    "firm": "Firma", "regisfacial": "Registro facial",
    "table": "Tabla", "mathoperations": "Cálculo",
}

_HORIZONTALES = {"horizontalLayout", "simpleHorizontalLayout"}
_VERTICALES = {"verticalLayout", "simpleVerticalLayout"}
_DECORATIVOS = {"label", "helpText", "divider", "image", "button", "headerTable"}

# Tope de profundidad: un diseño corrupto con ciclos colgaría el envío.
_MAX_PROFUNDIDAD = 8


def _escapar(texto) -> str:
    """Un label puede traer < o &; sin escapar romperían el HTML del correo."""
    return (
        str(texto or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _caja_campo(item: dict) -> str:
    props = item.get("props") or {}
    etiqueta = _escapar(props.get("label") or "(sin etiqueta)")
    clase = _NOMBRE_TIPO.get(item.get("type"), "Campo")
    obligatorio = (
        ' <span style="color:#dc2626;font-weight:bold;">*</span>'
        if props.get("required") else ""
    )
    return (
        '<div style="border:1px solid #e2e8f0;border-radius:5px;padding:8px 10px;'
        'background:#ffffff;margin:4px 0;">'
        f'<div style="font-size:13px;color:#1e293b;font-weight:600;">{etiqueta}{obligatorio}</div>'
        f'<div style="font-size:11px;color:#94a3b8;margin-top:2px;">{clase}</div>'
        '</div>'
    )


def _decorativo(item: dict) -> str:
    tipo = item.get("type")
    props = item.get("props") or {}
    texto = _escapar(props.get("label") or props.get("text") or "")

    if tipo == "divider":
        return '<hr style="border:none;border-top:1px solid #e2e8f0;margin:10px 0;">'
    if tipo == "label" and texto:
        return f'<div style="font-size:14px;font-weight:bold;color:#334155;margin:10px 0 4px;">{texto}</div>'
    if tipo == "helpText" and texto:
        return f'<div style="font-size:12px;color:#64748b;font-style:italic;margin:4px 0;">{texto}</div>'
    if tipo == "image":
        return '<div style="font-size:12px;color:#94a3b8;margin:4px 0;">[imagen]</div>'
    return ""


def _render(items, profundidad: int = 0) -> str:
    if profundidad > _MAX_PROFUNDIDAD or not isinstance(items, list):
        return ""

    salida = ""
    for item in items:
        if not isinstance(item, dict):
            continue
        tipo = item.get("type")
        props = item.get("props") or {}
        hijos = item.get("children") if isinstance(item.get("children"), list) else []

        # ── Repetidor: bloque propio, porque cambia cómo se llena ───────────
        if tipo == "repeater":
            titulo = _escapar(props.get("label") or "Sección repetible")
            salida += (
                '<table style="width:100%;border-collapse:collapse;margin:10px 0;'
                'border:1px solid #99f6e4;border-radius:6px;background:#f0fdfa;">'
                '<tr><td style="padding:8px 10px;">'
                f'<div style="font-size:12px;font-weight:bold;color:#0F8594;'
                f'text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px;">'
                f'{titulo} · se repite por filas</div>'
                f'{_render(hijos, profundidad + 1)}'
                '</td></tr></table>'
            )
            continue

        # ── Layout horizontal: los campos van EN LA MISMA FILA ──────────────
        if tipo in _HORIZONTALES and hijos:
            celdas = ""
            ancho = max(1, len(hijos))
            for h in hijos:
                celdas += (
                    f'<td style="vertical-align:top;padding:0 4px;width:{100 // ancho}%;">'
                    f'{_render([h], profundidad + 1)}</td>'
                )
            salida += (
                '<table style="width:100%;border-collapse:collapse;margin:2px 0;">'
                f'<tr>{celdas}</tr></table>'
            )
            continue

        # ── Layout vertical: apilado, que es el flujo normal ────────────────
        if tipo in _VERTICALES and hijos:
            salida += _render(hijos, profundidad + 1)
            continue

        if tipo in _DECORATIVOS:
            salida += _decorativo(item)
            if hijos:
                salida += _render(hijos, profundidad + 1)
            continue

        if tipo:
            salida += _caja_campo(item)

        if hijos:
            salida += _render(hijos, profundidad + 1)

    return salida


def _contar_campos(items, profundidad: int = 0) -> int:
    if profundidad > _MAX_PROFUNDIDAD or not isinstance(items, list):
        return 0
    n = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        tipo = item.get("type")
        if tipo and tipo not in _DECORATIVOS and tipo not in _HORIZONTALES \
                and tipo not in _VERTICALES and tipo != "repeater":
            n += 1
        hijos = item.get("children")
        if isinstance(hijos, list):
            n += _contar_campos(hijos, profundidad + 1)
    return n


def resumen_estructura_html(form_design) -> str:
    """La estructura del formato tal como se diseñó.

    Cadena vacía si no hay nada que mostrar: el correo sale igual sin ella.
    """
    import json as _json

    if isinstance(form_design, str):
        try:
            form_design = _json.loads(form_design)
        except (ValueError, TypeError):
            return ""
    if not isinstance(form_design, list) or not form_design:
        return ""

    try:
        cuerpo = _render(form_design)
        total = _contar_campos(form_design)
    except Exception:
        # Un diseño raro no puede impedir que salga el aviso.
        logger.warning(
            "No se pudo dibujar la estructura en el correo",
            extra={"event": "aviso_estructura_render"},
        )
        return ""

    if not cuerpo.strip():
        return ""

    return (
        '<div style="margin:18px 0;">'
        '<div style="font-size:13px;font-weight:bold;color:#334155;margin-bottom:8px;">'
        f'Así quedó el formato · {total} campo(s)</div>'
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;'
        f'padding:10px;">{cuerpo}</div>'
        '<div style="font-size:11px;color:#94a3b8;margin-top:5px;">'
        '<span style="color:#dc2626;">*</span> campo obligatorio</div>'
        '</div>'
    )
