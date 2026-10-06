"""
Extractor de relaciones entre formatos — Guía v3 sección 11.

Lee las fuentes de relaciones que ya existen en la base y produce el
grafo que el mapa necesita. NO modifica nada: solo lee.

Fuentes:
  1-5. QuestionTableRelation  (modos de carga, listas, seriales)
  6.   QuestionFilterCondition (condición lógica)
  7.   ApprovalRequirement     (formato requerido antes de aprobar)
  8.   RelationOperationMath   (operaciones matemáticas cross-format)
"""

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Form,
    FormCategory,
    FormQuestion,
    Question,
    QuestionTableRelation,
    QuestionFilterCondition,
    ApprovalRequirement,
    RelationOperationMath,
)


def extract_relations(db: Session) -> dict[str, Any]:
    """
    Extrae el grafo completo de relaciones entre formatos.

    Retorna la estructura que el prototipo espera:
      nodes[]      — formatos con id, nombre, tipo, carpeta, nivel, deps
      edges[]      — relaciones con de, a, clase, campos[], fuente
      fields{}     — campos de cada formato (para la ventana de relaciones)
      categories{} — carpetas con nombre y color
      stats{}      — contadores
    """
    # ── 1. Formatos y categorías ──────────────────────────────────────
    forms = db.query(Form).all()
    form_map = {f.id: f for f in forms}
    form_ids = set(form_map.keys())
    if not form_ids:
        return {"nodes": [], "edges": [], "fields": {}, "categories": {}, "stats": {}}

    cat_ids = {f.id_category for f in forms if f.id_category}
    categories = {}
    if cat_ids:
        for c in db.query(FormCategory).filter(FormCategory.id.in_(cat_ids)).all():
            categories[c.id] = {"name": c.name, "color": c.color or "#6b7f8c", "parent_id": c.parent_id}

    # ── 2. Mapas de preguntas ─────────────────────────────────────────
    fq_rows = db.query(FormQuestion.question_id, FormQuestion.form_id).filter(
        FormQuestion.form_id.in_(form_ids)
    ).all()

    q_to_forms: dict[int, set[int]] = defaultdict(set)
    form_to_qs: dict[int, set[int]] = defaultdict(set)
    for qid, fid in fq_rows:
        q_to_forms[qid].add(fid)
        form_to_qs[fid].add(qid)

    all_q_ids = set(q_to_forms.keys())
    questions = {}
    if all_q_ids:
        for q in db.query(Question).filter(Question.id.in_(all_q_ids)).all():
            questions[q.id] = q

    # ── 3. Extraer aristas ────────────────────────────────────────────
    edges: list[dict] = []
    deps: dict[int, set[int]] = defaultdict(set)
    seen: set[tuple] = set()

    def add_edge(from_id, to_id, clase, campos, source):
        if from_id == to_id or from_id not in form_ids or to_id not in form_ids:
            return
        key = (from_id, to_id, clase, source)
        if key in seen:
            for e in edges:
                if (e["de"], e["a"], e["clase"], e["fuente"]) == key:
                    for c in campos:
                        if c not in e["campos"]:
                            e["campos"].append(c)
                    return
            return
        seen.add(key)
        deps[to_id].add(from_id)
        edges.append({"de": from_id, "a": to_id, "clase": clase, "campos": campos, "fuente": source})

    # 3a. QuestionTableRelation
    for qtr in db.query(QuestionTableRelation).filter(
        QuestionTableRelation.question_id.in_(all_q_ids)
    ).all():
        dest_forms = q_to_forms.get(qtr.question_id, set())
        src_forms: set[int] = set()
        if qtr.related_question_id:
            src_forms = q_to_forms.get(qtr.related_question_id, set())
        if qtr.related_form_id and qtr.related_form_id in form_ids:
            src_forms.add(qtr.related_form_id)
        if not src_forms:
            continue
        dest_q = questions.get(qtr.question_id)
        src_q = questions.get(qtr.related_question_id) if qtr.related_question_id else None
        campo = (src_q.question_text if src_q else dest_q.question_text) if dest_q else ""
        for sf in src_forms:
            for df in dest_forms:
                add_edge(sf, df, "dato", [campo] if campo else [], "table_relation")

    # 3b. QuestionFilterCondition
    for qfc in db.query(QuestionFilterCondition).filter(
        QuestionFilterCondition.form_id.in_(form_ids)
    ).all():
        src_forms = q_to_forms.get(qfc.source_question_id, set())
        cond_forms = q_to_forms.get(qfc.condition_question_id, set())
        src_q = questions.get(qfc.source_question_id)
        campo = src_q.question_text if src_q else ""
        for sf in (src_forms | cond_forms):
            add_edge(sf, qfc.form_id, "dato", [campo] if campo else [], "filter_condition")

    # 3c. ApprovalRequirement
    for ar in db.query(ApprovalRequirement).filter(
        ApprovalRequirement.form_id.in_(form_ids)
    ).all():
        if ar.required_form_id in form_ids:
            add_edge(ar.required_form_id, ar.form_id, "aprob", [], "approval_requirement")

    # 3d. RelationOperationMath (cross-format)
    for math_op in db.query(RelationOperationMath).filter(
        RelationOperationMath.id_form.in_(form_ids)
    ).all():
        q_ids = math_op.id_questions or []
        if isinstance(q_ids, str):
            import json
            try:
                q_ids = json.loads(q_ids)
            except (ValueError, TypeError):
                continue
        for qid in q_ids:
            try:
                qid_int = int(qid)
            except (ValueError, TypeError):
                continue
            for sf in q_to_forms.get(qid_int, set()):
                if sf != math_op.id_form:
                    q_obj = questions.get(qid_int)
                    campo = q_obj.question_text if q_obj else ""
                    add_edge(sf, math_op.id_form, "dato", [campo] if campo else [], "math_operation")

    # ── 4. Niveles (BFS topológico) ───────────────────────────────────
    levels = _compute_levels(form_ids, deps)

    # ── 5. Nodos ──────────────────────────────────────────────────────
    nodes = []
    for f in forms:
        cat = categories.get(f.id_category, {})
        nodes.append({
            "id": f.id,
            "title": f.title,
            "description": f.description or "",
            "format_type": f.format_type.value if f.format_type else "abierto",
            "category_id": f.id_category,
            "category_name": cat.get("name", ""),
            "category_color": cat.get("color", "#6b7f8c"),
            "level": levels.get(f.id, 0),
            "deps": sorted(deps.get(f.id, set())),
            "is_enabled": f.is_enabled,
            "user_id": f.user_id,
        })

    # ── 6. Campos por formato ─────────────────────────────────────────
    fields = _build_fields(form_ids, form_to_qs, questions, edges)

    # ── 7. Stats ──────────────────────────────────────────────────────
    connected = set()
    for e in edges:
        connected.add(e["de"])
        connected.add(e["a"])

    return {
        "nodes": nodes,
        "edges": edges,
        "fields": fields,
        "categories": categories,
        "stats": {
            "total_formats": len(forms),
            "connected_formats": len(connected),
            "total_edges": len(edges),
            "isolated_formats": len(form_ids - connected),
        },
    }


