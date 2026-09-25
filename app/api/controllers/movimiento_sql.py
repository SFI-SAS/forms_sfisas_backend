"""Consolidado de una vista conjunta (movimiento), calculado EN LA BASE.

Por qué existe
──────────────
La versión en Python traía a memoria TODAS las respuestas y TODAS las answers de
todos los formatos de la vista, las convertía en diccionarios, y solo entonces
filtraba, totalizaba y paginaba. Medido en local, una vista de 10.000 envíos ×
6 preguntas (60.000 answers) costaba ~47 MB de objetos Python por petición; con
tres o cuatro peticiones a la vez el servidor se queda sin RAM (pasó el
25-09-2026 en producción).

Aquí se hace al revés: la base filtra, agrupa, totaliza y pagina, y a Python solo
llegan las filas de la página pedida (50 por defecto) más un puñado de
agregados. La memoria deja de depender del tamaño del formato.

Cómo se arma
────────────
Una CTE `base` convierte cada envío en UNA fila, con sus respuestas en un objeto
JSON `{question_id: valor}`. Sobre esa CTE se resuelve todo:

  · los filtros de fecha, de búsqueda y por columna,
  · `COUNT` para la paginación,
  · `SUM` para los totales de las columnas numéricas,
  · `DISTINCT` para los desplegables de cada columna,
  · y un `LIMIT/OFFSET` para las filas de la página.

El resultado tiene EXACTAMENTE la misma forma que devolvía la versión en Python
—mismas llaves, mismo criterio para el valor de cada celda, mismos totales—
porque el cliente ya está escrito contra ella. Hay una prueba que compara las
dos salidas campo por campo.

Reglas que se replican (y que no son obvias)
────────────────────────────────────────────
  · El valor de una celda es el de la PRIMERA pregunta de la columna que exista
    en el envío (una columna de alias fusiona varias). "Que exista" es que la
    llave esté, aunque su valor sea NULL.
  · Cuando una pregunta tiene varias respuestas en el mismo envío (repetidores),
    gana la ÚLTIMA por id de answer.
  · Los valores de los desplegables van EN CASCADA: para cada columna se aplican
    los filtros de las OTRAS columnas, no el suyo.
  · Un total solo aparece si la columna tuvo al menos un valor numérico.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Texto → número, con la misma tolerancia que `_movimiento_to_number`
# ─────────────────────────────────────────────────────────────────────────────
#
# Quita el signo de peso y los espacios; si hay coma Y punto, el punto es de
# miles; si solo hay coma, es el decimal. Lo que no quede como un número se
# ignora (NULL), igual que en Python, donde `float()` lanzaba y se devolvía None.
def _expr_numero(expr_texto: str) -> str:
    """El convertidor de arriba, aplicado a una expresión de texto cualquiera."""
    limpio = f"replace(replace(btrim({expr_texto}), '$', ''), ' ', '')"
    normalizado = (
        "CASE"
        f" WHEN {limpio} LIKE '%,%' AND {limpio} LIKE '%.%'"
        f" THEN replace(replace({limpio}, '.', ''), ',', '.')"
        f" WHEN {limpio} LIKE '%,%' THEN replace({limpio}, ',', '.')"
        f" ELSE {limpio} END"
    )
    return (
        f"CASE WHEN ({normalizado}) ~ '^[-+]?[0-9]*[.]?[0-9]+([eE][-+]?[0-9]+)?$'"
        f" THEN ({normalizado})::numeric ELSE NULL END"
    )


def _expr_valor_de_columna(question_ids: List[int]) -> str:
    """Valor de una celda: la PRIMERA pregunta de la columna que exista en el envío.

    Se mira la existencia de la llave (`?`), no que tenga valor: una respuesta
    guardada como NULL igual "ocupa" la columna, como en la versión en Python.
    """
    if not question_ids:
        return "NULL"
    ramas = " ".join(
        f"WHEN b.valores ? '{int(qid)}' THEN b.valores->>'{int(qid)}'"
        for qid in question_ids
    )
    return f"CASE {ramas} ELSE NULL END"


def _expr_archivo_de_columna(question_ids: List[int]) -> str:
    """Igual que el valor, pero del archivo adjunto de esa misma pregunta."""
    if not question_ids:
        return "NULL"
    ramas = " ".join(
        f"WHEN b.valores ? '{int(qid)}' THEN b.archivos->>'{int(qid)}'"
        for qid in question_ids
    )
    return f"CASE {ramas} ELSE NULL END"


class ConsolidadoSQL:
    """Arma el consolidado de un movimiento con consultas a la base.

    Se usa así:
        ConsolidadoSQL(db, movimiento, ...).calcular()
    """

    def __init__(
        self,
        db: Session,
        movimiento,
        etiquetas_por_pregunta: Dict[int, str],
        titulos_de_formato: Dict[int, str],
        page: int = 1,
        page_size: int = 50,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search: Optional[str] = None,
        alias: Optional[str] = None,
        last_only: bool = False,
        cap: int = 200,
        column_filters: Optional[Dict[str, List[str]]] = None,
    ):
        self.db = db
        self.mov = movimiento
        self.etiquetas = etiquetas_por_pregunta or {}
        self.titulos = titulos_de_formato or {}
        self.page = max(1, page or 1)
        self.page_size = min(cap, max(1, page_size or 50))
        self.date_from = date_from
        self.date_to = date_to
        self.search = (search or "").strip()
        self.alias = alias
        self.last_only = bool(last_only)
        self.cf = {k: list(v) for k, v in (column_filters or {}).items() if v}

        self.form_ids = [int(f) for f in (self.mov.form_ids or [])]
        self.question_ids = [int(q) for q in (self.mov.question_ids or [])]

        # Alias por movimiento: nombre → question_ids que fusiona.
        self.alias_por_pregunta: Dict[int, Dict[str, Any]] = {}
        for grupo in (self.mov.alias_groups or []):
            nombre = (grupo.get("name") or "").strip()
            if not nombre:
                continue
            for qid in (grupo.get("question_ids") or []):
                try:
                    self.alias_por_pregunta[int(qid)] = {
                        "name": nombre,
                        "description": grupo.get("description"),
                    }
                except (TypeError, ValueError):
                    continue

        self.alias_por_formato: Dict[int, str] = {}
        for fa in (self.mov.form_aliases or []):
            try:
                if (fa.get("alias") or "").strip():
                    self.alias_por_formato[int(fa["form_id"])] = fa["alias"].strip()
            except (TypeError, ValueError, KeyError):
                continue

        self.columnas: List[Dict[str, Any]] = []

    # ── La CTE base: un envío = una fila ────────────────────────────────────
    def _cte_base(self) -> str:
        """Cada envío con sus respuestas en un JSON, más el texto para buscar.

        `ORDER BY a.id` dentro de los agregados no es decorativo: cuando una
        pregunta tiene varias respuestas en el mismo envío (repetidores), el
        objeto JSON se queda con la última, que es el mismo criterio que usaba
        la versión en Python.
        """
        filtro_reciente = ""
        if self.last_only:
            # "Solo el más reciente" se evalúa sobre TODO el conjunto, antes de
            # los filtros de fecha y búsqueda (igual que antes).
            filtro_reciente = """
                AND r.id = (
                    -- El más reciente DE LOS QUE TIENEN respuestas de este
                    -- movimiento. Mirar solo `responses` podía caer en un envío
                    -- sin ninguna de esas preguntas, y la tabla salía vacía.
                    SELECT r2.id
                    FROM responses r2
                    JOIN answers a2 ON a2.response_id = r2.id
                    WHERE r2.form_id = ANY(:form_ids)
                      AND r2.status = 'submitted'
                      AND a2.question_id = ANY(:question_ids)
                    ORDER BY r2.submitted_at DESC NULLS LAST, r2.id DESC
                    LIMIT 1
                )
            """

        return f"""
            WITH base AS (
                SELECT
                    r.id            AS response_id,
                    r.form_id       AS form_id,
                    r.submitted_at  AS submitted_at,
                    jsonb_object_agg(a.question_id::text, to_jsonb(a.answer_text) ORDER BY a.id)
                                    AS valores,
                    jsonb_object_agg(a.question_id::text, to_jsonb(a.file_path) ORDER BY a.id)
                                    AS archivos,
                    lower(string_agg(coalesce(a.answer_text, ''), ' ')) AS texto_busqueda
                FROM responses r
                JOIN answers a ON a.response_id = r.id
                WHERE r.form_id = ANY(:form_ids)
                  AND r.status = 'submitted'
                  AND a.question_id = ANY(:question_ids)
                  {filtro_reciente}
                GROUP BY r.id, r.form_id, r.submitted_at
            )
        """

    def _condiciones_de_fecha_y_texto(self) -> str:
        cond = []
        if self.date_from:
            cond.append("b.submitted_at >= :date_from")
        if self.date_to:
            cond.append("b.submitted_at <= :date_to")
        if self.search:
            cond.append("b.texto_busqueda LIKE :search")
        return (" AND " + " AND ".join(cond)) if cond else ""

    # ── Columnas ───────────────────────────────────────────────────────────
    def _cargar_columnas(self) -> None:
        """Las columnas que existen de verdad, en el orden en que se eligieron.

        Solo entran las preguntas que tienen al menos una respuesta, como antes.
        Es una consulta sobre ids: no trae textos de respuesta.
        """
        filas = self.db.execute(
            text("""
                SELECT a.question_id           AS question_id,
                       min(r.form_id)          AS form_id,
                       min(q.question_text)    AS question_text,
                       min(cast(q.question_type AS varchar)) AS question_type
                FROM answers a
                JOIN responses r ON r.id = a.response_id
                JOIN questions q ON q.id = a.question_id
                WHERE r.form_id = ANY(:form_ids)
                  AND r.status = 'submitted'
                  AND a.question_id = ANY(:question_ids)
                GROUP BY a.question_id
            """),
            {"form_ids": self.form_ids, "question_ids": self.question_ids},
        ).all()

        por_pregunta = {int(f.question_id): f for f in filas}

        # Los alias disponibles son los de TODAS las preguntas con respuesta, no
        # solo los de las columnas que queden tras el filtro de alias: el
        # desplegable tiene que seguir ofreciendo los demás.
        self._alias_presentes = sorted({
            self.alias_por_pregunta[qid]["name"]
            for qid in por_pregunta
            if qid in self.alias_por_pregunta
        })

        # Orden: el de `question_ids` del movimiento (como se eligieron al crear
        # la vista). Lo que no esté en la lista va al final.
        orden = {qid: i for i, qid in enumerate(self.question_ids)}
        presentes = sorted(por_pregunta.keys(), key=lambda q: orden.get(q, len(orden)))

        indice_alias: Dict[str, int] = {}
        tipos: Dict[str, set] = {}

        for qid in presentes:
            fila = por_pregunta[qid]
            info_alias = self.alias_por_pregunta.get(qid)
            nombre_alias = info_alias["name"] if info_alias else None
            tipo = fila.question_type or "text"

            if self.alias and nombre_alias != self.alias:
                continue

            if nombre_alias:
                if nombre_alias in indice_alias:
                    col = self.columnas[indice_alias[nombre_alias]]
                    if qid not in col["question_ids"]:
                        col["question_ids"].append(qid)
                else:
                    clave = f"alias:{nombre_alias}"
                    indice_alias[nombre_alias] = len(self.columnas)
                    self.columnas.append({
                        "key": clave,
                        "label": nombre_alias,
                        "is_alias": True,
                        "form_id": None,
                        "form_title": None,
                        "question_ids": [qid],
                    })
                    tipos[clave] = set()
                tipos[f"alias:{nombre_alias}"].add(tipo)
            else:
                clave = f"q:{qid}"
                etiqueta = self.etiquetas.get(qid) or fila.question_text
                self.columnas.append({
                    "key": clave,
                    "label": etiqueta,
                    "is_alias": False,
                    "form_id": int(fila.form_id),
                    "form_title": self.titulos.get(int(fila.form_id)),
                    "question_ids": [qid],
                })
                tipos[clave] = {tipo}

        for col in self.columnas:
            t = tipos.get(col["key"], set())
            if t == {"number"}:
                col["type"] = "number"
            elif len(t) > 1:
                col["type"] = "mixed"
            else:
                col["type"] = next(iter(t)) if t else "text"
            col["totalize"] = col["type"] == "number"

    # ── Filtros por columna ────────────────────────────────────────────────
    def _expr_de_clave(self, clave: str) -> Optional[str]:
        """Expresión SQL con el valor de una columna (o de las dos especiales)."""
        if clave == "__form":
            return "coalesce(nullif(b.form_alias_calc, ''), b.form_title_calc)"
        if clave == "__fecha":
            return "to_char(b.submitted_at, 'YYYY-MM-DD')"
        for col in self.columnas:
            if col["key"] == clave:
                return _expr_valor_de_columna(col["question_ids"])
        return None

    def _condiciones_de_columna(self, excluir: Optional[str]) -> (str, dict):
        """Las condiciones de los filtros por columna, menos la que se excluya."""
        partes: List[str] = []
        params: Dict[str, Any] = {}
        for i, (clave, permitidos) in enumerate(self.cf.items()):
            if clave == excluir:
                continue
            expr = self._expr_de_clave(clave)
            if expr is None:      # columna desconocida: no filtra
                continue
            nombre = f"cf_{i}"
            # `coalesce(..., '')` porque la lista puede traer "" para las vacías.
            partes.append(f"coalesce(btrim({expr}), '') = ANY(:{nombre})")
            params[nombre] = [str(v) for v in permitidos]
        return ((" AND " + " AND ".join(partes)) if partes else ""), params

    # ── Cálculo ────────────────────────────────────────────────────────────
    def _params_base(self) -> dict:
        p = {"form_ids": self.form_ids, "question_ids": self.question_ids}
        if self.date_from:
            p["date_from"] = self.date_from
        if self.date_to:
            p["date_to"] = self.date_to
        if self.search:
            p["search"] = f"%{self.search.lower()}%"
        return p

    def _select_base_con_formato(self) -> str:
        """`base` más el alias/título del formato, que hacen falta para __form."""
        titulos = " ".join(
            f"WHEN {int(fid)} THEN :ft_{int(fid)}" for fid in self.form_ids
        ) or "WHEN NULL THEN NULL"
        alias_f = " ".join(
            f"WHEN {int(fid)} THEN :fa_{int(fid)}" for fid in self.alias_por_formato
        )
        alias_expr = f"CASE b0.form_id {alias_f} ELSE NULL END" if alias_f else "NULL"
        return f"""
            , base_f AS (
                SELECT b0.*,
                       (CASE b0.form_id {titulos} ELSE NULL END) AS form_title_calc,
                       ({alias_expr}) AS form_alias_calc
                FROM base b0
            )
        """

    def _params_de_formato(self) -> dict:
        p = {f"ft_{int(fid)}": self.titulos.get(int(fid)) for fid in self.form_ids}
        p.update({f"fa_{int(fid)}": a for fid, a in self.alias_por_formato.items()})
        return p

    def calcular(self) -> Dict[str, Any]:
        if not self.form_ids or not self.question_ids:
            return {
                "columns": [], "rows": [], "totals": {}, "distinct": {},
                "aliases": [], "forms": [],
                "pagination": {"page": 1, "page_size": self.page_size,
                               "total_rows": 0, "total_pages": 1},
            }

        self._cargar_columnas()

        prefijo = self._cte_base() + self._select_base_con_formato()
        donde_fecha = self._condiciones_de_fecha_y_texto()
        params = {**self._params_base(), **self._params_de_formato()}

        cond_todas, params_cf = self._condiciones_de_columna(None)
        params.update(params_cf)

        # 1) Conteo y totales del conjunto filtrado COMPLETO, en una consulta.
        sumas = []
        for i, col in enumerate(self.columnas):
            if not col["totalize"]:
                continue
            expr = _expr_numero(_expr_valor_de_columna(col["question_ids"]))
            sumas.append(f"sum({expr}) AS total_{i}, count({expr}) AS cuantos_{i}")
        seleccion = ", ".join(["count(*) AS filas"] + sumas)

        agregados = self.db.execute(
            text(f"{prefijo} SELECT {seleccion} FROM base_f b WHERE true {donde_fecha} {cond_todas}"),
            params,
        ).one()

        total_rows = int(agregados.filas or 0)
        totals: Dict[str, Any] = {}
        for i, col in enumerate(self.columnas):
            if not col["totalize"]:
                continue
            cuantos = getattr(agregados, f"cuantos_{i}", 0) or 0
            if cuantos:
                total = getattr(agregados, f"total_{i}")
                totals[col["key"]] = float(total) if total is not None else 0.0

        # 2) Las filas de LA PÁGINA. Es lo único que llega entero a Python.
        total_pages = (total_rows + self.page_size - 1) // self.page_size if total_rows else 1
        offset = (self.page - 1) * self.page_size

        columnas_sql = []
        for i, col in enumerate(self.columnas):
            columnas_sql.append(f"{_expr_valor_de_columna(col['question_ids'])} AS val_{i}")
            columnas_sql.append(f"{_expr_archivo_de_columna(col['question_ids'])} AS arc_{i}")
        select_valores = (", " + ", ".join(columnas_sql)) if columnas_sql else ""

        filas = self.db.execute(
            text(f"""
                {prefijo}
                SELECT b.response_id, b.form_id, b.submitted_at,
                       b.form_title_calc, b.form_alias_calc
                       {select_valores}
                FROM base_f b
                WHERE true {donde_fecha} {cond_todas}
                ORDER BY b.submitted_at ASC NULLS FIRST, b.response_id ASC
                LIMIT :limite OFFSET :salto
            """),
            {**params, "limite": self.page_size, "salto": offset},
        ).all()

        rows_out = []
        for fila in filas:
            valores, archivos = {}, {}
            for i, col in enumerate(self.columnas):
                valores[col["key"]] = getattr(fila, f"val_{i}")
                arc = getattr(fila, f"arc_{i}")
                if arc:
                    archivos[col["key"]] = arc
            rows_out.append({
                "form_id": fila.form_id,
                "form_title": fila.form_title_calc,
                "form_alias": fila.form_alias_calc,
                "response_id": fila.response_id,
                "submitted_at": fila.submitted_at,
                "values": valores,
                "files": archivos,
            })

        # 3) Valores para los desplegables, EN CASCADA (sin el filtro propio).
        distinct: Dict[str, List[str]] = {}
        for col in self.columnas:
            cond_otras, params_otras = self._condiciones_de_columna(col["key"])
            expr = _expr_valor_de_columna(col["question_ids"])
            vals = self.db.execute(
                text(f"""
                    {prefijo}
                    SELECT DISTINCT coalesce(btrim({expr}), '') AS v
                    FROM base_f b
                    WHERE true {donde_fecha} {cond_otras}
                    LIMIT 2000
                """),
                {**params, **params_otras},
            ).scalars().all()
            distinct[col["key"]] = self._ordenar_distintos(vals)

        for clave in ("__form", "__fecha"):
            cond_otras, params_otras = self._condiciones_de_columna(clave)
            expr = self._expr_de_clave(clave)
            vals = self.db.execute(
                text(f"""
                    {prefijo}
                    SELECT DISTINCT coalesce(btrim({expr}), '') AS v
                    FROM base_f b
                    WHERE true {donde_fecha} {cond_otras}
                    LIMIT 2000
                """),
                {**params, **params_otras},
            ).scalars().all()
            distinct[clave] = self._ordenar_distintos(vals)

        # 4) Formatos y alias presentes.
        # Los formatos NO se filtran: es la lista de referencia de la vista
        # (el desplegable de "formato origen"), no el resultado de los filtros.
        # Se devuelven en el orden en que se eligieron al crear la vista.
        formatos_con_datos = set(self.db.execute(
            text("""
                SELECT DISTINCT r.form_id
                FROM responses r
                JOIN answers a ON a.response_id = r.id
                WHERE r.form_id = ANY(:form_ids)
                  AND r.status = 'submitted'
                  AND a.question_id = ANY(:question_ids)
            """),
            {"form_ids": self.form_ids, "question_ids": self.question_ids},
        ).scalars().all())

        alias_presentes = getattr(self, "_alias_presentes", [])

        return {
            "columns": self.columnas,
            "rows": rows_out,
            "totals": totals,
            "distinct": distinct,
            "aliases": alias_presentes,
            "forms": [
                {
                    "form_id": fid,
                    "form_title": self.titulos.get(fid),
                    "form_alias": self.alias_por_formato.get(fid),
                }
                for fid in self.form_ids
                if fid in formatos_con_datos
            ],
            "pagination": {
                "page": self.page,
                "page_size": self.page_size,
                "total_rows": total_rows,
                "total_pages": total_pages,
            },
        }

    @staticmethod
    def _ordenar_distintos(valores) -> List[str]:
        """Alfabético sin distinguir mayúsculas, y las vacías al final."""
        limpios = [str(v) for v in valores]
        ordenados = sorted((v for v in limpios if v != ""), key=lambda x: x.lower())
        if "" in limpios:
            ordenados.append("")
        return ordenados[:1000]
