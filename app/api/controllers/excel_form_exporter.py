"""
Módulo para exportar respuestas de formularios a Excel
replicando el diseño visual del form_design.
Compatible con FastAPI + openpyxl.

v3.0 — Fixes:
  - parse_css_size() para manejar rem, em, %, pt, px
  - Descubrimiento dinámico ROBUSTO de columnas del repeater via answers
  - Columnas descubiertas mantienen orden del form_design
  - Campos consumidos por repeater se omiten del nivel superior
  - Matching mejorado: form_design_element_id + question_id + linkExternalId
"""

from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage
from io import BytesIO
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import requests
import tempfile
import os
import re


# ─────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────

def hex_to_argb(hex_color: str) -> str:
    if not hex_color:
        return "FFFFFFFF"
    c = hex_color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        return f"FF{c.upper()}"
    if len(c) == 8:
        return c.upper()
    return "FFFFFFFF"


def make_side(width: str = "1px", color: str = "#000000") -> Side:
    w = width.replace("px", "").strip() if width else "1"
    style = "thin"
    if w.isdigit():
        n = int(w)
        if n >= 3:
            style = "thick"
        elif n >= 2:
            style = "medium"
    return Side(style=style, color=hex_to_argb(color))


def make_border(bw: str = "1px", bc: str = "#000000") -> Border:
    s = make_side(bw, bc)
    return Border(left=s, right=s, top=s, bottom=s)


def parse_css_size(value, default: int = 12) -> int:
    if value is None:
        return default
    s = str(value).strip().lower()
    if not s:
        return default
    try:
        return max(6, min(int(float(s)), 28))
    except (ValueError, TypeError):
        pass
    match = re.match(r'^([+-]?\d*\.?\d+)\s*(px|pt|rem|em|%|vw|vh)?$', s)
    if not match:
        return default
    num = float(match.group(1))
    unit = match.group(2) or "px"
    multipliers = {"px": 1.0, "pt": 1.0, "rem": 16.0, "em": 16.0, "%": 0.16, "vw": 0.16, "vh": 0.16}
    result = num * multipliers.get(unit, 1.0)
    return max(6, min(int(result), 28))


# ─────────────────────────────────────────────────
# CLASE PRINCIPAL
# ─────────────────────────────────────────────────