def _compute_levels(form_ids, deps):
    from collections import deque
    in_deg = defaultdict(int)
    adj = defaultdict(set)
    for fid in form_ids:
        in_deg[fid] = 0
    for fid, srcs in deps.items():
        in_deg[fid] = len(srcs)
        for s in srcs:
            adj[s].add(fid)

    levels = {}
    q = deque()
    for fid in form_ids:
        if in_deg[fid] == 0:
            levels[fid] = 0
            q.append(fid)
    while q:
        node = q.popleft()
        for child in adj[node]:
            levels[child] = max(levels.get(child, 0), levels[node] + 1)
            in_deg[child] -= 1
            if in_deg[child] == 0:
                q.append(child)
    for fid in form_ids:
        if fid not in levels:
            levels[fid] = 0
    return levels


def _build_fields(form_ids, form_to_qs, questions, edges):
    """Campos por formato para la ventana de relaciones del mapa."""
    consumed_by = defaultdict(lambda: defaultdict(list))
    for e in edges:
        for campo in e["campos"]:
            consumed_by[e["de"]][campo].append(e["a"])

    fields = {}
    for fid in form_ids:
        q_ids = form_to_qs.get(fid, set())
        if not q_ids:
            continue
        field_list = []
        for qid in sorted(q_ids):
            q = questions.get(qid)
            if not q:
                continue
            q_type = q.question_type.value if q.question_type else "text"
            nombre = q.question_text or f"Pregunta #{qid}"
            consumers = consumed_by.get(fid, {}).get(nombre, [])

            usable = True
            motivo = None
            if q_type in ('firm', 'regisfacial'):
                usable = False
                motivo = f"tipo {q_type} no se puede referenciar"

            field_list.append({
                "id": q.id,
                "nombre": nombre,
                "tipo": q_type,
                "requerido": q.required,
                "consumido_por": consumers,
                "usable": usable,
                "motivo": motivo,
            })
        if field_list:
            fields[fid] = field_list
    return fields


def detect_approval_cycles(db: Session) -> list[list[int]]:
    """Detecta ciclos en relaciones de clase aprob (abrazo mortal §11)."""
    ar_rows = db.query(ApprovalRequirement).all()
    adj = defaultdict(set)
    for ar in ar_rows:
        adj[ar.required_form_id].add(ar.form_id)

    visited, in_stack = set(), set()
    cycles = []

    def dfs(node, path):
        visited.add(node)
        in_stack.add(node)
        path.append(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                dfs(nb, path)
            elif nb in in_stack:
                cycles.append(path[path.index(nb):])
        path.pop()
        in_stack.discard(node)

    all_nodes = set(adj.keys())
    for ar in ar_rows:
        all_nodes.add(ar.form_id)
    for node in all_nodes:
        if node not in visited:
            dfs(node, [])
    return cycles
