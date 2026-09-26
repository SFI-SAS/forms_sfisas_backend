"""
Cargue masivo de la plantilla Excel de un formato, en el backend.

    POST /forms/{form_id}/import-template   (multipart: archivo=.xlsx)
        confirmar=false  -> SOLO valida y devuelve el informe (no escribe nada)
        confirmar=true   -> valida y, si no hay errores, carga todo
        omitir_invalidas -> con confirmar=true, carga las filas buenas y salta las malas

Hasta ahora el "Importar Excel" del frontend mandaba cada registro en dos
llamadas por dato (save-response + una save-answers POR RESPUESTA, cada una con
su commit): 2.080 materiales eran ~40.000 peticiones, sin validación previa y
sin marcha atrás si fallaba a la mitad. Aquí:

  * el Excel se lee una vez (openpyxl read_only);
  * se valida TODO antes de escribir, con una consulta por lista enlazada y por
    pregunta no repetible (nunca por fila);
  * se inserta en lote en UNA transacción (~5 sentencias en total);
  * los campos calculados se calculan aquí (el cargue del front los dejaba
    vacíos, y de ellos se alimenta, p. ej., el precio de la mano de obra del APU).

Se guarda exactamente lo mismo que el diligenciamiento normal
(`post_create_response` + `save_single_answer`): Response, RelationBitacora,
ResponseApproval (si corresponde), Answer y QuestionAndAnswerBitacora.
No se manda un correo por registro: con miles de filas eso satura el SMTP
(ver la nota de `send_notifications` en `post_create_response`).
"""
import json
import time as _time
from typing import Optional

from fastapi import Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, insert
from sqlalchemy.orm import Session

from app.core import field_access
from app.core.plantilla_import import (
    TIPOS_FECHA, TIPOS_NO_IMPORTABLES, PlantillaInvalida, calcular_formula,
    campos_del_diseno, leer_plantilla, numero_js, parse_numero, sin_tildes, valor_a_texto,
)
from app.core.security import get_current_user
from app.database import get_db
from app.models import (
    Answer, Form, FormApproval, FormatType, ApprovalStatus, Question,
    QuestionAndAnswerBitacora, QuestionTableRelation, RelationBitacora,
    RelationOperationMath, Response, ResponseApproval, ResponseStatus, User,
)

MAX_BYTES = 15 * 1024 * 1024
MAX_REGISTROS = 20000
MAX_LARGO = 255  # answers.answer_text es varchar(255)

MENSAJES = {
    "obligatorio_vacio": "es obligatorio y está vacío",
    "fecha_invalida": "no es una fecha válida (use dd/mm/aaaa)",
    "numero_invalido": "no es un número válido",
    "muy_largo": f"supera los {MAX_LARGO} caracteres",
    "fuera_de_lista": "no existe en la lista de donde sale este campo",
    "duplicado_en_archivo": "está repetido dentro del archivo y este campo no admite repetidos",
    "ya_existe": "ya existe en el sistema y este campo no admite repetidos",
    "opcion_no_valida": "no está entre las opciones del campo (se guardará tal cual)",
    "no_importable": "es un campo que no se puede cargar desde Excel (archivo o firma); se omite",
    "formula_con_fecha": "es un cálculo con fechas; no se calcula en el cargue masivo",
}


class _Informe:
    """Agrupa los problemas por (tipo, campo) para que el informe sea legible
    aunque haya miles: cantidad, algunos ejemplos y los valores distintos."""

    def __init__(self):
        self.grupos: dict = {}

    def add(self, nivel: str, tipo: str, campo, fila: int, valor=None):
        g = self.grupos.setdefault((nivel, tipo, campo.element_id), {
            "nivel": nivel, "tipo": tipo, "campo": campo.etiqueta,
            "mensaje": MENSAJES.get(tipo, tipo), "cantidad": 0, "ejemplos": [], "valores": {},
        })
        g["cantidad"] += 1
        if len(g["ejemplos"]) < 5:
            g["ejemplos"].append({"fila_excel": fila, "valor": None if valor is None else str(valor)[:80]})
        if valor not in (None, "") and len(g["valores"]) < 30:
            v = str(valor)[:80]
            g["valores"][v] = g["valores"].get(v, 0) + 1

    def lista(self, nivel: str) -> list:
        salida = []
        for g in self.grupos.values():
            if g["nivel"] == nivel:
                g = dict(g)
                g["valores_distintos"] = [{"valor": k, "veces": n} for k, n in
                                          sorted(g.pop("valores").items(), key=lambda x: -x[1])]
                g.pop("nivel")
                salida.append(g)
        return sorted(salida, key=lambda g: -g["cantidad"])

    def total(self, nivel: str) -> int:
        return sum(g["cantidad"] for g in self.grupos.values() if g["nivel"] == nivel)