class FormExcelExporter:

    GRID_COLS = 12
    DEFAULT_COL_WIDTH = 14
    LABEL_FILL = PatternFill("solid", fgColor="FFF3F4F6")
    ANSWER_FILL = PatternFill("solid", fgColor="FFFFFFFF")
    HEADER_FONT = Font(name="Arial", bold=True, size=11)
    LABEL_FONT = Font(name="Arial", bold=True, size=10, color="FF374151")
    ANSWER_FONT = Font(name="Arial", size=10, color="FF1F2937")
    DECORATIVE_FONT = Font(name="Arial", size=10, color="FF6B7280", italic=True)

    def __init__(self, form_design, answers, style_config=None, form_title="", response_id=None):
        self.form_design = form_design
        self.answers = answers
        self.style_config = style_config or {}
        self.form_title = form_title
        self.response_id = response_id

        self.answers_map: Dict[str, dict] = {}
        self._build_answers_map()

        # ═══ Descubrir estructura de repeaters ═══
        self._repeater_columns: Dict[str, List[dict]] = {}
        self._consumed_by_repeater: Set[str] = set()
        self._discover_repeater_structure()

        self.wb = Workbook()
        self.ws = self.wb.active
        self.ws.title = "Formato"
        self.current_row = 1
        for col in range(1, self.GRID_COLS + 1):
            self.ws.column_dimensions[get_column_letter(col)].width = self.DEFAULT_COL_WIDTH

    # ── Mapa de respuestas ──

    def _build_answers_map(self):
        for ans in self.answers:
            qt = ans.get("question_text")
            if qt:
                self.answers_map[qt] = ans
            qid = ans.get("question_id")
            if qid is not None:
                self.answers_map[str(qid)] = ans
                self.answers_map[qid] = ans
            uuid_key = ans.get("form_design_element_id")
            if uuid_key:
                self.answers_map[uuid_key] = ans

    def _get_answer_for_field(self, field):
        fid = field.get("id")
        if fid and fid in self.answers_map:
            return self.answers_map[fid]
        link = field.get("linkExternalId")
        if link is not None:
            if link in self.answers_map:
                return self.answers_map[link]
            if str(link) in self.answers_map:
                return self.answers_map[str(link)]
        sqid = (field.get("props") or {}).get("sourceQuestionId")
        if sqid is not None and sqid in self.answers_map:
            return self.answers_map[sqid]
        label = (field.get("props") or {}).get("label")
        if label and label in self.answers_map:
            return self.answers_map[label]
        return None

    def _get_answer_text(self, answer):
        if not answer:
            return ""
        val = answer.get("answer_text", "")
        return str(val).strip() if val else ""

    # ── Descubrir columnas de repeaters (v3 ROBUSTO) ──

    def _discover_repeater_structure(self):
        """
        Para cada repeater descubre TODAS sus columnas:
        1. Hijos directos (children)
        2. Campos de nivel superior cuyas respuestas tienen
           repeated_id == repeater.id

        Las columnas descubiertas se ordenan según su posición
        en el form_design original.
        """
        repeaters = []
        self._find_repeaters(self.form_design, repeaters)

        # Índice de campos por ID
        field_index: Dict[str, dict] = {}
        # Orden de aparición en form_design (para ordenar columnas descubiertas)
        field_order: Dict[str, int] = {}
        self._index_all_fields(self.form_design, field_index, field_order)

        for repeater in repeaters:
            repeater_id = repeater.get("id")
            if not repeater_id:
                continue

            children = repeater.get("children") or []
            child_ids = {c.get("id") for c in children if c.get("id")}

            # IDs de elementos encontrados en respuestas de este repeater
            answer_element_ids = set()
            for ans in self.answers:
                if ans.get("repeated_id") == repeater_id:
                    elem_id = ans.get("form_design_element_id")
                    if elem_id:
                        answer_element_ids.add(elem_id)

            # Columnas descubiertas (no children) ordenadas por form_design
            discovered = []
            for elem_id in answer_element_ids:
                if elem_id not in child_ids and elem_id in field_index:
                    discovered.append(field_index[elem_id])

            # Ordenar descubiertas por su posición original en form_design
            discovered.sort(key=lambda f: field_order.get(f.get("id", ""), 9999))

            # Columnas finales: children primero, luego descubiertas (en orden)
            columns = list(children) + discovered

            self._repeater_columns[repeater_id] = columns

            # Marcar como consumidos
            for col in columns:
                col_id = col.get("id")
                if col_id:
                    self._consumed_by_repeater.add(col_id)

    def _find_repeaters(self, items, result):
        for item in items:
            if item.get("type") == "repeater":
                result.append(item)
            children = item.get("children") or []
            if children:
                self._find_repeaters(children, result)

    def _index_all_fields(self, items, index, order=None, counter=None):
        """Indexa todos los campos por ID y registra orden de aparición."""
        if counter is None:
            counter = [0]
        for item in items:
            fid = item.get("id")
            if fid and item.get("type"):
                index[fid] = item
                if order is not None:
                    order[fid] = counter[0]
                    counter[0] += 1
            children = item.get("children") or []
            if children:
                self._index_all_fields(children, index, order, counter)

    # ── Filtrar elementos ──

    def _filter_form_items(self, items):
        result = []
        for item in items:
            if item.get("type") and item.get("id"):
                result.append(item)
            elif item.get("type") and item.get("props"):
                result.append(item)
        return result

    def _extract_style_config(self):
        if self.style_config:
            return self.style_config
        for item in self.form_design:
            props = item.get("props") or {}
            if props.get("styleConfig"):
                return props["styleConfig"]
            if item.get("headerTable") and not item.get("type"):
                return item
        return {}

    # ── Header table ──

    def _render_header_table(self):
        sc = self._extract_style_config()
        ht = sc.get("headerTable")
        if not ht or not ht.get("enabled"):
            return
        cells_data = ht.get("cells", [])
        if not cells_data:
            return

        border_width = ht.get("borderWidth", "1px")
        border_color = ht.get("borderColor", "#000000")

        max_logical_cols = 0
        for row_cells in cells_data:
            col_count = sum(c.get("colSpan", 1) for c in row_cells)
            max_logical_cols = max(max_logical_cols, col_count)
        cols_per_header = max(1, self.GRID_COLS // max_logical_cols) if max_logical_cols else 3

        occupied = set()
        start_row = self.current_row

        for row_idx, row_cells in enumerate(cells_data):
            excel_row = start_row + row_idx
            logical_col = 0
            for cell_data in row_cells:
                while (excel_row, logical_col) in occupied:
                    logical_col += 1

                col_span = cell_data.get("colSpan", 1)
                row_span = cell_data.get("rowSpan", 1)
                content = cell_data.get("content", "")

                start_col = 1 + logical_col * cols_per_header
                end_col = min(start_col + (col_span * cols_per_header) - 1, self.GRID_COLS)
                end_row = excel_row + row_span - 1

                for r in range(excel_row, end_row + 1):
                    for c in range(logical_col, logical_col + col_span):
                        occupied.add((r, c))

                if end_col > start_col or end_row > excel_row:
                    self.ws.merge_cells(start_row=excel_row, start_column=start_col,
                                        end_row=end_row, end_column=end_col)

                cell = self.ws.cell(row=excel_row, column=start_col)
                if "[LOGO]" in content:
                    logo_url = sc.get("logo", {}).get("url")
                    if not logo_url or not self._try_insert_logo(logo_url, excel_row, start_col):
                        cell.value = "LOGO"
                else:
                    cell.value = content

                size_pt = parse_css_size(cell_data.get("fontSize", "11px"), 11)
                cell.font = Font(name="Arial", bold=cell_data.get("bold", False),
                                 italic=cell_data.get("italic", False), size=size_pt,
                                 color=hex_to_argb(cell_data.get("textColor", "#000000")))
                cell.alignment = Alignment(horizontal=cell_data.get("align", "center"),
                                           vertical="center", wrap_text=True)
                cell.fill = PatternFill("solid", fgColor=hex_to_argb(cell_data.get("backgroundColor", "#ffffff")))

                cell_border = make_border(cell_data.get("borderWidth", border_width),
                                          cell_data.get("borderColor", border_color))
                for r in range(excel_row, end_row + 1):
                    for c in range(start_col, end_col + 1):
                        self.ws.cell(row=r, column=c).border = cell_border

                logical_col += col_span

        for r in range(start_row, start_row + len(cells_data)):
            self.ws.row_dimensions[r].height = 28
        self.current_row = start_row + len(cells_data) + 1

    def _try_insert_logo(self, url, row, col):
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return False
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(resp.content)
            tmp.close()
            img = XlImage(tmp.name)
            img.width = 80
            img.height = 40
            self.ws.add_image(img, f"{get_column_letter(col)}{row}")
            return True
        except Exception:
            return False

    # ── Número de documento ──

    def _render_document_number(self):
        if not self.response_id:
            return
        row = self.current_row
        self.ws.merge_cells(start_row=row, start_column=9, end_row=row, end_column=12)
        cell = self.ws.cell(row=row, column=9)
        cell.value = f"Número del Documento: {self.response_id}"
        cell.font = Font(name="Courier New", bold=True, size=10, color="FFB91C1C")
        cell.alignment = Alignment(horizontal="right", vertical="center")
        cell.border = make_border("1px", "#DC2626")
        for c in range(9, 13):
            self.ws.cell(row=row, column=c).border = make_border("1px", "#DC2626")
        self.ws.row_dimensions[row].height = 24
        self.current_row += 2

    # ── Renderizar campos ──

    def _render_field(self, field, start_col=1, col_span=12):
        field_type = field.get("type", "")

        fid = field.get("id")
        if fid and fid in self._consumed_by_repeater and field_type != "repeater":
            return

        if field_type in ("label", "helpText", "divider", "image", "button"):
            self._render_decorative(field, start_col, col_span)
            return

        if field_type == "verticalLayout":
            for child in (field.get("children") or []):
                child_space = int((child.get("props") or {}).get("space", 12))
                self._render_field(child, start_col, min(child_space, col_span))
            return

        if field_type == "horizontalLayout":
            children = field.get("children") or []
            visible = [c for c in children if c.get("id") not in self._consumed_by_repeater]
            if not visible:
                return
            target_row = self.current_row
            current_col = start_col
            for child in visible:
                child_space = int((child.get("props") or {}).get("space", 6))
                actual_cols = max(2, child_space)
                self._render_field_inline(child, target_row, current_col, actual_cols)
                current_col += actual_cols
            self.ws.row_dimensions[target_row].height = 28
            self.current_row = target_row + 1
            return

        if field_type == "repeater":
            self._render_repeater(field)
            return

        # Campo normal
        props = field.get("props") or {}
        label = props.get("label", "Campo")
        required = props.get("required", False)
        answer = self._get_answer_for_field(field)
        answer_text = self._get_answer_text(answer)

        row = self.current_row
        end_col = min(start_col + col_span - 1, self.GRID_COLS)
        mid = start_col + max(1, col_span // 3) - 1

        if mid > start_col:
            self.ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=mid)
        lbl_cell = self.ws.cell(row=row, column=start_col)
        lbl_cell.value = f"{label} *" if required else label
        lbl_cell.font = self.LABEL_FONT
        lbl_cell.fill = self.LABEL_FILL
        lbl_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        lbl_cell.border = make_border("1px", "#D1D5DB")
        for c in range(start_col, mid + 1):
            self.ws.cell(row=row, column=c).border = make_border("1px", "#D1D5DB")

        ans_start = mid + 1
        if end_col > ans_start:
            self.ws.merge_cells(start_row=row, start_column=ans_start, end_row=row, end_column=end_col)
        ans_cell = self.ws.cell(row=row, column=ans_start)

        if answer and answer.get("question_type") == "firm":
            ans_cell.value = self._format_firm_answer(answer_text)
        elif answer and answer.get("file_path"):
            display = answer_text or "Archivo adjunto"
            ans_cell.value = f"{display} 📎 [{answer.get('file_path', '')}]"
        else:
            ans_cell.value = answer_text or "Sin respuesta"

        ans_cell.font = self.ANSWER_FONT if answer_text else self.DECORATIVE_FONT
        ans_cell.fill = self.ANSWER_FILL
        ans_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ans_cell.border = make_border("1px", "#D1D5DB")
        for c in range(ans_start, end_col + 1):
            self.ws.cell(row=row, column=c).border = make_border("1px", "#D1D5DB")

        self.ws.row_dimensions[row].height = 28
        self.current_row += 1

    def _render_field_inline(self, field, row, start_col, col_span):
        props = field.get("props") or {}
        label = props.get("label", "Campo")
        required = props.get("required", False)
        answer = self._get_answer_for_field(field)
        answer_text = self._get_answer_text(answer)

        end_col = min(start_col + col_span - 1, self.GRID_COLS)
        label_cols = max(1, col_span // 3)
        mid = start_col + label_cols - 1

        if mid > start_col:
            self.ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=mid)
        lbl = self.ws.cell(row=row, column=start_col)
        lbl.value = f"{label} *" if required else label
        lbl.font = self.LABEL_FONT
        lbl.fill = self.LABEL_FILL
        lbl.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        for c in range(start_col, mid + 1):
            self.ws.cell(row=row, column=c).border = make_border("1px", "#D1D5DB")

        ans_start = mid + 1
        if end_col > ans_start:
            self.ws.merge_cells(start_row=row, start_column=ans_start, end_row=row, end_column=end_col)
        ac = self.ws.cell(row=row, column=ans_start)
        if answer and answer.get("question_type") == "firm":
            ac.value = self._format_firm_answer(answer_text)
        elif answer and answer.get("file_path"):
            ac.value = f"{answer_text or 'Archivo adjunto'} 📎 [{answer.get('file_path', '')}]"
        else:
            ac.value = answer_text or "Sin respuesta"
        ac.font = self.ANSWER_FONT if answer_text else self.DECORATIVE_FONT
        ac.fill = self.ANSWER_FILL
        ac.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        for c in range(ans_start, end_col + 1):
            self.ws.cell(row=row, column=c).border = make_border("1px", "#D1D5DB")

    def _format_firm_answer(self, answer_text):
        try:
            data = json.loads(answer_text)
            firm = data.get("firmData", {})
            if isinstance(firm, dict):
                nested = firm.get("firmData", firm)
                name = nested.get("person_name", "")
                pid = nested.get("person_id", "")
                qr = nested.get("qr_url", "")
                parts = ["✅ Firma validada"]
                if name: parts.append(f"por {name}")
                if pid: parts.append(f"(ID: {pid})")
                if qr: parts.append(f"| QR: {qr}")
                return " ".join(parts)
        except (json.JSONDecodeError, TypeError):
            pass
        return answer_text

    # ── Decorativos ──

    def _render_decorative(self, field, start_col=1, col_span=12):
        field_type = field.get("type", "")
        props = field.get("props") or {}
        row = self.current_row
        end_col = min(start_col + col_span - 1, self.GRID_COLS)

        if field_type == "label":
            if end_col > start_col:
                self.ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
            cell = self.ws.cell(row=row, column=start_col)
            cell.value = props.get("text", "")
            fw = props.get("fontWeight", "normal")
            size = parse_css_size(props.get("fontSize", "12px"), 12)
            cell.font = Font(name="Arial", bold=(fw == "bold"), size=size,
                             color=hex_to_argb(props.get("color", "#333333")))
            cell.alignment = Alignment(horizontal=props.get("align", "left"),
                                       vertical="center", wrap_text=True)
            self.ws.row_dimensions[row].height = 24
            self.current_row += 1

        elif field_type == "helpText":
            if end_col > start_col:
                self.ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
            cell = self.ws.cell(row=row, column=start_col)
            cell.value = props.get("text", "")
            cell.font = Font(name="Arial", italic=True, size=9, color="FF6B7280")
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            self.ws.row_dimensions[row].height = 20
            self.current_row += 1

        elif field_type == "divider":
            thickness = parse_css_size(props.get("thickness", 1), 1)
            color = hex_to_argb(props.get("color", "#E5E7EB"))
            side = Side(style="thin" if thickness < 2 else "medium", color=color)
            for c in range(start_col, end_col + 1):
                self.ws.cell(row=row, column=c).border = Border(bottom=side)
            self.ws.row_dimensions[row].height = 8
            self.current_row += 1

        elif field_type == "image":
            if end_col > start_col:
                self.ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
            cell = self.ws.cell(row=row, column=start_col)
            cell.value = f"[Imagen: {props.get('label', props.get('src', ''))}]"
            cell.font = self.DECORATIVE_FONT
            self.current_row += 1

        else:
            self.current_row += 1

    # ── Repeater (tabla) v3 ROBUSTO ──

    def _render_repeater(self, field):
        """
        Renderiza repeater como tabla.
        Usa columnas descubiertas dinámicamente (children + campos via answers).
        Matching robusto: form_design_element_id → linkExternalId/question_id.
        """
        props = field.get("props") or {}
        repeater_id = field.get("id")

        columns = self._repeater_columns.get(repeater_id, field.get("children") or [])
        if not columns:
            return

        # Filtrar respuestas por repeated_id
        repeater_answers = [a for a in self.answers if a.get("repeated_id") == repeater_id]

        # Agrupar respuestas por columna
        answers_by_column: Dict[str, List[dict]] = {col.get("id"): [] for col in columns}

        # Construir lookup rápido: linkExternalId → column_id
        link_to_col: Dict[str, str] = {}
        for col_def in columns:
            col_id = col_def.get("id")
            if not col_id:
                continue
            lid = col_def.get("linkExternalId")
            if lid is not None:
                link_to_col[str(lid)] = col_id
            sqid = (col_def.get("props") or {}).get("sourceQuestionId")
            if sqid is not None:
                link_to_col[str(sqid)] = col_id

        for ans in repeater_answers:
            elem_id = ans.get("form_design_element_id")
            q_id = ans.get("question_id")

            # Prioridad 1: Match por form_design_element_id (UUID directo)
            if elem_id and elem_id in answers_by_column:
                answers_by_column[elem_id].append(ans)
                continue

            # Prioridad 2: Match por question_id → linkExternalId/sourceQuestionId
            if q_id is not None:
                col_id = link_to_col.get(str(q_id))
                if col_id and col_id in answers_by_column:
                    answers_by_column[col_id].append(ans)
                    continue

            # Prioridad 3: Match por question_text → label
            qt = ans.get("question_text", "")
            if qt:
                for col_def in columns:
                    col_label = (col_def.get("props") or {}).get("label", "")
                    if col_label and col_label == qt:
                        col_id = col_def.get("id")
                        if col_id and col_id in answers_by_column:
                            answers_by_column[col_id].append(ans)
                            break

        # Título
        label = props.get("label", "")
        if label:
            row = self.current_row
            self.ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=self.GRID_COLS)
            cell = self.ws.cell(row=row, column=1)
            cell.value = label
            cell.font = Font(name="Arial", bold=True, size=11, color="FF1F2937")
            cell.alignment = Alignment(horizontal="left", vertical="center")
            self.ws.row_dimensions[row].height = 24
            self.current_row += 1

        # Estilos
        ts = props.get("tableStyle", {})
        header_bg = hex_to_argb(ts.get("headerBackgroundColor", "#F3F4F6"))
        header_color = hex_to_argb(ts.get("headerTextColor", "#374151"))
        cell_bg = hex_to_argb(ts.get("cellBackgroundColor", "#FFFFFF"))
        alt_bg = hex_to_argb(ts.get("alternateRowColor", "#F9FAFB"))
        striped = ts.get("enableStripedRows", True)
        tb_border = make_border(ts.get("borderWidth", "1px"), ts.get("borderColor", "#D1D5DB"))

        num_cols = len(columns)
        col_width = max(1, self.GRID_COLS // num_cols)

        # Encabezados
        row = self.current_row
        for i, col_def in enumerate(columns):
            child_label = (col_def.get("props") or {}).get("label", f"Col {i+1}")
            start_c = 1 + i * col_width
            end_c = min(start_c + col_width - 1, self.GRID_COLS)
            if i == num_cols - 1:
                end_c = self.GRID_COLS  # Última columna ocupa el resto
            if end_c > start_c:
                self.ws.merge_cells(start_row=row, start_column=start_c, end_row=row, end_column=end_c)
            cell = self.ws.cell(row=row, column=start_c)
            cell.value = child_label
            cell.font = Font(name="Arial", bold=True, size=10, color=header_color)
            cell.fill = PatternFill("solid", fgColor=header_bg)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for c in range(start_c, end_c + 1):
                self.ws.cell(row=row, column=c).border = tb_border
        self.ws.row_dimensions[row].height = 28
        self.current_row += 1

        # Filas
        max_rows = max((len(v) for v in answers_by_column.values()), default=0)
        if max_rows == 0:
            row = self.current_row
            self.ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=self.GRID_COLS)
            cell = self.ws.cell(row=row, column=1)
            cell.value = "Sin datos registrados"
            cell.font = self.DECORATIVE_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center")
            self.current_row += 1
            return

        for row_idx in range(max_rows):
            row = self.current_row
            use_alt = striped and row_idx % 2 == 1
            bg = PatternFill("solid", fgColor=alt_bg) if use_alt else PatternFill("solid", fgColor=cell_bg)

            for i, col_def in enumerate(columns):
                col_id = col_def.get("id")
                col_answers = answers_by_column.get(col_id, [])
                val = ""
                if row_idx < len(col_answers):
                    val = col_answers[row_idx].get("answer_text", "") or ""
                    fp = col_answers[row_idx].get("file_path", "")
                    if fp:
                        val = f"{val} 📎 [{fp}]" if val else f"📎 [{fp}]"

                start_c = 1 + i * col_width
                end_c = min(start_c + col_width - 1, self.GRID_COLS)
                if i == num_cols - 1:
                    end_c = self.GRID_COLS
                if end_c > start_c:
                    self.ws.merge_cells(start_row=row, start_column=start_c, end_row=row, end_column=end_c)
                cell = self.ws.cell(row=row, column=start_c)
                cell.value = val or "-"
                cell.font = self.ANSWER_FONT
                cell.fill = bg
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                for c in range(start_c, end_c + 1):
                    self.ws.cell(row=row, column=c).border = tb_border

            self.ws.row_dimensions[row].height = 24
            self.current_row += 1

    # ── Footer ──

    def _render_footer(self):
        sc = self._extract_style_config()
        footer = sc.get("footer", {})
        if not footer.get("show"):
            return
        self.current_row += 1
        row = self.current_row
        side = Side(style="thin", color="FF999999")
        for c in range(1, self.GRID_COLS + 1):
            self.ws.cell(row=row, column=c).border = Border(top=side)
        row += 1
        self.ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=self.GRID_COLS)
        cell = self.ws.cell(row=row, column=1)
        cell.value = footer.get("text", "")
        cell.font = Font(name="Arial", size=8, color="FF999999")
        cell.alignment = Alignment(horizontal=footer.get("align", "center"), vertical="center")
        self.current_row = row + 1

    # ── Generar ──

    def generate(self) -> BytesIO:
        self._render_header_table()
        self._render_document_number()

        filtered = self._filter_form_items(self.form_design)
        for field in filtered:
            field_type = field.get("type", "")
            fid = field.get("id")
            if fid and fid in self._consumed_by_repeater and field_type != "repeater":
                continue
            if field_type in ("horizontalLayout", "verticalLayout"):
                self._render_field(field)
            else:
                space = int((field.get("props") or {}).get("space", 12))
                self._render_field(field, start_col=1, col_span=space)

        self._render_footer()
        self.ws.sheet_properties.pageSetUpPr = None
        self.ws.page_setup.orientation = "landscape"
        self.ws.page_setup.fitToWidth = 1
        self.ws.page_setup.fitToHeight = 0

        output = BytesIO()
        self.wb.save(output)
        output.seek(0)
        return output


def generate_form_excel(form_design, answers, style_config=None, form_title="", response_id=None) -> BytesIO:
    return FormExcelExporter(
        form_design=form_design, answers=answers,
        style_config=style_config, form_title=form_title, response_id=response_id,
    ).generate()