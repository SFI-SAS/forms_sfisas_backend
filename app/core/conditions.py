"""Condiciones de visibilidad (layouts y campos).

Espejo en el servidor de `forms_sfi/src/lib/fieldConditions.ts`.

Un elemento condicionado guarda:
    hidden        → True = "este elemento es condicional"
    condiciones   → [{"condicion": "api-57", "valor": "Contado, Credito"}, ...]
    condicionModo → "todas" (Y) | "alguna" (O). Por defecto "todas".

FORMATO ANTERIOR (una sola condición), que sigue funcionando:
    condicion → "api-57" | "manual-53"
    valor     → "Contado, Credito"

El cliente evalúa esto contra las respuestas que tiene a la vista. El problema
aparece con los aprobadores: si una pregunta que condiciona es `hidden` para uno
de ellos, el servidor no se la manda, el cliente no encuentra el valor y el campo
condicionado desaparece aunque SÍ venga diligenciado. Por eso el servidor evalúa
la condición aquí —con TODAS las respuestas— y le manda el veredicto ya resuelto
(ver `field_access.condition_visibility_for_approver`). Va el veredicto y no el
valor: `hidden` sigue significando que ese dato no sale.

La comparación replica la del renderer de solo lectura (`FormResponseRenderer`):
se compara el valor completo, no cada ítem de una lista separada por comas. Es
una limitación conocida de las casillas de verificación, pero mantenerla es lo
que garantiza que el veredicto del servidor y el del cliente nunca discrepen.
"""

from typing import Any, Callable, Iterable, List, Optional


def condition_question_id(condicion: Any) -> Optional[int]:
    """Id de la pregunta de una condición, o None si no está bien configurada."""
    if not condicion:
        return None
    parts = str(condicion).split("-")
    if len(parts) < 2:
        return None
    try:
        value = int(parts[1])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def condition_list(props: Optional[dict]) -> List[dict]:
    """Condiciones del elemento, normalizadas y sin las mal configuradas.

    Vacío significa "ocúltalo": o no es condicional, o está marcado como tal
    pero sin nada que evaluar.
    """
    if not props or not props.get("hidden"):
        return []

    crudas = props.get("condiciones")
    if not (isinstance(crudas, list) and crudas):
        # Formato anterior: una sola condición suelta en las props.
        crudas = (
            [{"condicion": props.get("condicion"), "valor": props.get("valor") or ""}]
            if props.get("condicion")
            else []
        )

    return [
        c for c in crudas
        if isinstance(c, dict)
        and condition_question_id(c.get("condicion")) is not None
        and str(c.get("valor") or "").strip() != ""
    ]


def condition_question_ids(props: Optional[dict]) -> List[int]:
    """Ids de todas las preguntas que condicionan este elemento (sin repetir)."""
    vistos = []
    for c in condition_list(props):
        qid = condition_question_id(c.get("condicion"))
        if qid is not None and qid not in vistos:
            vistos.append(qid)
    return vistos


def condition_mode(props: Optional[dict]) -> str:
    return "alguna" if (props or {}).get("condicionModo") == "alguna" else "todas"


def matches_condition(condicion: dict, raw: Any) -> bool:
    """¿Se cumple UNA condición con el valor dado?"""
    allowed = [v.strip() for v in str(condicion.get("valor") or "").split(",") if v.strip()]
    if not allowed:
        return False

    # Las casillas de verificación pueden llegar como lista: basta con que una
    # de las marcadas esté entre las permitidas.
    if isinstance(raw, (list, tuple, set)):
        return any(str(v) in allowed for v in raw)

    if raw is None or raw == "":
        return False

    return str(raw) in allowed


def is_visible_by_condition(
    props: Optional[dict], get_value: Callable[[int], Any]
) -> bool:
    """¿Debe verse este elemento?

    `get_value` devuelve el valor actual de una pregunta; quien llama decide de
    dónde sale (de la fila, del formato, de lo ya guardado).
    """
    if not props or not props.get("hidden"):
        return True

    condiciones = condition_list(props)
    if not condiciones:
        return False

    resultados = []
    for c in condiciones:
        qid = condition_question_id(c.get("condicion"))
        resultados.append(False if qid is None else matches_condition(c, get_value(qid)))

    if condition_mode(props) == "alguna":
        return any(resultados)
    return all(resultados)


def collect_conditional_elements(form_design: Any) -> List[dict]:
    """Elementos condicionados del diseño, con el repetidor que los contiene.

    Devuelve `[{"element_id", "repeater_id", "question_ids", "props"}]` solo de
    los que tienen al menos una condición bien configurada; el resto no necesita
    veredicto (o se oculta siempre, que el cliente ya resuelve sin datos).
    """
    import json

    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except (ValueError, TypeError):
            return []

    if not isinstance(form_design, list):
        return []

    found: List[dict] = []

    def walk(items: Iterable[Any], repeater_id: Optional[str]):
        for item in items:
            if not isinstance(item, dict):
                continue

            props = item.get("props") or {}
            item_id = str(item.get("id")) if item.get("id") is not None else None
            is_repeater = item.get("type") == "repeater"

            if item_id and props.get("hidden"):
                question_ids = condition_question_ids(props)
                if question_ids:
                    found.append({
                        "element_id": item_id,
                        "repeater_id": repeater_id,
                        "question_ids": question_ids,
                        "props": props,
                    })

            children = item.get("children")
            if isinstance(children, list) and children:
                # Un repetidor abre contexto; un layout dentro de un repetidor
                # conserva el del repetidor que lo contiene.
                walk(children, item_id if is_repeater else repeater_id)

    walk(form_design, None)
    return found