def _ids_formula(raw) -> list:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return [int(x) for x in raw or [] if str(x).lstrip("-").isdigit()]


def register_import_template_route(router):
    """Se llama desde forms.py, igual que register_export_template_route."""

    @router.post("/{form_id}/import-template")
    def import_template(
        form_id: int,
        archivo: UploadFile = File(...),
        confirmar: bool = Query(False, description="False = solo validar"),
        omitir_invalidas: bool = Query(False, description="Con confirmar: cargar solo las filas buenas"),
        action: str = Query("send_and_close", enum=["send", "send_and_close"]),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        t0 = _time.perf_counter()

        form = db.query(Form).filter(Form.id == form_id).first()
        if not form:
            raise HTTPException(status_code=404, detail="Formato no encontrado")
        if not form.is_enabled:
            raise HTTPException(status_code=409, detail="Este formato está en borrador y no se puede diligenciar.")

        diseno = form.form_design
        if isinstance(diseno, str):
            try:
                diseno = json.loads(diseno)
            except json.JSONDecodeError:
                diseno = None
        if not isinstance(diseno, list) or not diseno:
            raise HTTPException(status_code=400, detail="El formato no tiene diseño")
        campos = campos_del_diseno(diseno)

        contenido = archivo.file.read(MAX_BYTES + 1)
        if len(contenido) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="El archivo supera 15 MB")
        try:
            plantilla = leer_plantilla(contenido, campos)
        except PlantillaInvalida as e:
            raise HTTPException(status_code=400, detail=str(e))
        if len(plantilla.registros) > MAX_REGISTROS:
            raise HTTPException(status_code=400, detail=f"Máximo {MAX_REGISTROS} registros por archivo")

        informe = _Informe()
        qids = {c.question_id for c in campos if c.question_id}
        preguntas = {q.id: q for q in db.query(Question).filter(Question.id.in_(qids)).all()} if qids else {}
        con_columna = {c.campo.element_id for c in plantilla.columnas}

        # Listas que salen de las respuestas de otro formato: una consulta por lista.
        listas: dict[int, dict] = {}
        for rel in db.query(QuestionTableRelation).filter(QuestionTableRelation.question_id.in_(qids)).all():
            if rel.related_question_id:
                valores = db.query(Answer.answer_text).filter(
                    Answer.question_id == rel.related_question_id, Answer.answer_text.isnot(None)
                ).distinct().all()
                listas[rel.question_id] = {sin_tildes(v): v for (v,) in valores if v and v.strip()}

        # ── Registro por registro: textos, validaciones, respuestas a guardar ──
        malos: set[int] = set()
        por_registro: list[list[dict]] = []
        unicos: dict[int, dict[str, int]] = {}      # qid -> {texto: índice de registro}
        unicos_filas: dict[tuple, int] = {}          # (qid, texto) -> fila excel

        def celda(i, reg, campo, crudo, fila, answers, rep_id=None, idx=None, padre=None):
            if campo.tipo in TIPOS_NO_IMPORTABLES:
                informe.add("advertencia", "no_importable", campo, fila, None)
                return
            texto, problema = valor_a_texto(campo, crudo)
            if problema:
                informe.add("error", problema, campo, fila, texto); malos.add(i); return
            if not texto:
                return
            if len(texto) > MAX_LARGO:
                informe.add("error", "muy_largo", campo, fila, texto[:60] + "…"); malos.add(i); return
            qid = campo.question_id
            if qid in listas:
                canon = listas[qid].get(sin_tildes(texto))
                if canon is None:
                    informe.add("error", "fuera_de_lista", campo, fila, texto); malos.add(i); return
                texto = canon
            elif campo.opciones:
                canon = {sin_tildes(o): o for o in campo.opciones}.get(sin_tildes(texto))
                if canon is None:
                    informe.add("advertencia", "opcion_no_valida", campo, fila, texto)
                else:
                    texto = canon
            q = preguntas.get(qid)
            if q is not None and q.unique_answer and rep_id is None:
                vistos = unicos.setdefault(qid, {})
                if texto in vistos:
                    informe.add("error", "duplicado_en_archivo", campo, fila, texto); malos.add(i); return
                vistos[texto] = i
                unicos_filas[(qid, texto)] = fila
            answers.append({"question_id": qid, "answer_text": texto, "form_design_element_id": campo.element_id,
                            "repeated_id": rep_id, "repeater_row_index": idx, "parent_repeated_id": padre})

        def obligatorio(campo) -> bool:
            p = campo.props
            return (bool(p.get("required")) and campo.element_id in con_columna
                    and campo.tipo not in TIPOS_NO_IMPORTABLES and campo.tipo != "mathoperations"
                    and not p.get("hidden") and not p.get("condiciones") and not p.get("condicion"))

        normales = [c for c in campos if not c.repetidor and c.question_id]
        de_repetidor: dict[str, list] = {}
        for c in campos:
            if c.repetidor and not c.sub and c.question_id:
                de_repetidor.setdefault(c.repetidor, []).append(c)
        de_sub: dict[str, list] = {}
        for c in campos:
            if c.sub and c.question_id:
                de_sub.setdefault(c.sub, []).append(c)

        for i, reg in enumerate(plantilla.registros):
            answers: list[dict] = []
            for c in normales:
                crudo = reg.normal.get(c.element_id)
                if crudo is None or (isinstance(crudo, str) and not crudo.strip()):
                    if obligatorio(c):
                        informe.add("error", "obligatorio_vacio", c, reg.fila_excel); malos.add(i)
                    continue
                celda(i, reg, c, crudo, reg.fila_excel, answers)
            for rep_id, filas in reg.filas.items():
                for idx, fila in enumerate(filas):
                    if not fila:
                        continue
                    n_excel = reg.fila_de.get((rep_id, idx), reg.fila_excel)
                    for c in de_repetidor.get(rep_id, []):
                        crudo = fila.get(c.element_id)
                        if crudo is None or (isinstance(crudo, str) and not crudo.strip()):
                            if obligatorio(c):
                                informe.add("error", "obligatorio_vacio", c, n_excel); malos.add(i)
                            continue
                        celda(i, reg, c, crudo, n_excel, answers, rep_id, idx)
            for (rep_id, idx, sub_id), subfilas in reg.subfilas.items():
                sub_rep_id = f"{sub_id}-{rep_id}-row{idx}"   # igual que el front
                for sidx, sfila in enumerate(subfilas):
                    for c in de_sub.get(sub_id, []):
                        crudo = sfila.get(c.element_id)
                        if crudo is not None and not (isinstance(crudo, str) and not crudo.strip()):
                            celda(i, reg, c, crudo, reg.fila_excel, answers, sub_rep_id, sidx, rep_id)
            por_registro.append(answers)

        # No repetibles contra lo que ya hay en la base: una consulta por pregunta.
        for qid, vistos in unicos.items():
            textos = list(vistos)
            campo = next(c for c in campos if c.question_id == qid)
            for k in range(0, len(textos), 1000):
                existentes = db.query(Answer.answer_text).filter(
                    Answer.question_id == qid, Answer.answer_text.in_(textos[k:k + 1000])).distinct().all()
                for (t,) in existentes:
                    informe.add("error", "ya_existe", campo, unicos_filas.get((qid, t), 0), t)
                    malos.add(vistos[t])

        # ── Campos calculados ──────────────────────────────────────────────────
        por_qid = {}
        for c in campos:
            if c.question_id and c.question_id not in por_qid:
                por_qid[c.question_id] = c
        formulas = []
        for f in db.query(RelationOperationMath).filter(RelationOperationMath.id_form == form_id).all():
            ids = _ids_formula(f.id_questions)
            destino = por_qid.get(ids[0]) if ids else None
            if not destino or destino.tipo != "mathoperations":
                continue
            operandos = [por_qid.get(q) for q in ids[1:]]
            if any(o is not None and o.tipo in TIPOS_FECHA for o in operandos):
                informe.add("advertencia", "formula_con_fecha", destino, 0)
                continue
            formulas.append((destino, f.operations or "", bool(getattr(f, "clamp_negativos", False))))

        if formulas:
            for i, answers in enumerate(por_registro):
                arriba: dict[int, float] = {}
                filas_val: dict[tuple, dict] = {}
                columnas: dict[int, list] = {}
                for a in answers:
                    n = parse_numero(a["answer_text"])
                    if a["repeated_id"] is None:
                        arriba[a["question_id"]] = n
                    else:
                        filas_val.setdefault((a["repeated_id"], a["repeater_row_index"]), {})[a["question_id"]] = n
                        columnas.setdefault(a["question_id"], []).append(n)
                ya = {(a["question_id"], a["repeated_id"], a["repeater_row_index"]) for a in answers}
                # Pasadas hasta que no cambie nada: un total puede depender de un subtotal.
                for _ in range(len(formulas) + 1):
                    cambio = False
                    for destino, operacion, clamp in formulas:
                        if destino.repetidor:
                            filas_rep = {k[1] for k in filas_val if k[0] == destino.repetidor}
                            for idx in sorted(filas_rep):
                                fila = filas_val[(destino.repetidor, idx)]

                                def valor(q, fila=fila):
                                    c = por_qid.get(q)
                                    if c and c.repetidor == destino.repetidor:
                                        return fila.get(q)
                                    return arriba.get(q) if not (c and c.repetidor) else columnas.get(q)
                                r = calcular_formula(operacion, valor)
                                if r is None:
                                    continue
                                r = max(r, 0.0) if clamp else r
                                if fila.get(destino.question_id) != r:
                                    fila[destino.question_id] = r
                                    cambio = True
                        else:
                            r = calcular_formula(operacion, lambda q: columnas.get(q) if (por_qid.get(q) and por_qid[q].repetidor) else arriba.get(q))
                            if r is None:
                                continue
                            r = max(r, 0.0) if clamp else r
                            if arriba.get(destino.question_id) != r:
                                arriba[destino.question_id] = r
                                cambio = True
                    # las columnas se recalculan de las filas
                    columnas = {}
                    for fila in filas_val.values():
                        for q, n in fila.items():
                            columnas.setdefault(q, []).append(n)
                    if not cambio:
                        break
                for destino, _, _ in formulas:
                    if destino.repetidor:
                        for (rep, idx), fila in filas_val.items():
                            if rep == destino.repetidor and destino.question_id in fila and (destino.question_id, rep, idx) not in ya:
                                answers.append({"question_id": destino.question_id, "answer_text": numero_js(fila[destino.question_id]),
                                                "form_design_element_id": destino.element_id, "repeated_id": rep,
                                                "repeater_row_index": idx, "parent_repeated_id": None})
                    elif destino.question_id in arriba and (destino.question_id, None, None) not in ya:
                        answers.append({"question_id": destino.question_id, "answer_text": numero_js(arriba[destino.question_id]),
                                        "form_design_element_id": destino.element_id, "repeated_id": None,
                                        "repeater_row_index": None, "parent_repeated_id": None})

        validos = [i for i in range(len(plantilla.registros)) if i not in malos and por_registro[i]]
        resumen = {
            "formato": {"id": form.id, "titulo": form.title},
            "registros_leidos": len(plantilla.registros),
            "registros_validos": len(validos),
            "registros_con_error": len(malos),
            "total_errores": informe.total("error"),
            "total_advertencias": informe.total("advertencia"),
            "errores": informe.lista("error"),
            "advertencias": informe.lista("advertencia"),
            "columnas_sin_campo": plantilla.ids_sin_campo,
            "filas_con_etiqueta_desconocida": plantilla.etiquetas_raras,
            "campos_calculados": [d.etiqueta for d, _, _ in formulas],
        }

        if not confirmar or not validos or (malos and not omitir_invalidas):
            resumen.update(importado=False, registros_creados=0,
                           motivo=("solo_validacion" if not confirmar else
                                   "hay_errores" if malos else "nada_para_cargar"),
                           tiempo_ms=int((_time.perf_counter() - t0) * 1000))
            return resumen

        # ── Inserción en lote, una sola transacción ───────────────────────────
        if form.format_type == FormatType.cerrado or action == "send_and_close":
            estado, con_aprobaciones = ResponseStatus.submitted, True
        else:
            estado, con_aprobaciones = ResponseStatus.draft, False
        aprobadores = (db.query(FormApproval).filter(FormApproval.form_id == form_id,
                                                     FormApproval.is_active == True).all()  # noqa: E712
                       if con_aprobaciones else [])
        try:
            ultimo = db.query(func.max(Response.mode_sequence)).filter(Response.mode == "online").scalar() or 0
            filas_resp = []
            for n, i in enumerate(validos, start=1):
                rep = next((a["repeated_id"] for a in por_registro[i] if a["repeated_id"]), None)
                filas_resp.append({"form_id": form_id, "user_id": current_user.id, "mode": "online",
                                   "mode_sequence": ultimo + n, "repeated_id": rep, "status": estado})
            ids_resp = db.execute(insert(Response).returning(Response.id, sort_by_parameter_order=True),
                                  filas_resp).scalars().all()
            ids_bit = db.execute(insert(RelationBitacora).returning(RelationBitacora.id, sort_by_parameter_order=True),
                                 [{"id_response": r} for r in ids_resp]).scalars().all()
            if aprobadores:
                db.execute(insert(ResponseApproval), [{
                    "response_id": r, "user_id": a.user_id, "sequence_number": a.sequence_number,
                    "is_mandatory": a.is_mandatory, "status": ApprovalStatus.pendiente,
                    "firm_mode": getattr(a, "firm_mode", "button") or "button",
                    "firm_source_question_id": getattr(a, "firm_source_question_id", None),
                    "participant_role": getattr(a, "participant_role", "approver") or "approver",
                    "receives_from_user_ids": getattr(a, "receives_from_user_ids", None),
                    "receive_timing": getattr(a, "receive_timing", None) or "after_approvals",
                } for r in ids_resp for a in aprobadores])
            filas_ans, filas_bit = [], []
            nombre = f"{current_user.name}"
            for r, b, i in zip(ids_resp, ids_bit, validos):
                for a in por_registro[i]:
                    filas_ans.append({"response_id": r, "question_id": a["question_id"], "answer_text": a["answer_text"],
                                      "file_path": "", "form_design_element_id": a["form_design_element_id"],
                                      "repeated_id": a["repeated_id"], "repeater_row_index": a["repeater_row_index"],
                                      "parent_repeated_id": a["parent_repeated_id"]})
                    q = preguntas.get(a["question_id"])
                    filas_bit.append({"id_relation_bitacora": b, "name_format": form.title, "name_user": nombre,
                                      "question": (q.question_text if q else "")[:255], "answer": a["answer_text"]})
            db.execute(insert(Answer), filas_ans)
            db.execute(insert(QuestionAndAnswerBitacora), filas_bit)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"No se cargó nada (se revirtió todo): {e}")

        # ── Lo que el diligenciamiento normal hace después, solo si el formato lo usa ──
        post = {"participantes_dinamicos": 0, "registro_externo": 0}
        try:
            if field_access.approver_selector_elements(diseno) or field_access.receiver_selector_elements(diseno):
                for r in ids_resp:
                    field_access.resolve_dynamic_receivers(db, r)
                    field_access.resolve_dynamic_approvers(db, r, avisos=[])
                    post["participantes_dinamicos"] += 1
            if aprobadores:
                for r in ids_resp:
                    field_access.auto_resolve_empty_approvals(db, r)
            from app.api.endpoints import external_signoff
            cfg = external_signoff._config_of(db, form_id)
            if cfg is not None and cfg.trigger_mode == "on_submit":
                for r in ids_resp:
                    post["registro_externo"] += external_signoff.dispatch_on_submit(db, r)
        except Exception as e:  # los datos ya quedaron; esto no tumba el cargue
            post["error"] = str(e)[:200]

        resumen.update(importado=True, registros_creados=len(ids_resp), respuestas_guardadas=len(filas_ans),
                       estado=estado.value, aprobaciones_creadas=len(ids_resp) * len(aprobadores),
                       correos="no se envía un correo por registro en el cargue masivo",
                       posteriores=post, tiempo_ms=int((_time.perf_counter() - t0) * 1000))
        return resumen
