"""Acceso a campos por aprobador.

Espejo en el servidor de `forms_sfi/src/lib/approverFieldAccess.ts`. La config
la escribe la pantalla "Administrar aprobadores" → "Configurar campos" y vive en
`form_approval_field_access` (una fila por formato + usuario aprobador).

Aquí está la parte que MANDA: el cliente oculta campos por cosmética, pero lo
que un aprobador ve y puede escribir se decide en este módulo.

Modos por campo:
    hidden → no lo ve; ni siquiera se le envía la answer
    read   → lo ve en solo lectura (DEFAULT: comportamiento de siempre)
    edit   → lo llena él; queda oculto para quien diligencia el formato

Además cada repetidor puede filtrarse por aprobador: "solo le llegan las filas
donde Tipo de pago = Contado".
"""

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import json
import logging

logger = logging.getLogger(__name__)

HIDDEN = "hidden"
READ = "read"
EDIT = "edit"
DEFAULT_MODE = READ
VALID_MODES = (HIDDEN, READ, EDIT)

# Tipos del diseño que son decoración: no se responden.
NON_FIELD_TYPES = {
    "label", "button", "helpText", "divider", "image", "headerTable",
    "verticalLayout", "horizontalLayout", "repeater",
}


# ─── Carga de la config ──────────────────────────────────────────────────────

