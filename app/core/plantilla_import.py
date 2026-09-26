"""
Lectura de la plantilla Excel de un formato (la que baja "Descargar plantilla"
o "export-template-excel") para cargarla de un golpe en el backend.

Es el espejo de `handleUploadTemplate` + `buildResponses` del frontend
(ListForms.tsx) y de `normalizarValorExcel` (lib/excelDateValues.ts): mismas
filas de encabezado, mismas marcas de "Envío N / ↳ Fila N / ↳ Sub N", mismo
formato de fecha al guardar. Aquí NO hay base de datos: todo es puro para
poder probarlo sin servidor (ver test/test_plantilla_import.py).
"""
from __future__ import annotations

import ast
import operator
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Any, Optional

# Tipos del diseño que no se diligencian (o que no se pueden cargar desde un Excel).
TIPOS_SIN_VALOR = {"horizontalLayout", "verticalLayout", "label", "helpText", "divider",
                   "button", "image", ""}
TIPOS_NO_IMPORTABLES = {"file", "firm", "regisfacial", "signature"}
TIPOS_FECHA = {"date", "datetime", "time"}
FORMATOS_NUMERICOS = {"thousands", "currency", "percent"}

ENVIO_RE = re.compile(r"^env[ií]o\s+\d+", re.I)
RESPUESTA_RE = re.compile(r"^respuesta", re.I)
FILA_RE = re.compile(r"↳\s*fila\s+(\d+)", re.I)
SUB_RE = re.compile(r"↳\s*sub\s+(\d+)", re.I)


# ── Diseño ───────────────────────────────────────────────────────────────────

@dataclass
class Campo:
    element_id: str
    question_id: Optional[int]      # el que se guarda (linkExternalId || id_question)
    tipo: str
    etiqueta: str
    props: dict
    repetidor: Optional[str] = None  # id del repetidor padre
    sub: Optional[str] = None        # id del sub-repetidor

    @property
    def es_numerico(self) -> bool:
        return self.tipo == "number" or (self.props.get("numberFormat") in FORMATOS_NUMERICOS)

    @property
    def opciones(self) -> list[str]:
        salida = []
        for o in self.props.get("options") or []:
            if isinstance(o, dict):
                o = o.get("value", o.get("label"))
            if o is not None and str(o).strip():
                salida.append(str(o).strip())
        return salida


def _qid(item: dict) -> Optional[int]:
    """Igual que el front: `linkExternalId || id_question || id`."""
    for k in ("linkExternalId", "id_question"):
        v = item.get(k)
        if v not in (None, ""):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


def campos_del_diseno(form_design: list) -> list[Campo]:
    """Todos los campos diligenciables del diseño, en orden, con su repetidor."""
    campos: list[Campo] = []

    def walk(items, rep=None, sub=None):
        for it in items or []:
            if not isinstance(it, dict):
                continue
            t = it.get("type") or ""
            if t in ("horizontalLayout", "verticalLayout"):
                walk(it.get("children"), rep, sub)
            elif t == "repeater":
                if rep:
                    walk(it.get("children"), rep, it.get("id"))
                else:
                    walk(it.get("children"), it.get("id"), None)
            elif t not in TIPOS_SIN_VALOR:
                campos.append(Campo(
                    element_id=it.get("id") or "", question_id=_qid(it), tipo=t,
                    etiqueta=(it.get("props") or {}).get("label") or "Campo",
                    props=it.get("props") or {}, repetidor=rep, sub=sub,
                ))

    walk(form_design)
    return campos


# ── Valores ──────────────────────────────────────────────────────────────────

