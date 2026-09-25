# -*- coding: utf-8 -*-
"""Compara el consolidado de una vista conjunta: Python (viejo) contra SQL (nuevo).

Para qué sirve
──────────────
El consolidado de movimientos se calcula ahora en la base
(`app/api/controllers/movimiento_sql.py`) en vez de en Python, porque la versión
en Python traía TODAS las respuestas y answers a memoria y con eso tumbó el
servidor en producción. El camino viejo sigue en el código como red de seguridad.

Este script siembra datos con de todo —dos formatos, alias de columna, alias de
formato, repetidores (misma pregunta varias veces en un envío), números con
separadores y con signo de peso, valores vacíos, archivos adjuntos, fechas
repartidas— corre las DOS implementaciones con doce combinaciones de filtros y
compara campo por campo: columnas, filas, totales, valores de los desplegables,
alias, formatos y paginación. Al final mide tiempo y memoria de las dos.

Todo ocurre dentro de una transacción que se revierte: la base local queda igual.

Cómo se corre
─────────────
    cd forms_sfisas_backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/comparar_consolidado_movimiento.py

Última corrida (25-09-2026, 8.060 envíos / 48.438 answers):
    las doce combinaciones dieron IGUAL, la exportación también (8.060 filas),
    y la petición de una página pasó de 3.292 ms / 37,1 MB a 536 ms / 0,7 MB.

Dos diferencias a propósito, documentadas:
  · el orden de `forms` ahora es el de los formatos como se eligieron al crear
    la vista (antes lo decidía la base);
  · cuando dos envíos tienen EXACTAMENTE la misma fecha y hora, el desempate es
    por id de respuesta (antes dependía del orden de los formatos).
"""

import json
import os
import time
import tracemalloc
from datetime import datetime

os.environ["DATABASE_URL"] = "postgresql://postgres:admin@localhost:5432/forms_sfisas"

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.api.endpoints.forms as F
from app.api.controllers.movimiento_sql import ConsolidadoSQL
from app.models import Form, Question, User

e = create_engine(os.environ["DATABASE_URL"])
db = sessionmaker(bind=e)()


class Mov:
    pass