def _as_dict(raw: Any) -> dict:
    """AutoJSON ya deserializa, pero una fila escrita a mano puede traer str."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def load_field_access(db, form_id: int) -> Dict[int, dict]:
    """Devuelve {user_id: config} para todos los aprobadores del formato.

    Un aprobador sin fila no aparece: se comporta con el default (`read`).

    Deja fuera las configs de participantes DINÁMICOS (las del recibidor que se
    elige en un campo): esas no son de un usuario, van por `dynamic_key` y se
    piden con `load_dynamic_field_access`.
    """
    from app.models import FormApprovalFieldAccess

    rows = (
        db.query(FormApprovalFieldAccess)
        .filter(
            FormApprovalFieldAccess.form_id == form_id,
            FormApprovalFieldAccess.user_id.isnot(None),
        )
        .all()
    )
    return {row.user_id: _as_dict(row.config) for row in rows}


def load_dynamic_field_access(db, form_id: int) -> Dict[str, dict]:
    """Devuelve {element_id: config} de los participantes dinámicos.

    Son los "recibidores aleatorios": no hay un usuario al que colgar la config
    porque se elige al diligenciar, así que va contra el campo que lo define.
    """
    from app.models import FormApprovalFieldAccess

    rows = (
        db.query(FormApprovalFieldAccess)
        .filter(
            FormApprovalFieldAccess.form_id == form_id,
            FormApprovalFieldAccess.dynamic_key.isnot(None),
        )
        .all()
    )
    return {row.dynamic_key: _as_dict(row.config) for row in rows}


def config_for_participant(db, form_id: int, response_id: int, user_id: int) -> Optional[dict]:
    """Config de campos que le toca a un participante EN ESTA respuesta.

    Casi siempre es la suya, la de (formato, usuario). Pero si entró a la cadena
    porque alguien lo escogió en un campo selector, no tiene una propia: le
    corresponde la del participante dinámico, que va contra ese campo. Sin esto
    el recibidor elegido vería todo en solo lectura y nunca sus campos.
    """
    from app.models import ResponseApproval

    participacion = (
        db.query(ResponseApproval)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.user_id == user_id,
        )
        .first()
    )
    origen = getattr(participacion, "dynamic_source_element_id", None) if participacion else None
    if origen:
        return load_dynamic_field_access(db, form_id).get(origen)

    return load_field_access(db, form_id).get(user_id)


def get_mode(config: Optional[dict], element_id: str) -> str:
    if not config:
        return DEFAULT_MODE
    for rule in config.get("rules") or []:
        if isinstance(rule, dict) and rule.get("element_id") == element_id:
            mode = rule.get("mode")
            if mode in VALID_MODES:
                return mode
    return DEFAULT_MODE


def elements_with_mode(config: Optional[dict], mode: str) -> Set[str]:
    if not config:
        return set()
    return {
        rule.get("element_id")
        for rule in (config.get("rules") or [])
        if isinstance(rule, dict) and rule.get("mode") == mode and rule.get("element_id")
    }


def row_filters(config: Optional[dict]) -> List[dict]:
    """Filtros con al menos un valor; los vacíos no filtran nada."""
    if not config:
        return []
    return [
        f for f in (config.get("row_filters") or [])
        if isinstance(f, dict) and f.get("repeater_id") and (f.get("values") or [])
    ]


def elements_visible_to_filler(form_design: Any) -> Set[str]:
    """Campos de aprobador que SÍ puede ver quien diligenció, al consultar.

    Se marca campo por campo en el diseñador (`props.verDiligenciador`), al
    vincular las preguntas al formato. Por defecto un campo que llena un
    aprobador no se le muestra a quien diligenció: solo ve lo suyo.

    OJO: esto es para VER la respuesta ya enviada. Al diligenciar siguen sin
    aparecerle nunca — no son suyos.
    """
    import json

    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except (ValueError, TypeError):
            return set()

    if not isinstance(form_design, list):
        return set()

    visibles: Set[str] = set()

    def walk(items: Iterable[Any]):
        for item in items:
            if not isinstance(item, dict):
                continue
            props = item.get("props") or {}
            if item.get("id") is not None and props.get("verDiligenciador"):
                visibles.add(str(item["id"]))
            children = item.get("children")
            if isinstance(children, list) and children:
                walk(children)

    walk(form_design)
    return visibles


def row_filter_mode(config: Optional[dict], repeater_id: str) -> str:
    """¿Cómo se combinan los filtros de ese repetidor?

    'todas'  → la fila tiene que cumplirlos TODOS (default)
    'alguna' → basta con que cumpla uno
    """
    modos = (config or {}).get("row_filter_modes") or {}
    return "alguna" if modos.get(repeater_id) == "alguna" else "todas"


def filters_by_repeater(config: Optional[dict]) -> Dict[str, List[dict]]:
    """Los filtros agrupados por repetidor. Puede haber VARIOS por repetidor."""
    agrupados: Dict[str, List[dict]] = {}
    for f in row_filters(config):
        agrupados.setdefault(f["repeater_id"], []).append(f)
    return agrupados


def owned_element_ids(configs: Dict[int, dict]) -> Set[str]:
    """Elementos que llena ALGÚN aprobador → no los ve quien diligencia."""
    owned: Set[str] = set()
    for config in configs.values():
        owned |= elements_with_mode(config, EDIT)
    return owned


def owner_of_element(configs: Dict[int, dict], element_id: str) -> Optional[int]:
    """user_id del aprobador que llena ese campo, o None si no es de nadie."""
    for user_id, config in configs.items():
        if get_mode(config, element_id) == EDIT:
            return user_id
    return None


# ─── Lectura del form_design ─────────────────────────────────────────────────

class DesignInfo:
    """Índice del diseño: campos, repetidores y a qué repetidor pertenece cada
    campo. Se calcula una vez por formato y se reusa en los filtros."""

    __slots__ = ("fields", "repeaters", "repeater_of_element",
                 "elements_of_repeater", "questions_of_repeater",
                 "question_of_element")

    def __init__(self):
        self.fields: List[dict] = []
        self.repeaters: List[dict] = []
        # element_id del campo → element_id del repetidor que lo contiene
        self.repeater_of_element: Dict[str, str] = {}
        # element_id del repetidor → set de element_id de sus campos
        self.elements_of_repeater: Dict[str, Set[str]] = {}
        # element_id del repetidor → set de question_id de sus campos
        # (fallback para answers viejas sin form_design_element_id)
        self.questions_of_repeater: Dict[str, Set[int]] = {}
        self.question_of_element: Dict[str, Optional[int]] = {}


def collect_design(form_design: Any) -> DesignInfo:
    info = DesignInfo()

    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except (ValueError, TypeError):
            form_design = []

    if not isinstance(form_design, list):
        return info

    def walk(items: Iterable[Any], repeater_id: Optional[str]):
        for item in items:
            if not isinstance(item, dict):
                continue

            props = item.get("props") or {}
            item_id = str(item.get("id")) if item.get("id") is not None else None
            is_repeater = item.get("type") == "repeater"

            if is_repeater and item_id:
                info.repeaters.append({"id": item_id, "label": props.get("label") or "Repetidor"})
                info.elements_of_repeater.setdefault(item_id, set())
                info.questions_of_repeater.setdefault(item_id, set())
            elif item_id and item.get("type") not in NON_FIELD_TYPES and item.get("id_question"):
                question_id = item.get("id_question")
                info.fields.append({
                    "element_id": item_id,
                    "question_id": question_id,
                    "label": props.get("label") or f"Campo {question_id}",
                    "type": item.get("type"),
                    "repeater_id": repeater_id,
                })
                info.question_of_element[item_id] = question_id
                if repeater_id:
                    info.repeater_of_element[item_id] = repeater_id
                    info.elements_of_repeater.setdefault(repeater_id, set()).add(item_id)
                    if isinstance(question_id, int):
                        info.questions_of_repeater.setdefault(repeater_id, set()).add(question_id)

            children = item.get("children")
            if isinstance(children, list) and children:
                # Un repetidor abre contexto; un layout dentro de un repetidor
                # conserva el del repetidor que lo contiene.
                walk(children, item_id if is_repeater else repeater_id)

    walk(form_design, None)
    return info


def strip_elements(form_design: Any, element_ids: Set[str]) -> list:
    """Devuelve una copia del diseño sin los elementos indicados.

    Se recorta el árbol completo: quitar un elemento se lleva sus hijos, que es
    lo correcto (si un layout entero es del aprobador, no debe quedar el marco).
    """
    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except (ValueError, TypeError):
            return []

    if not isinstance(form_design, list):
        return []

    if not element_ids:
        return form_design

    def prune(items: List[Any]) -> list:
        result = []
        for item in items:
            if not isinstance(item, dict):
                result.append(item)
                continue
            item_id = str(item.get("id")) if item.get("id") is not None else None
            if item_id and item_id in element_ids:
                continue
            copy = dict(item)
            children = copy.get("children")
            if isinstance(children, list):
                copy["children"] = prune(children)
            result.append(copy)
        return result

    return prune(form_design)


# ─── Filtrado de answers ─────────────────────────────────────────────────────

def _get(answer: Any, key: str, default=None):
    """Lee indistintamente de un dict serializado o de un ORM Answer."""
    if isinstance(answer, dict):
        return answer.get(key, default)
    return getattr(answer, key, default)


def row_key(repeated_id: Any, row_index: Any) -> Tuple:
    """Identidad de una fila del repetidor.

    Va el PAR completo a propósito. Los dos campos significan cosas distintas
    según quién escribió la answer:
      · el web manda `repeated_id` = id del REPETIDOR (igual para todas las
        filas) y `repeater_row_index` = la fila;
      · el móvil manda un `repeated_id` propio por fila.
    Quedarse solo con `repeated_id`, como se hacía antes, metía todas las filas
    del web en una sola clave: bastaba con que una fila pasara el filtro para
    que pasaran todas.
    """
    return ("row", str(repeated_id) if repeated_id else "", row_index)


def build_row_keys(
    answers: Iterable[Any], repeater_id: str, design: DesignInfo
) -> Dict[int, Tuple]:
    """Clave de fila de cada answer de ese repetidor, por identidad de objeto.

    Si las answers no traen NI repeated_id NI índice —lo que pasa con todo lo
    diligenciado desde el web, porque `/save-answers/` no persiste esos campos—
    la fila se reconstruye por posición: dentro de cada columna, la n-ésima
    answer pertenece a la n-ésima fila. Es exactamente lo que hace el renderer
    para pintar la tabla, así que las filas coinciden con lo que se ve.
    """
    members = [a for a in answers if _belongs_to_repeater(a, repeater_id, design)]
    if not members:
        return {}

    def tiene_identidad(answer: Any) -> bool:
        return bool(_get(answer, "repeated_id")) or _get(answer, "repeater_row_index") is not None

    # Reconstrucción posicional (espejo de la "Estrategia 2" del renderer), solo
    # sobre las que no traen identidad: las que sí la traen no deben correr las
    # posiciones de las demás.
    por_columna: Dict[str, List[Any]] = {}
    for answer in members:
        if tiene_identidad(answer):
            continue
        element_id = _get(answer, "form_design_element_id")
        columna = element_id or f"q{_get(answer, 'question_id')}"
        por_columna.setdefault(columna, []).append(answer)

    posicion: Dict[int, int] = {}
    for columna in por_columna.values():
        columna.sort(key=lambda a: _get(a, "id") or _get(a, "answer_id") or 0)
        for indice, answer in enumerate(columna):
            posicion[id(answer)] = indice

    keys: Dict[int, Tuple] = {}
    for answer in members:
        if tiene_identidad(answer):
            keys[id(answer)] = row_key(
                _get(answer, "repeated_id"), _get(answer, "repeater_row_index")
            )
        else:
            keys[id(answer)] = row_key(None, posicion[id(answer)])
    return keys


def _belongs_to_repeater(answer: Any, repeater_id: str, design: DesignInfo) -> bool:
    element_id = _get(answer, "form_design_element_id")
    if element_id:
        return element_id in design.elements_of_repeater.get(repeater_id, set())
    # Fallback para answers sin element_id: por pregunta.
    question_id = _get(answer, "question_id")
    return question_id in design.questions_of_repeater.get(repeater_id, set())


def _answer_matches_filter_field(answer: Any, row_filter: dict) -> bool:
    element_id = _get(answer, "form_design_element_id")
    if element_id and row_filter.get("element_id"):
        return element_id == row_filter["element_id"]
    question_id = _get(answer, "question_id")
    return question_id is not None and question_id == row_filter.get("question_id")


def passing_row_keys(
    answers: Iterable[Any], row_filter: dict, design: DesignInfo
) -> Set[Tuple]:
    """Filas del repetidor que pasan el filtro del aprobador."""
    answers = list(answers)
    repeater_id = row_filter["repeater_id"]
    keys = build_row_keys(answers, repeater_id, design)
    wanted = {str(v) for v in (row_filter.get("values") or [])}
    passing: Set[Tuple] = set()

    for answer in answers:
        key = keys.get(id(answer))
        if key is None:
            continue
        if not _answer_matches_filter_field(answer, row_filter):
            continue
        value = _get(answer, "answer_text")
        if value is not None and str(value) in wanted:
            passing.add(key)

    return passing


def passing_rows_by_repeater(
    answers: Iterable[Any], config: Optional[dict], design: DesignInfo
) -> Dict[str, Set[Tuple]]:
    """Filas que le llegan al aprobador, por repetidor.

    Un repetidor puede tener VARIOS filtros ("solo Contado" + "solo Bogotá").
    Se combinan según el modo del repetidor: `todas` deja las filas que cumplen
    todos (intersección) y `alguna` las que cumplen al menos uno (unión).

    Es el único sitio donde se decide esto: lo usan el recorte de answers, el
    auto-salto y la validación al guardar los campos del aprobador.
    """
    answers = list(answers)
    resultado: Dict[str, Set[Tuple]] = {}

    for repeater_id, filtros in filters_by_repeater(config).items():
        conjuntos = [passing_row_keys(answers, f, design) for f in filtros]
        if not conjuntos:
            continue
        if row_filter_mode(config, repeater_id) == "alguna":
            pasan: Set[Tuple] = set()
            for c in conjuntos:
                pasan |= c
        else:
            pasan = set(conjuntos[0])
            for c in conjuntos[1:]:
                pasan &= c
        resultado[repeater_id] = pasan

    return resultado


def filter_answers_for_approver(
    answers: List[Any], config: Optional[dict], design: DesignInfo
) -> List[Any]:
    """Quita lo que este aprobador no debe recibir: campos `hidden` y filas del
    repetidor que no pasan su filtro."""
    if not config:
        return answers

    hidden = elements_with_mode(config, HIDDEN)
    filters = row_filters(config)

    if not hidden and not filters:
        return answers

    # Por repetidor filtrado: qué filas sobreviven y a qué fila va cada answer.
    allowed_rows = passing_rows_by_repeater(answers, config, design)
    row_keys: Dict[str, Dict[int, Tuple]] = {
        repeater_id: build_row_keys(answers, repeater_id, design)
        for repeater_id in allowed_rows
    }

    result = []
    for answer in answers:
        element_id = _get(answer, "form_design_element_id")
        if element_id and element_id in hidden:
            continue

        drop = False
        for repeater_id, keys in allowed_rows.items():
            key = row_keys[repeater_id].get(id(answer))
            if key is not None:
                if key not in keys:
                    drop = True
                break
        if drop:
            continue

        result.append(answer)

    return result


def approver_has_work(
    answers: List[Any], config: Optional[dict], design: DesignInfo
) -> bool:
    """¿Le queda algo por hacer a este aprobador en esta respuesta?

    Si su filtro de filas no deja ninguna fila y tampoco tiene campos `edit`
    fuera del repetidor filtrado, no tiene nada que llenar ni que revisar: el
    flujo lo salta.
    """
    filters = row_filters(config)
    if not filters:
        return True

    editable = elements_with_mode(config, EDIT)

    # Campos que llena fuera de los repetidores filtrados → siempre tiene trabajo.
    filtered_repeaters = {f["repeater_id"] for f in filters}
    for element_id in editable:
        repeater_id = design.repeater_of_element.get(element_id)
        if repeater_id is None or repeater_id not in filtered_repeaters:
            return True

    # Si algún repetidor filtrado le deja filas, tiene trabajo.
    for pasan in passing_rows_by_repeater(answers, config, design).values():
        if pasan:
            return True

    return False


# ─── Condiciones que el aprobador no puede evaluar ───────────────────────────

def _question_of(answer: Any, design: DesignInfo) -> Optional[int]:
    element_id = _get(answer, "form_design_element_id")
    if element_id and element_id in design.question_of_element:
        return design.question_of_element[element_id]
    question_id = _get(answer, "question_id")
    return question_id if isinstance(question_id, int) else None


def _row_token(answer: Any, key: Tuple) -> str:
    """Cómo identifica el CLIENTE esa fila, para poder mandarle el veredicto.

    El renderer usa el `repeated_id` cuando las answers lo traen, y `pos-N`
    cuando no (su "Estrategia 2", la reconstrucción por posición). Aquí se
    replica esa misma etiqueta.
    """
    repeated_id = _get(answer, "repeated_id")
    if repeated_id:
        return str(repeated_id)
    return f"pos-{key[2]}"


def _index_condition_values(
    answers: Iterable[Any], design: DesignInfo
) -> Tuple[Dict[int, Any], Dict[Tuple[Tuple, int], Any]]:
    """Valores utilizables como condición: los sueltos y los de cada fila.

    Devuelve `({question_id: valor}, {(clave_de_fila, question_id): valor})`. Si
    la misma pregunta aparece varias veces fuera del repetidor gana la última,
    que es lo que hace el cliente al armar su `answersMap`.
    """
    answers = list(answers)
    loose: Dict[int, Any] = {}
    rows: Dict[Tuple[Tuple, int], Any] = {}

    # Clave de fila por repetidor (con reconstrucción posicional si hace falta).
    keys_by_repeater: Dict[str, Dict[int, Tuple]] = {
        repeater["id"]: build_row_keys(answers, repeater["id"], design)
        for repeater in design.repeaters
    }

    for answer in answers:
        question_id = _question_of(answer, design)
        if question_id is None:
            continue

        element_id = _get(answer, "form_design_element_id")
        repeater_id = design.repeater_of_element.get(element_id) if element_id else None

        if repeater_id:
            key = keys_by_repeater.get(repeater_id, {}).get(id(answer))
            if key is not None:
                rows[(key, question_id)] = _get(answer, "answer_text")
        else:
            loose[question_id] = _get(answer, "answer_text")

    return loose, rows


def _rows_of_repeater(
    answers: Iterable[Any], repeater_id: str, design: DesignInfo
) -> List[Tuple[Tuple, str]]:
    """Filas de ese repetidor, en orden de aparición.

    Devuelve `[(clave_de_fila, etiqueta_del_cliente)]`: la clave sirve para
    buscar valores aquí dentro, la etiqueta es con la que el cliente pedirá el
    veredicto.
    """
    answers = list(answers)
    keys = build_row_keys(answers, repeater_id, design)
    seen: List[Tuple[Tuple, str]] = []
    vistas: Set[Tuple] = set()

    for answer in answers:
        key = keys.get(id(answer))
        if key is None or key in vistas:
            continue
        vistas.add(key)
        seen.append((key, _row_token(answer, key)))

    return seen


def condition_visibility_for_approver(
    form_design: Any,
    design: DesignInfo,
    all_answers: List[Any],
    visible_answers: List[Any],
    config: Optional[dict],
) -> dict:
    """Veredicto de las condiciones que el aprobador NO puede evaluar solo.

    Un campo condicional se muestra si la pregunta que lo condiciona trae cierto
    valor. Si esa pregunta es `hidden` para este aprobador, el servidor no se la
    manda: el cliente no encuentra el valor y oculta el campo aunque venga
    diligenciado. Aquí se resuelve la condición contra TODAS las respuestas y se
    manda solo el veredicto — el valor sigue sin salir del servidor.

    Devuelve `{"global": {element_id: bool}, "rows": {fila: {element_id: bool}}}`,
    y solo con los elementos cuyo valor de condición el cliente no tiene. Lo
    demás lo sigue evaluando el cliente, exactamente como hoy.

    Las filas se etiquetan como las nombra el renderer: `repeated_id` si las
    answers lo traen, y `pos-N` cuando se reconstruyen por posición.
    """
    from app.core import conditions

    conditional = conditions.collect_conditional_elements(form_design)
    if not conditional:
        return {}

    hidden = elements_with_mode(config, HIDDEN)
    all_loose, all_rows = _index_condition_values(all_answers, design)
    seen_loose, seen_rows = _index_condition_values(visible_answers, design)

    result_global: Dict[str, bool] = {}
    result_rows: Dict[str, Dict[str, bool]] = {}

    for element in conditional:
        element_id = element["element_id"]
        # El elemento condicionado tampoco lo ve: no hay nada que resolver.
        if element_id in hidden:
            continue

        question_ids = element["question_ids"]
        props = element["props"]
        repeater_id = element["repeater_id"]

        # Un elemento puede depender de VARIAS preguntas, y cada una puede vivir
        # dentro del repetidor (valor por fila) o fuera (valor único).
        en_repetidor = design.questions_of_repeater.get(repeater_id, set()) if repeater_id else set()
        por_fila = [q for q in question_ids if q in en_repetidor]
        sueltas = [q for q in question_ids if q not in en_repetidor]

        def valor_para(qid: int, key=None):
            """El valor que usaría el servidor para esa pregunta."""
            if qid in en_repetidor and key is not None:
                return all_rows.get((key, qid))
            return all_loose.get(qid)

        if repeater_id:
            for key, token in _rows_of_repeater(visible_answers, repeater_id, design):
                # Si el cliente TIENE todos los valores, que lo evalúe él.
                le_falta = any((key, q) not in seen_rows for q in por_fila)                     or any(q not in seen_loose for q in sueltas)
                if not le_falta:
                    continue
                visible = conditions.is_visible_by_condition(
                    props, lambda q, _k=key: valor_para(q, _k)
                )
                result_rows.setdefault(token, {})[element_id] = visible
            continue

        # Campo suelto: solo dependen de valores sueltos.
        if all(q in seen_loose for q in question_ids):
            continue
        visible = conditions.is_visible_by_condition(props, lambda q: all_loose.get(q))
        result_global[element_id] = visible

    if not result_global and not result_rows:
        return {}

    return {"global": result_global, "rows": result_rows}


# ─── Auto-salto de aprobadores sin trabajo ───────────────────────────────────

AUTO_SKIP_MESSAGE = (
    "Aprobado automáticamente: esta respuesta no trae filas que le correspondan "
    "a este aprobador."
)


def auto_resolve_empty_approvals(db, response_id: int) -> List[int]:
    """Resuelve sola la aprobación de quien no tiene nada que revisar.

    Si el filtro de filas de un aprobador no deja ninguna fila y tampoco tiene
    campos por llenar fuera de ese repetidor, no hay nada que pueda hacer: su
    aprobación se marca aprobada con un mensaje explicativo y el flujo sigue de
    largo. Sin esto la respuesta se quedaría esperando para siempre.

    Al RECIBIDOR no se le aplica: su trabajo no es revisar filas sino dar el
    acuse de recibo, y eso solo lo puede hacer él. Aunque su filtro no deje
    ninguna fila, el pendiente le llega y queda ahí hasta que pulse "Recibido".

    Es idempotente: solo toca aprobaciones en estado pendiente. Devuelve los
    user_id que se saltaron.
    """
    from app.core import response_scope
    from app.models import Answer, ApprovalStatus, Form, Response, ResponseApproval
    from datetime import datetime, timezone

    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        return []

    configs = load_field_access(db, response.form_id)
    # Solo cuesta algo cuando hay filtros de fila configurados.
    if not any(row_filters(config) for config in configs.values()):
        return []

    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        return []

    design = collect_design(form.form_design)
    # El árbol completo, no solo la respuesta del diligenciador: hay filtros de
    # fila que miran un campo que llena un aprobador anterior, y esas answers
    # viven en la respuesta hija de ese aprobador. Leyendo solo la padre, el
    # filtro no encontraba nada y saltaba a quien sí tenía trabajo.
    answers = (
        db.query(Answer)
        .filter(Answer.response_id.in_(response_scope.response_tree_ids(db, response_id)))
        .all()
    )

    pending = (
        db.query(ResponseApproval)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.status == ApprovalStatus.pendiente,
        )
        .all()
    )

    skipped: List[int] = []
    for approval in pending:
        if (getattr(approval, "participant_role", None) or "approver") == "receiver":
            continue  # el acuse de recibo no se firma solo
        config = configs.get(approval.user_id)
        if not config:
            continue
        if approver_has_work(answers, config, design):
            continue

        approval.status = ApprovalStatus.aprobado
        approval.reviewed_at = datetime.now(timezone.utc)
        approval.message = AUTO_SKIP_MESSAGE
        skipped.append(approval.user_id)

    if skipped:
        db.commit()

    return skipped


# ─── Recibidor dinámico ("recibidor aleatorio") ──────────────────────────────
#
# Un campo tipo lista puede marcarse en el diseño con `props.receiverSelector`.
# Ese campo lo llena alguien de la cadena —no quien diligencia— y lo que escoge
# es la PERSONA que va a recibir después de él. Como el usuario no se conoce
# hasta ese momento, el participante no puede existir en la plantilla del
# formato: se crea aquí, cuando ya hay una respuesta que leer.
#
# Cada campo marcado es un participante independiente, así que un formato puede
# encadenar varios saltos, cada uno con su campo y su propia config.


def receiver_selector_elements(form_design: Any) -> List[dict]:
    """Campos del diseño marcados como "este campo elige al recibidor".

    Devuelve [{element_id, question_id, label}], en el orden del diseño.
    """
    import json

    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except (ValueError, TypeError):
            return []

    if not isinstance(form_design, list):
        return []

    encontrados: List[dict] = []

    def walk(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            props = item.get("props") or {}
            if props.get("receiverSelector") and item.get("id"):
                encontrados.append({
                    "element_id": str(item["id"]),
                    "question_id": item.get("id_question") or item.get("linkExternalId"),
                    "label": props.get("label") or "Recibidor",
                })
            walk(item.get("children"))

    walk(form_design)
    return encontrados


def approver_selector_elements(form_design: Any) -> List[dict]:
    """Campos del diseño marcados como "este campo elige al aprobador".

    Gemelo de `receiver_selector_elements`, con la bandera `approverSelector`.
    Devuelve [{element_id, question_id, label}], en el orden del diseño.
    """
    import json

    if isinstance(form_design, str):
        try:
            form_design = json.loads(form_design)
        except (ValueError, TypeError):
            return []

    if not isinstance(form_design, list):
        return []

    encontrados: List[dict] = []

    def walk(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            props = item.get("props") or {}
            if props.get("approverSelector") and item.get("id"):
                encontrados.append({
                    "element_id": str(item["id"]),
                    "question_id": item.get("id_question") or item.get("linkExternalId"),
                    "label": props.get("label") or "Aprobador",
                })
            walk(item.get("children"))

    walk(form_design)
    return encontrados


def resolve_receiver_user(db, valor: Any):
    """Usuario al que se refiere el valor de un campo selector de participante.

    Sirve para los dos casos: cuando la persona se escoge en el desplegable
    ("Nombre (correo)" / "Nombre (#id)") y cuando el valor llega por
    autocompletado desde otro formato (una cédula, un nombre, o ambos).

    El campo guarda texto, así que se busca por lo más identificable primero.
    El frontend arma cada opción como "Nombre (correo)" y, cuando no puede ver
    el correo —a un usuario normal el directorio le llega sin correos—, como
    "Nombre (#id)". Se aceptan las dos formas, luego el texto entero como
    correo, y por último el nombre exacto. Devuelve None si no se puede resolver
    a una única persona: ante la duda es mejor no crear un participante
    equivocado.
    """
    import re
    from sqlalchemy import func
    from app.models import User

    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None

    entre_parentesis = re.search(r"\(([^)]+)\)\s*$", texto)
    candidatos = []
    if entre_parentesis:
        candidatos.append(entre_parentesis.group(1).strip())
    candidatos.append(texto)

    for candidato in candidatos:
        # "#123" → id directo, la forma más fiable.
        if candidato.startswith("#") and candidato[1:].isdigit():
            usuario = db.query(User).filter(User.id == int(candidato[1:])).first()
            if usuario:
                return usuario
        if "@" not in candidato:
            continue
        usuario = db.query(User).filter(func.lower(User.email) == candidato.lower()).first()
        if usuario:
            return usuario

    # ── Valores que NO vienen del desplegable de personas ────────────────────
    # El campo puede llenarse por autocompletado desde otro formato: se escoge un
    # proyecto y el campo trae la cédula, el nombre, o los dos juntos
    # ("1098765 - JUAN PEREZ"). Ahí no hay correo ni "#id" que valga, así que se
    # busca por documento y por nombre. En todos los casos se exige que la
    # coincidencia sea ÚNICA: ante la duda es mejor no crear un participante
    # equivocado que meter al que no era en la cadena.
    piezas = {texto}
    for sep in (" - ", " – ", " | ", ",", ";", "-"):
        for parte in texto.split(sep):
            parte = parte.strip()
            if parte:
                piezas.add(parte)
    # Las tiras de dígitos sueltas son candidatas a documento.
    piezas.update(re.findall(r"\d{4,}", texto))

    for pieza in piezas:
        por_documento = db.query(User).filter(User.num_document == pieza).all()
        if len(por_documento) == 1:
            return por_documento[0]

    for pieza in piezas:
        por_nombre = db.query(User).filter(
            func.lower(func.trim(User.name)) == pieza.lower()
        ).all()
        if len(por_nombre) == 1:
            return por_nombre[0]

    return None


def resolve_dynamic_receivers(db, response_id: int) -> List[int]:
    """Crea los recibidores elegidos en campos selectores de esta respuesta.

    Por cada campo marcado que ya tenga respuesta y cuyo participante todavía no
    exista, añade su `ResponseApproval` con papel 'receiver'.

    El nuevo entra al FINAL de la cadena. Se hizo así a propósito: la secuencia
    es la clave con la que se localiza cada aprobación, y renumerar filas ya
    creadas para colarlo en mitad del flujo es mucho más arriesgado que ponerlo
    detrás. En el caso previsto —el último de la cadena escoge a quien le
    recibe— es además la misma posición.

    Es idempotente: si el participante de ese campo ya existe, no hace nada.
    Devuelve los user_id creados.
    """
    from app.core import response_scope
    from app.models import Answer, ApprovalStatus, Form, Response, ResponseApproval

    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        return []

    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        return []

    selectores = receiver_selector_elements(form.form_design)
    if not selectores:
        return []

    # Ya creados, para no duplicar si el paso se guarda dos veces.
    existentes = {
        ra.dynamic_source_element_id
        for ra in db.query(ResponseApproval)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.dynamic_source_element_id.isnot(None),
        )
        .all()
    }
    pendientes = [s for s in selectores if s["element_id"] not in existentes]
    if not pendientes:
        return []

    # La respuesta del campo puede vivir en la respuesta hija del participante
    # que lo llenó, no en la padre: hay que mirar el árbol completo.
    ids_arbol = response_scope.response_tree_ids(db, response_id)
    answers = (
        db.query(Answer)
        .filter(Answer.response_id.in_(ids_arbol))
        .all()
    )
    # Dueño de cada respuesta del árbol: sirve para saber QUIÉN eligió cuando la
    # answer no trae autor (las del diligenciador no lo llevan).
    dueno_de_respuesta = {
        r.id: r.user_id
        for r in db.query(Response).filter(Response.id.in_(ids_arbol)).all()
    }

    ya_en_cadena = {
        ra.user_id
        for ra in db.query(ResponseApproval)
        .filter(ResponseApproval.response_id == response_id)
        .all()
    }
    siguiente_secuencia = max(
        [
            ra.sequence_number
            for ra in db.query(ResponseApproval)
            .filter(ResponseApproval.response_id == response_id)
            .all()
        ] or [0]
    )

    creados: List[int] = []
    for selector in pendientes:
        respuesta = next(
            (
                a for a in answers
                if str(_get(a, "form_design_element_id") or "") == selector["element_id"]
                and (_get(a, "answer_text") or "").strip()
            ),
            None,
        )
        if respuesta is None:
            continue  # todavía nadie lo ha llenado

        usuario = resolve_receiver_user(db, _get(respuesta, "answer_text"))
        if usuario is None:
            continue
        # Ya está en la cadena (es el mismo que lo eligió, o un participante
        # fijo): no se duplica, recibiría dos veces lo mismo.
        if usuario.id in ya_en_cadena:
            continue

        # De quién recibe: de quien lo eligió. Sin esto el recibidor no cuelga de
        # nadie, y "Formatos por recibir → lo que envié" —que busca a los
        # recibidores cuyo `receives_from_user_ids` contiene al aprobador— no se
        # lo mostraría nunca a quien lo escogió.
        #
        # Las answers del participante llevan autor; las de quien diligencia no,
        # y ahí el dueño es el de la respuesta donde vive la answer.
        elector = (
            _get(respuesta, "answered_by_user_id")
            or dueno_de_respuesta.get(_get(respuesta, "response_id"))
        )

        siguiente_secuencia += 1
        db.add(ResponseApproval(
            response_id=response_id,
            user_id=usuario.id,
            sequence_number=siguiente_secuencia,
            is_mandatory=True,
            status=ApprovalStatus.pendiente,
            participant_role="receiver",
            receives_from_user_ids=[elector] if elector else None,
            dynamic_source_element_id=selector["element_id"],
        ))
        ya_en_cadena.add(usuario.id)
        creados.append(usuario.id)

    if creados:
        db.commit()

    return creados


def resolve_dynamic_approvers(
    db,
    response_id: int,
    avisos: Optional[List[str]] = None,
) -> List[int]:
    """Crea los aprobadores elegidos en campos selectores de esta respuesta.

    Gemelo de `resolve_dynamic_receivers`, pero con papel 'approver': el que
    diligencia (o un aprobador anterior) escoge en un campo quién aprueba
    despues, en vez de que el administrador lo deje fijo en la plantilla.

    Igual que con los recibidores, el nuevo entra al FINAL de la cadena: la
    secuencia es la clave con la que se localiza cada aprobacion, y renumerar
    filas ya creadas para colarlo en mitad del flujo es mucho mas arriesgado que
    ponerlo detras. En el caso previsto —el ultimo de la cadena escoge quien
    sigue— es ademas la misma posicion.

    Es idempotente: si el participante de ese campo ya existe, no hace nada.
    Devuelve los user_id creados. Si se pasa `avisos`, se le agregan los mensajes
    de los campos cuyo valor no se pudo resolver a un usuario, para que quien
    diligencia se entere en vez de quedarse sin aprobador en silencio.
    """
    from app.core import response_scope
    from app.models import Answer, ApprovalStatus, Form, Response, ResponseApproval

    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        return []

    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        return []

    selectores = approver_selector_elements(form.form_design)
    if not selectores:
        return []

    existentes = {
        ra.dynamic_source_element_id
        for ra in db.query(ResponseApproval)
        .filter(
            ResponseApproval.response_id == response_id,
            ResponseApproval.dynamic_source_element_id.isnot(None),
        )
        .all()
    }
    pendientes = [s for s in selectores if s["element_id"] not in existentes]
    if not pendientes:
        return []

    ids_arbol = response_scope.response_tree_ids(db, response_id)
    answers = db.query(Answer).filter(Answer.response_id.in_(ids_arbol)).all()

    ya_en_cadena = {
        ra.user_id
        for ra in db.query(ResponseApproval)
        .filter(ResponseApproval.response_id == response_id)
        .all()
    }
    siguiente_secuencia = max(
        [
            ra.sequence_number
            for ra in db.query(ResponseApproval)
            .filter(ResponseApproval.response_id == response_id)
            .all()
        ] or [0]
    )

    creados: List[int] = []
    # Avisos para quien diligencia: campos llenos cuyo valor no corresponde a
    # ningún usuario. Se devuelven aparte de los creados.
    sin_resolver: List[str] = []
    for selector in pendientes:
        respuesta = next(
            (
                a for a in answers
                if str(_get(a, "form_design_element_id") or "") == selector["element_id"]
                and (_get(a, "answer_text") or "").strip()
            ),
            None,
        )
        if respuesta is None:
            continue  # todavia nadie lo ha llenado

        # Se reusa el mismo resolutor de los recibidores: el formato del texto
        # que guarda el campo ("Nombre (correo)" / "Nombre (#id)") es identico.
        texto = (_get(respuesta, "answer_text") or "").strip()
        usuario = resolve_receiver_user(db, texto)
        if usuario is None:
            # No se pudo saber a quién se refiere: ni por correo, ni por cédula,
            # ni por nombre único. Se avisa en vez de dejarlo pasar en silencio;
            # antes el formato se enviaba sin aprobador y nadie se enteraba.
            aviso = (
                f'No se encontró en SafeMetrics al aprobador "{texto}" '
                f'del campo "{selector["label"]}". El formato quedó sin ese aprobador.'
            )
            logger.warning(
                "Respuesta %s: %s (elemento %s)", response_id, aviso, selector["element_id"]
            )
            sin_resolver.append(aviso)
            continue
        if usuario.id in ya_en_cadena:
            continue

        siguiente_secuencia += 1
        db.add(ResponseApproval(
            response_id=response_id,
            user_id=usuario.id,
            sequence_number=siguiente_secuencia,
            is_mandatory=True,
            status=ApprovalStatus.pendiente,
            participant_role="approver",
            dynamic_source_element_id=selector["element_id"],
        ))
        ya_en_cadena.add(usuario.id)
        creados.append(usuario.id)

    if avisos is not None:
        avisos.extend(sin_resolver)

    if creados:
        db.commit()

        # Avisarle al que quedo de turno.
        #
        # Hace falta porque el aviso al "siguiente aprobador" sale al ENVIAR la
        # respuesta (post_create_response), y para entonces este participante
        # todavia no existe: se crea despues, cuando se guarda la answer del
        # campo selector. En un formato sin aprobadores fijos —el caso tipico de
        # esta funcion— nadie recibiria nada.
        #
        # Solo se manda si el que sigue pendiente es uno de los recien creados:
        # si delante habia aprobadores fijos, a esos ya se les aviso y repetirlo
        # seria correo de mas.
        try:
            from app.models import ApprovalStatus, ResponseApproval

            pendientes = (
                db.query(ResponseApproval)
                .filter(
                    ResponseApproval.response_id == response_id,
                    ResponseApproval.status == ApprovalStatus.pendiente,
                )
                .order_by(ResponseApproval.sequence_number)
                .all()
            )
            if pendientes and pendientes[0].user_id in creados:
                from app.crud import send_mails_to_next_supporters
                send_mails_to_next_supporters(response_id, db)
        except Exception:
            # El aviso no puede tumbar la creacion del participante: si el correo
            # falla, el aprobador igual queda en la cadena y lo vera en su bandeja.
            logger.exception("No se pudo avisar al aprobador dinamico de la respuesta %s", response_id)

    return creados
