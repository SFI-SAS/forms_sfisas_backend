"""Condiciones de visibilidad (layouts y campos).

Espejo en el servidor de `forms_sfi/src/lib/fieldConditions.ts`.

Un elemento condicionado guarda tres props:
    hidden    → True = "este elemento es condicional"
    condicion → "api-57" | "manual-53"  (el número es el id de la pregunta)
    valor     → "Contado, Credito"      (valores separados por coma que lo muestran)

El cliente evalúa esto contra las respuestas que tiene a la vista. El problema
aparece con los aprobadores: si la pregunta que condiciona es `hidden` para uno
de ellos, el servidor no se la manda, el cliente no encuentra el valor y el campo
condicionado desaparece aunque SÍ venga diligenciado. Por eso el servidor evalúa
la condición aquí —con TODAS las respuestas— y le manda el veredicto ya resuelto
(ver `field_access.condition_visibility_for_approver`). Va el veredicto y no el
valor a propósito: `hidden` significa que ese dato no sale del servidor.

La comparación replica la del renderer de solo lectura (`FormResponseRenderer`):
se compara el valor completo, no cada ítem de una lista separada por comas. Es
una limitación conocida de las casillas de verificación, pero mantenerla es lo
que garantiza que el veredicto del servidor y el del cliente nunca discrepen.
"""

from typing import Any, Callable, Iterable, List, Optional


def condition_question_id(props: Optional[dict]) -> Optional[int]:
    """Id de la pregunta que condiciona, o None si no está bien configurado."""
    if not props:
        return None
    raw = props.get("condicion")
    if not raw:
        return None
    parts = str(raw).split("-")
    if len(parts) < 2:
        return None
    try:
        value = int(parts[1])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def is_visible_by_condition(
    props: Optional[dict], get_value: Callable[[int], Any]
) -> bool:
    """¿Debe verse este elemento?

    `get_value` devuelve el valor actual de la pregunta que condiciona; quien
    llama decide de dónde sale (de la fila, del formato, de lo ya guardado).
    """
    if not props or not props.get("hidden"):
        return True

    # Marcado como condicional pero sin configurar: se oculta, igual que hace el
    # cliente con los layouts mal configurados.
    if not props.get("condicion") or not props.get("valor"):
        return False

    question_id = condition_question_id(props)
    if not question_id:
        return False

    allowed = [v.strip() for v in str(props["valor"]).split(",") if v.strip()]
    if not allowed:
        return False

    raw = get_value(question_id)

    # Las casillas de verificación pueden llegar como lista: basta con que una
    # de las marcadas esté entre las permitidas.
    if isinstance(raw, (list, tuple, set)):
        return any(str(v) in allowed for v in raw)

    if raw is None or raw == "":
        return False

    return str(raw) in allowed


def collect_conditional_elements(form_design: Any) -> List[dict]:
    """Elementos condicionados del diseño, con el repetidor que los contiene.

    Devuelve `[{"element_id", "repeater_id", "question_id", "props"}]` solo de
    los que tienen la condición bien configurada; el resto no necesita veredicto
    (o se oculta siempre, que el cliente ya resuelve sin datos).
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
                question_id = condition_question_id(props)
                if question_id and props.get("valor"):
                    found.append({
                        "element_id": item_id,
                        "repeater_id": repeater_id,
                        "question_id": question_id,
                        "props": props,
                    })

            children = item.get("children")
            if isinstance(children, list) and children:
                # Un repetidor abre contexto; un layout dentro de un repetidor
                # conserva el del repetidor que lo contiene.
                walk(children, item_id if is_repeater else repeater_id)

    walk(form_design, None)
    return found