def normalizar(x):
    """Para comparar: fechas a texto y numeros a float redondeado."""
    if isinstance(x, dict):
        return {k: normalizar(v) for k, v in x.items()}
    if isinstance(x, list):
        return [normalizar(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return round(float(x), 6)
    if x is None:
        return None
    return str(x)


# `columns[].form_id/form_title` se compara aparte: la version vieja tomaba el
# formato de la PRIMERA fila donde aparecia la pregunta —o sea, el que la base
# devolviera primero— y la nueva usa el menor id, que es determinista. Solo se
# nota cuando la MISMA pregunta vive en dos formatos de la vista, que es lo que
# hace esta prueba a proposito.
IGNORAR_EN_COLUMNAS = ("form_id", "form_title")


def sin_formato(columnas):
    return [{k: v for k, v in c.items() if k not in IGNORAR_EN_COLUMNAS} for c in columnas]


def primera_diferencia(va, vb):
    def corto(x):
        return json.dumps(x, ensure_ascii=False)[:300]

    if isinstance(va, list) and isinstance(vb, list):
        if len(va) != len(vb):
            return 'largo %d contra %d' % (len(va), len(vb))
        for i, (x, y) in enumerate(zip(va, vb)):
            if x != y:
                return ('en la posicion %d:\n           viejo=%s\n           nuevo=%s'
                        % (i, corto(x), corto(y)))
        return 'iguales'
    if isinstance(va, dict) and isinstance(vb, dict):
        for k in sorted(set(va) | set(vb)):
            if va.get(k) != vb.get(k):
                return ('en la llave %r:\n           viejo=%s\n           nuevo=%s'
                        % (k, corto(va.get(k)), corto(vb.get(k))))
        return 'iguales'
    return 'viejo=%r nuevo=%r' % (va, vb)


def comparar(etiqueta, viejo, nuevo):
    a, b = normalizar(viejo), normalizar(nuevo)
    a["columns"], b["columns"] = sin_formato(a.get("columns", [])), sin_formato(b.get("columns", []))
    # El orden de `forms` cambia a proposito (ver nota al final), se compara
    # como conjunto.
    porid = lambda fs: sorted(fs, key=lambda f: f.get("form_id"))
    a["forms"], b["forms"] = porid(a.get("forms", [])), porid(b.get("forms", []))
    diferencias = []
    for llave in ("columns", "rows", "totals", "distinct", "aliases", "pagination", "forms"):
        if a.get(llave) != b.get(llave):
            diferencias.append(llave)
    if not diferencias:
        print(f"  OK   {etiqueta}")
        return True
    print(f"  MAL  {etiqueta}  -> difiere en: {', '.join(diferencias)}")
    for llave in diferencias:
        print(f"         {llave}: {primera_diferencia(a.get(llave), b.get(llave))}")
    return False


try:
    forms = db.query(Form.id, Form.title).order_by(Form.id).limit(2).all()
    f1, f2 = int(forms[0][0]), int(forms[-1][0])
    user_id = db.query(User.id).first()[0]
    qs = [int(r[0]) for r in db.query(Question.id).order_by(Question.id).limit(7).all()]
    q_texto, q_num, q_rep, q_alias1, q_alias2, q_vacio, q_extra = qs

    # ── Diseños con etiquetas propias, para probar que se usan ──────────────
    for fid in {f1, f2}:
        diseno = [{"id_question": q, "props": {"label": f"Etiqueta {q}"}} for q in qs]
        db.execute(text("UPDATE forms SET form_design = :d WHERE id = :f"),
                   {"d": json.dumps(diseno), "f": fid})

    # ── Envíos ─────────────────────────────────────────────────────────────
    #  · 40 en el formato 1, 20 en el formato 2
    #  · fechas repartidas en días distintos
    for fid, cuantos, dias in ((f1, 40, 40), (f2, 20, 20)):
        db.execute(text("""
            INSERT INTO responses (form_id, user_id, mode, mode_sequence, status, sync_pendiente, submitted_at)
            SELECT :f, :u, 'test', i, 'submitted', false,
                   (now() - (i || ' days')::interval - (:f || ' seconds')::interval)
            FROM generate_series(1, :n) i
        """), {"f": fid, "u": user_id, "n": cuantos})

    ids = [int(r[0]) for r in db.execute(text(
        "SELECT id FROM responses WHERE form_id = ANY(:fs) AND mode='test' ORDER BY id"),
        {"fs": [f1, f2]}).all()]

    # texto, número con separadores, vacío, y una pregunta con DOS respuestas
    # en el mismo envío (como un repetidor) para probar el "gana la última".
    for i, rid in enumerate(ids):
        db.execute(text("""
            INSERT INTO answers (response_id, question_id, answer_text, file_path) VALUES
                (:r, :q_texto, :texto, NULL),
                (:r, :q_num,   :numero, NULL),
                (:r, :q_rep,   :rep1, NULL),
                (:r, :q_rep,   :rep2, NULL),
                (:r, :q_alias1, :al1, NULL),
                (:r, :q_alias2, :al2, NULL),
                (:r, :q_vacio, :vacio, :archivo)
        """), {
            "r": rid, "q_texto": q_texto, "q_num": q_num, "q_rep": q_rep,
            "q_alias1": q_alias1, "q_alias2": q_alias2, "q_vacio": q_vacio,
            "texto": ["ALFA", "BETA", "GAMMA", ""][i % 4],
            "numero": ["1.234,50", "$ 2.000", "abc", "15"][i % 4],
            "rep1": f"fila-1-{i}",
            "rep2": f"fila-2-{i}",
            "al1": ["norte", "sur"][i % 2],
            "al2": ["oriente", "occidente"][i % 2],
            "vacio": None if i % 3 == 0 else f"con valor {i}",
            "archivo": None if i % 2 else f"/archivos/doc-{i}.pdf",
        })
    db.flush()
    db.execute(text("ANALYZE answers"))
    db.execute(text("ANALYZE responses"))

    mov = Mov()
    mov.id = 999
    mov.title = "prueba"
    mov.description = None
    mov.form_ids = [f1, f2]
    # El orden ELEGIDO, distinto del orden de ids, para probar el ordenamiento.
    mov.question_ids = [q_num, q_texto, q_alias1, q_alias2, q_rep, q_vacio]
    mov.alias_groups = [{"name": "Zona", "description": "une dos", "question_ids": [q_alias1, q_alias2]}]
    mov.form_aliases = [{"form_id": f2, "alias": "Formato Dos (alias)"}]

    etiquetas, titulos = F._etiquetas_y_titulos(db, mov)

    def viejo(**kw):
        res = F._collect_movimiento_result(db, mov)
        return F._build_movimiento_consolidado(
            res,
            kw.get("page", 1), kw.get("page_size", 50),
            kw.get("date_from"), kw.get("date_to"), kw.get("search"),
            kw.get("alias"), kw.get("last_only", False),
            cap=kw.get("cap", 200),
            column_filters=kw.get("column_filters"),
            orden_preguntas=mov.question_ids,
        )

    def nuevo(**kw):
        return ConsolidadoSQL(
            db, mov, etiquetas, titulos,
            page=kw.get("page", 1), page_size=kw.get("page_size", 50),
            date_from=kw.get("date_from"), date_to=kw.get("date_to"),
            search=kw.get("search"), alias=kw.get("alias"),
            last_only=kw.get("last_only", False),
            cap=kw.get("cap", 200),
            column_filters=kw.get("column_filters"),
        ).calcular()

    hoy = datetime.now()
    casos = [
        ("sin filtros", {}),
        ("pagina 2 de 10", {"page": 2, "page_size": 10}),
        ("buscar 'ALFA'", {"search": "ALFA"}),
        ("rango de fechas", {"date_from": (hoy.replace(microsecond=0)).strftime("%Y-%m-%dT00:00:00"), "date_to": None}),
        ("desde hace 10 dias", {"date_from": (hoy.replace(microsecond=0)).strftime("%Y-%m-%dT00:00:00")}),
        ("solo el mas reciente", {"last_only": True}),
        ("filtro de alias Zona", {"alias": "Zona"}),
        ("filtro por columna texto", {"column_filters": {f"q:{q_texto}": ["ALFA", "BETA"]}}),
        ("filtro por columna vacia", {"column_filters": {f"q:{q_vacio}": [""]}}),
        ("filtro por __fecha y texto", {"column_filters": {
            "__fecha": [(hoy).strftime("%Y-%m-%d")], f"q:{q_texto}": ["ALFA", "BETA", "GAMMA", ""]}}),
        ("filtro por __form", {"column_filters": {"__form": ["Formato Dos (alias)"]}}),
        ("dos filtros de columna", {"column_filters": {
            f"q:{q_texto}": ["ALFA"], f"alias:Zona": ["norte", "sur"]}}),
    ]

    print(f"datos: {len(ids)} envios, {len(ids)*7} answers, 2 formatos, 1 alias de columna")
    print()
    todo_bien = True
    for etiqueta, kw in casos:
        todo_bien &= comparar(etiqueta, viejo(**kw), nuevo(**kw))

    print()
    print("TODAS IGUALES" if todo_bien else "HAY DIFERENCIAS")

    # ── Memoria y tiempo con un formato grande ──────────────────────────────
    print()
    db.execute(text("""
        INSERT INTO responses (form_id, user_id, mode, mode_sequence, status, sync_pendiente, submitted_at)
        SELECT :f, :u, 'test', 1000 + i, 'submitted', false, now() - (i || ' minutes')::interval
        FROM generate_series(1, 8000) i
    """), {"f": f1, "u": user_id})
    db.execute(text("""
        INSERT INTO answers (response_id, question_id, answer_text)
        SELECT r.id, q, 'valor ' || r.id || '-' || q
        FROM responses r, unnest(CAST(:qs AS bigint[])) q
        WHERE r.form_id = :f AND r.mode = 'test' AND r.mode_sequence > 1000
    """), {"qs": mov.question_ids, "f": f1})
    db.flush(); db.execute(text("ANALYZE answers"))
    total = db.execute(text("SELECT count(*) FROM answers")).scalar()
    print(f"escenario grande: {total} answers en la tabla")

    # El caso de la EXPORTACION: todas las filas, sin paginar.
    print()
    print('exportacion (todas las filas):')
    exp_viejo = viejo(page=1, page_size=10**9, cap=10**9)
    exp_nuevo = nuevo(page=1, page_size=10**9, cap=10**9)
    print('  mismas filas:', len(exp_viejo['rows']) == len(exp_nuevo['rows']),
          '| viejo', len(exp_viejo['rows']), '| nuevo', len(exp_nuevo['rows']))
    print('  mismos totales:', normalizar(exp_viejo['totals']) == normalizar(exp_nuevo['totals']),
          '|', normalizar(exp_nuevo['totals']))

    print()
    for etiqueta, fn in (("VIEJO (Python)", viejo), ("NUEVO (SQL)", nuevo)):
        db.expire_all()
        tracemalloc.start()
        t = time.perf_counter()
        res = fn(page=1, page_size=50)
        ms = (time.perf_counter() - t) * 1000
        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print("  %-16s %8.0f ms | pico %6.1f MB | filas de la pagina %d de %d" % (
            etiqueta, ms, pico / 1024 / 1024, len(res["rows"]),
            res["pagination"]["total_rows"]))

finally:
    db.rollback()
    db.close()
print("(revertido)")