def sin_tildes(texto: str) -> str:
    """Para comparar opciones: sin tildes, sin mayúsculas, sin espacios de sobra."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(t.casefold().split())


def _dos(n: int) -> str:
    return f"{n:02d}"


def _redondear_minuto(d: datetime) -> datetime:
    # Mismo motivo que en el front: la fracción de segundo corre la fecha un día.
    return (d + timedelta(seconds=30)).replace(second=0, microsecond=0)


def _desde_serial(serial: float) -> Optional[datetime]:
    if serial < 0:
        return None
    return _redondear_minuto(datetime(1899, 12, 30) + timedelta(days=serial))


def normalizar_fecha(tipo: str, valor: Any) -> tuple[Optional[str], bool]:
    """Valor de celda → como se GUARDA una fecha (dd/mm/aaaa [HH:MM] o HH:MM).
    Devuelve (texto, ok). Si no se reconoce, (texto crudo, False)."""
    d: Optional[datetime] = None
    if isinstance(valor, datetime):
        d = _redondear_minuto(valor)
    elif isinstance(valor, date):
        d = datetime(valor.year, valor.month, valor.day)
    elif isinstance(valor, time):
        return f"{_dos(valor.hour)}:{_dos(valor.minute)}", True
    elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
        d = _desde_serial(float(valor))
    else:
        t = str(valor).strip()
        if re.fullmatch(r"\d+(\.\d+)?", t):
            d = _desde_serial(float(t))
        elif tipo == "time" and re.fullmatch(r"\d{1,2}:\d{2}", t):
            h, m = t.split(":")
            return f"{_dos(int(h))}:{m}", True
        else:
            m = (re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2})(?::\d{2})?)?", t)
                 or None)
            if m:
                y, mo, dd, hh, mi = m.groups()
            else:
                m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:[ T](\d{1,2}):(\d{2}))?", t)
                if not m:
                    return t, False
                dd, mo, y, hh, mi = m.groups()
            try:
                d = datetime(int(y), int(mo), int(dd), int(hh or 0), int(mi or 0))
            except ValueError:
                return t, False
    if d is None:
        return str(valor), False
    if tipo == "time":
        return f"{_dos(d.hour)}:{_dos(d.minute)}", True
    fecha = f"{_dos(d.day)}/{_dos(d.month)}/{d.year}"
    if tipo == "datetime":
        return f"{fecha} {_dos(d.hour)}:{_dos(d.minute)}", True
    return fecha, True


def numero_js(n: float) -> str:
    """Un número como lo escribe `String(n)` en JavaScript (2880, no 2880.0)."""
    if isinstance(n, bool):
        return str(n).lower()
    if isinstance(n, int) or (isinstance(n, float) and n.is_integer() and abs(n) < 1e15):
        return str(int(n))
    return repr(float(n))


def parse_numero(valor: Any) -> Optional[float]:
    """Port de `parseNumeroFormateado` (lib/numberFormat.ts): punto de miles,
    coma decimal, "30 %" vale 0,3, "COP $ 1.234" vale 1234. None si no es número."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    t = str(valor or "").strip()
    if not t:
        return None
    pct = "%" in t
    t = t.replace("%", "")
    t = re.sub(r"[A-Z]{3}", "", t)
    t = re.sub(r"[$€£¥₹\s]", "", t)
    if not t:
        return None
    neg = t.startswith("-")
    if neg:
        t = t[1:]
    if "," in t:
        t = t.replace(".", "").replace(",", ".", 1)
    elif re.fullmatch(r"(?!0\.)\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        n = float(t)
    except ValueError:
        return None
    n = -n if neg else n
    return n / 100 if pct else n


def valor_a_texto(campo: Campo, valor: Any) -> tuple[str, Optional[str]]:
    """Celda → texto a guardar + problema (None si está bien)."""
    if campo.tipo in TIPOS_FECHA:
        texto, ok = normalizar_fecha(campo.tipo, valor)
        return (texto or ""), (None if ok else "fecha_invalida")
    if isinstance(valor, bool):
        return ("true" if valor else "false"), None
    if isinstance(valor, (int, float)):
        texto = numero_js(valor)
        # Un campo numérico se guarda como se TECLEA en Safemetrics: coma decimal.
        # Así "123.456" nunca se confunde con miles al hacer cuentas.
        return (texto.replace(".", ",") if campo.es_numerico else texto), None
    if isinstance(valor, datetime):  # fecha en un campo que no es de fecha
        return normalizar_fecha("datetime" if (valor.hour or valor.minute) else "date", valor)[0], None
    texto = str(valor).strip()
    if campo.es_numerico and texto and parse_numero(texto) is None:
        return texto, "numero_invalido"
    return texto, None


# ── Plantilla ────────────────────────────────────────────────────────────────

@dataclass
class Registro:
    fila_excel: int                                 # fila (1-based) donde empieza el "Envío"
    etiqueta: str
    normal: dict = field(default_factory=dict)      # element_id -> valor crudo
    filas: dict = field(default_factory=dict)       # rep_id -> [ {element_id: valor} ]
    subfilas: dict = field(default_factory=dict)    # (rep_id, fila, sub_id) -> [ {element_id: valor} ]
    fila_de: dict = field(default_factory=dict)     # (rep_id, fila) -> fila excel (para errores)


@dataclass
class Columna:
    indice: int
    campo: Campo


@dataclass
class Plantilla:
    columnas: list[Columna]
    registros: list[Registro]
    ids_sin_campo: list[str]       # IDs de pregunta de la plantilla que el formato ya no tiene
    etiquetas_raras: int           # filas con etiqueta que no es Envío/Fila/Sub


class PlantillaInvalida(ValueError):
    pass


def _vacio(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def leer_plantilla(contenido: bytes, campos: list[Campo]) -> Plantilla:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(BytesIO(contenido), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - cualquier cosa que no sea un xlsx
        raise PlantillaInvalida(f"El archivo no es un Excel válido ({e.__class__.__name__}).")
    if "Plantilla" not in wb.sheetnames:
        raise PlantillaInvalida(
            "El Excel no tiene la hoja 'Plantilla'. Hay que usar la plantilla que se "
            "descarga del formato, sin cambiarle el nombre a la hoja.")
    filas = list(wb["Plantilla"].iter_rows(values_only=True))
    wb.close()
    if len(filas) < 5:
        raise PlantillaInvalida("La plantilla no tiene filas de datos (empiezan en la fila 5).")

    ids = filas[0]
    por_qid = {c.question_id: c for c in campos if c.question_id is not None}
    columnas: list[Columna] = []
    sin_campo: list[str] = []
    for i, raw in enumerate(ids):
        if i < 2 or _vacio(raw):
            continue
        try:
            qid = int(float(raw))
        except (TypeError, ValueError):
            sin_campo.append(str(raw)); continue
        campo = por_qid.get(qid)
        if not campo:
            sin_campo.append(str(qid)); continue
        # El repetidor de cada columna se toma del DISEÑO, no de la fila "Nivel":
        # si el formato cambió desde que se bajó la plantilla, manda el formato.
        columnas.append(Columna(i, campo))

    if not columnas:
        raise PlantillaInvalida(
            "Ninguna columna de la plantilla corresponde a este formato. ¿Es la "
            "plantilla de otro formato?")

    registros: list[Registro] = []
    actual: Optional[Registro] = None
    fila_rep = 0
    raras = 0

    def escribir(col: Columna, v: Any, fila_rep: int, fila_sub: int, n_excel: int):
        c = col.campo
        if _vacio(v):
            return
        if c.sub:
            clave = (c.repetidor, fila_rep, c.sub)
            lista = actual.subfilas.setdefault(clave, [])
            while len(lista) <= fila_sub:
                lista.append({})
            lista[fila_sub][c.element_id] = v
        elif c.repetidor:
            lista = actual.filas.setdefault(c.repetidor, [])
            while len(lista) <= fila_rep:
                lista.append({})
            lista[fila_rep][c.element_id] = v
            actual.fila_de.setdefault((c.repetidor, fila_rep), n_excel)
        else:
            actual.normal[c.element_id] = v

    for n, fila in enumerate(filas[4:], start=5):
        etiqueta = str(fila[0] if fila and fila[0] is not None else "").strip()
        if not etiqueta:
            continue
        tiene = any(not _vacio(fila[c.indice]) for c in columnas if c.indice < len(fila))
        if ENVIO_RE.match(etiqueta) or RESPUESTA_RE.match(etiqueta):
            if not tiene:
                actual = None
                continue
            actual = Registro(fila_excel=n, etiqueta=etiqueta)
            registros.append(actual)
            fila_rep = 0
            for col in columnas:
                if col.indice < len(fila):
                    escribir(col, fila[col.indice], 0, 0, n)
        elif (m := FILA_RE.search(etiqueta)) and actual:
            fila_rep = int(m.group(1)) - 1
            for col in columnas:
                if col.campo.repetidor and col.indice < len(fila):
                    escribir(col, fila[col.indice], fila_rep, 0, n)
        elif (m := SUB_RE.search(etiqueta)) and actual:
            fila_sub = int(m.group(1)) - 1
            for col in columnas:
                if col.campo.sub and col.indice < len(fila):
                    escribir(col, fila[col.indice], fila_rep, fila_sub, n)
        else:
            raras += 1

    return Plantilla(columnas, registros, sin_campo, raras)


# ── Fórmulas ─────────────────────────────────────────────────────────────────

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def evaluar(expr: str) -> Optional[float]:
    """Aritmética segura (+ - * / % ** y paréntesis). None si no se puede."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        raise ValueError("expresión no permitida")
    try:
        r = ev(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError):
        return None
    return r if r == r and r not in (float("inf"), float("-inf")) else None


FORMULA_ID_RE = re.compile(r"\{\s*(\d+)\s*\}")


def calcular_formula(operacion: str, valor_de) -> Optional[float]:
    """`operacion` = "{2950} * {2951}"; `valor_de(qid)` → número (o lista para
    columnas de repetidor, que se suman: así funciona "+{id}" en el front)."""
    def sustituir(m):
        v = valor_de(int(m.group(1)))
        if isinstance(v, list):
            v = sum(x for x in v if x is not None)
        return f"({repr(float(v))})" if v is not None else "(0.0)"
    return evaluar(FORMULA_ID_RE.sub(sustituir, operacion))
