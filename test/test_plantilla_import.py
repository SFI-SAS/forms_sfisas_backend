"""Pruebas de la lectura de plantillas (sin base de datos).

    python -m pytest test/test_plantilla_import.py -q      (o: python test/test_plantilla_import.py)
"""
import os
import sys
from datetime import datetime
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import Workbook  # noqa: E402

from app.core.plantilla_import import (  # noqa: E402
    calcular_formula, campos_del_diseno, leer_plantilla, normalizar_fecha, numero_js,
    parse_numero, valor_a_texto,
)

DISENO = [
    {"id": "e-cod", "type": "input", "id_question": 10, "props": {"label": "Código", "required": True}},
    {"id": "e-pre", "type": "input", "id_question": 11, "props": {"label": "Precio", "numberFormat": "currency"}},
    {"id": "e-fec", "type": "date", "id_question": 12, "props": {"label": "Fecha"}},
    {"id": "h1", "type": "horizontalLayout", "children": [
        {"id": "e-est", "type": "select", "id_question": 13, "props": {"label": "Estado", "options": ["VIGENTE", "OBSOLETO"]}},
    ]},
    {"id": "rep", "type": "repeater", "props": {"label": "MATERIALES"}, "children": [
        {"id": "e-can", "type": "input", "linkExternalId": 20, "props": {"label": "Cantidad", "numberFormat": "thousands"}},
        {"id": "e-par", "type": "mathoperations", "linkExternalId": 21, "props": {"label": "Parcial"}},
    ]},
]


def _xlsx(filas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Plantilla"
    for f in filas:
        ws.append(f)
    b = BytesIO()
    wb.save(b)
    return b.getvalue()


def test_fechas_como_el_front():
    assert normalizar_fecha("date", datetime(2026, 9, 26)) == ("26/09/2026", True)
    assert normalizar_fecha("date", "2026-09-26") == ("26/09/2026", True)
    assert normalizar_fecha("date", "5/9/2026") == ("05/09/2026", True)
    assert normalizar_fecha("datetime", datetime(2026, 9, 14, 23, 59, 59, 900000)) == ("15/09/2026 00:00", True)
    assert normalizar_fecha("date", 46291) == ("26/09/2026", True)          # serial de Excel
    assert normalizar_fecha("date", "mañana")[1] is False


def test_numeros():
    assert numero_js(2880.0) == "2880" and numero_js(0.0125) == "0.0125"
    assert parse_numero("12.345,67") == 12345.67
    assert parse_numero("41.000") == 41000 and parse_numero("0.075") == 0.075
    assert parse_numero("30 %") == 0.3 and parse_numero("COP $ 1.234") == 1234
    assert parse_numero("abc") is None
    campos = {c.element_id: c for c in campos_del_diseno(DISENO)}
    assert valor_a_texto(campos["e-pre"], 12345.67) == ("12345,67", None)   # coma decimal
    assert valor_a_texto(campos["e-cod"], 123) == ("123", None)
    assert valor_a_texto(campos["e-pre"], "doce")[1] == "numero_invalido"


def test_leer_plantilla_con_repetidor():
    campos = campos_del_diseno(DISENO)
    assert [c.element_id for c in campos] == ["e-cod", "e-pre", "e-fec", "e-est", "e-can", "e-par"]
    assert campos[4].repetidor == "rep" and campos[4].question_id == 20
    contenido = _xlsx([
        ["ID Pregunta", None, 10, 11, 12, 13, 20, 999],
        ["Tipo", None, "input", "input", "date", "select", "input", "input"],
        ["Nivel", None, "", "", "", "", "rep", ""],
        ["Pregunta", None, "Código", "Precio", "Fecha", "Estado", "Cantidad", "Viejo"],
        ["Envío 1", None, "MAT-1", 2880, datetime(2026, 9, 26), "vigente", 2, None],
        ["  ↳ Fila 2", None, None, None, None, None, 0.5, None],
        ["Envío 2", None, None, None, None, None, None, None],          # vacío: se ignora
        ["Envío 3", None, "MAT-2", 10, None, "OBSOLETO", None, None],
        ["Instrucciones", None, None, None, None, None, None, None],
    ])
    p = leer_plantilla(contenido, campos)
    assert len(p.registros) == 2 and p.ids_sin_campo == ["999"] and p.etiquetas_raras == 1
    r = p.registros[0]
    assert r.normal["e-cod"] == "MAT-1" and r.filas["rep"] == [{"e-can": 2}, {"e-can": 0.5}]
    assert r.fila_de[("rep", 1)] == 6 and p.registros[1].fila_excel == 8


def test_formulas():
    assert calcular_formula("{1} * {2}", {1: 100000.0, 2: 1.75}.get) == 175000.0
    assert calcular_formula("+{5}", {5: [154.32, 24691.34]}.get) == 154.32 + 24691.34   # suma de columna
    assert calcular_formula("{1} - {9}", {1: 3.0}.get) == 3.0                           # falta -> 0
    assert calcular_formula("{1} / {2}", {1: 1.0, 2: 0.0}.get) is None                  # sin división por cero
    assert calcular_formula("__import__('os')", {}.get) is None                         # nada de código


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("OK")
