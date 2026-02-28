"""
Módulo para exportar respuestas de formularios a PDF
replicando el diseño visual del form_design.

v3.0 — Fixes:
  - Descubrimiento dinámico ROBUSTO de columnas del repeater via answers
  - Columnas descubiertas mantienen orden del form_design
  - Campos consumidos por repeater se omiten del nivel superior
  - Matching mejorado: form_design_element_id + question_id + linkExternalId
  - Bug fix en _render_repeater_html (cell_content)

Dependencia: pip install xhtml2pdf
"""

from io import BytesIO
from typing import Any, Dict, List, Optional, Set
import json
import html as html_module


class FormPdfExporter:

    def __init__(self, form_design, answers, style_config=None,
                 form_title="", response_id=None, logo_base64=None):
        self.form_design = form_design
        self.answers = answers
        self.style_config = style_config or {}
        self.form_title = form_title
        self.response_id = response_id
        self.logo_base64 = logo_base64

        self.answers_map: Dict[str, dict] = {}
        self._build_answers_map()

        # ═══ Descubrir estructura de repeaters ═══
        self._repeater_columns: Dict[str, List[dict]] = {}
        self._consumed_by_repeater: Set[str] = set()
        self._discover_repeater_structure()

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

    def _esc(self, text):
        return html_module.escape(str(text)) if text else ""

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

        field_index: Dict[str, dict] = {}
        field_order: Dict[str, int] = {}
        self._index_all_fields(self.form_design, field_index, field_order)

        for repeater in repeaters:
            repeater_id = repeater.get("id")
            if not repeater_id:
                continue

            children = repeater.get("children") or []
            child_ids = {c.get("id") for c in children if c.get("id")}

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

            discovered.sort(key=lambda f: field_order.get(f.get("id", ""), 9999))

            columns = list(children) + discovered

            self._repeater_columns[repeater_id] = columns

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

    # ── Filtrar / Style config ──

    def _filter_form_items(self, items):
        return [
            item for item in items
            if (item.get("type") and item.get("id"))
            or (item.get("type") and item.get("props"))
        ]

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

    # ── Header table HTML ──

    def _render_header_table_html(self):
        sc = self._extract_style_config()
        ht = sc.get("headerTable")
        if not ht or not ht.get("enabled"):
            return ""
        cells_data = ht.get("cells", [])
        if not cells_data:
            return ""

        bw = ht.get("borderWidth", "1px")
        bc = ht.get("borderColor", "#000000")

        rows_html = []
        for row_cells in cells_data:
            cells_html = []
            for cell in row_cells:
                content = cell.get("content", "")
                col_span = cell.get("colSpan", 1)
                row_span = cell.get("rowSpan", 1)
                bold = "font-weight:bold;" if cell.get("bold") else ""
                italic = "font-style:italic;" if cell.get("italic") else ""
                fs = cell.get("fontSize", "11px")
                tc = cell.get("textColor", "#000000")
                bg = cell.get("backgroundColor", "#ffffff")
                align = cell.get("align", "center")
                cell_bw = cell.get("borderWidth", bw)
                cell_bc = cell.get("borderColor", bc)

                style = (
                    f"border:{cell_bw} solid {cell_bc};background-color:{bg};"
                    f"color:{tc};font-size:{fs};text-align:{align};"
                    f"padding:6px 8px;vertical-align:middle;{bold}{italic}"
                )

                if "[LOGO]" in content:
                    logo_url = sc.get("logo", {}).get("url", "")
                    if self.logo_base64:
                        display = f'<img src="data:image/png;base64,{self.logo_base64}" style="height:40px;"/>'
                    elif logo_url:
                        display = f'<img src="{self._esc(logo_url)}" style="height:40px;" />'
                    else:
                        display = "LOGO"
                else:
                    display = self._esc(content)

                attrs = f'style="{style}"'
                if col_span > 1: attrs += f' colspan="{col_span}"'
                if row_span > 1: attrs += f' rowspan="{row_span}"'
                cells_html.append(f"<td {attrs}>{display}</td>")
            rows_html.append(f"<tr>{''.join(cells_html)}</tr>")

        return f'''
        <table class="header-table" style="width:100%;border-collapse:collapse;border:{bw} solid {bc};margin-bottom:12px;">
            {''.join(rows_html)}
        </table>'''

    # ── Número de documento HTML ──

    def _render_document_number_html(self):
        if not self.response_id:
            return ""
        return f'''
        <div style="text-align:right;margin-bottom:12px;">
            <span style="font-family:'Courier New',monospace;font-size:11px;font-weight:bold;
                color:#B91C1C;border:1px solid #DC2626;border-radius:6px;padding:4px 12px;
                display:inline-block;">
                Número del Documento: {self.response_id}
            </span>
        </div>'''

    # ── Campo HTML ──

    def _render_field_html(self, field):
        field_type = field.get("type", "")

        fid = field.get("id")
        if fid and fid in self._consumed_by_repeater and field_type != "repeater":
            return ""

        if field_type in ("label", "helpText", "divider", "image", "button"):
            return self._render_decorative_html(field)

        if field_type == "verticalLayout":
            children = field.get("children") or []
            inner = "".join(self._render_field_html(c) for c in children)
            return f'<div style="margin-bottom:4px;">{inner}</div>'

        if field_type == "horizontalLayout":
            children = field.get("children") or []
            visible = [c for c in children if c.get("id") not in self._consumed_by_repeater]
            if not visible:
                return ""
            cells = []
            for child in visible:
                space = int((child.get("props") or {}).get("space", 6))
                width_pct = (space / 12) * 100
                cell_html = self._render_field_html(child)
                cells.append(f'<td style="width:{width_pct:.1f}%;vertical-align:top;padding:0 4px;">{cell_html}</td>')
            return f'<table style="width:100%;border-collapse:collapse;margin-bottom:4px;"><tr>{"".join(cells)}</tr></table>'

        if field_type == "repeater":
            return self._render_repeater_html(field)

        return self._render_input_field_html(field)

    def _render_input_field_html(self, field):
        props = field.get("props") or {}
        label = props.get("label", "Campo")
        required = props.get("required", False)
        answer = self._get_answer_for_field(field)
        answer_text = self._get_answer_text(answer)

        label_display = f"{self._esc(label)} <span style='color:red;'>*</span>" if required else self._esc(label)

        if answer and answer.get("question_type") == "firm":
            value_html = self._format_firm_html(answer_text)
        elif answer and answer.get("file_path"):
            file_name = self._esc(answer.get("file_path", ""))
            display = self._esc(answer_text) or "Archivo adjunto"
            value_html = f'{display} <span style="color:#3B82F6;">📎 [{file_name}]</span>'
        elif answer_text:
            value_html = self._esc(answer_text)
        else:
            value_html = '<span style="color:#9CA3AF;font-style:italic;">Sin respuesta</span>'

        return f'''
        <table style="width:100%;border-collapse:collapse;margin-bottom:6px;">
            <tr>
                <td style="width:35%;background-color:#F3F4F6;border:1px solid #D1D5DB;
                    padding:6px 10px;font-weight:bold;font-size:10px;color:#374151;
                    vertical-align:middle;">{label_display}</td>
                <td style="width:65%;background-color:#FFFFFF;border:1px solid #D1D5DB;
                    padding:6px 10px;font-size:10px;color:#1F2937;
                    vertical-align:middle;">{value_html}</td>
            </tr>
        </table>'''

    def _format_firm_html(self, answer_text):
        try:
            data = json.loads(answer_text)
            firm = data.get("firmData", {})
            if isinstance(firm, dict):
                nested = firm.get("firmData", firm)
                name = nested.get("person_name", "")
                pid = nested.get("person_id", "")
                qr = nested.get("qr_url", "")
                parts = ['<span style="color:#059669;">✅ Firma validada</span>']
                if name: parts.append(f"por <b>{self._esc(name)}</b>")
                if pid: parts.append(f'<span style="color:#6B7280;">(ID: {self._esc(pid)})</span>')
                if qr: parts.append(f'<br/><span style="font-size:8px;color:#6B7280;">QR: {self._esc(qr)}</span>')
                return " ".join(parts)
        except (json.JSONDecodeError, TypeError):
            pass
        return self._esc(answer_text)

    # ── Decorativos HTML ──

    def _render_decorative_html(self, field):
        field_type = field.get("type", "")
        props = field.get("props") or {}

        if field_type == "label":
            text = self._esc(props.get("text", ""))
            fw = props.get("fontWeight", "normal")
            fs = props.get("fontSize", "12px")
            color = props.get("color", "#333333")
            align = props.get("align", "left")
            return f'<div style="font-size:{fs};font-weight:{fw};color:{color};text-align:{align};margin-bottom:6px;padding:4px 0;">{text}</div>'

        if field_type == "helpText":
            text = self._esc(props.get("text", ""))
            fs = props.get("fontSize", "9px")
            color = props.get("color", "#6B7280")
            return f'<div style="font-size:{fs};color:{color};font-style:italic;margin-bottom:6px;">{text}</div>'

        if field_type == "divider":
            thickness = props.get("thickness", 1)
            color = props.get("color", "#E5E7EB")
            return f'<hr style="border:none;height:{thickness}px;background-color:{color};margin:8px 0;"/>'

        if field_type == "image":
            src = props.get("src", "")
            label = props.get("label", "")
            if src:
                lbl_html = f'<div style="font-size:10px;font-weight:bold;margin-bottom:4px;">{self._esc(label)}</div>' if label else ''
                return f'<div style="margin-bottom:6px;">{lbl_html}<img src="{self._esc(src)}" style="max-width:100%;height:auto;border-radius:4px;"/></div>'
            return ""

        return ""

    # ── Repeater HTML (v3 ROBUSTO) ──

    def _render_repeater_html(self, field):
        """
        Renderiza repeater como tabla HTML.
        Usa columnas descubiertas dinámicamente.
        Matching robusto: form_design_element_id → linkExternalId/question_id → label.
        """
        props = field.get("props") or {}
        repeater_id = field.get("id")

        columns = self._repeater_columns.get(repeater_id, field.get("children") or [])
        if not columns:
            return ""

        # Filtrar respuestas del repeater
        repeater_answers = [a for a in self.answers if a.get("repeated_id") == repeater_id]

        # Agrupar por columna
        answers_by_column: Dict[str, List[dict]] = {col.get("id"): [] for col in columns}

        # Lookup rápido: linkExternalId/sourceQuestionId → column_id
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

            # Prioridad 1: form_design_element_id directo
            if elem_id and elem_id in answers_by_column:
                answers_by_column[elem_id].append(ans)
                continue

            # Prioridad 2: question_id → linkExternalId/sourceQuestionId
            if q_id is not None:
                col_id = link_to_col.get(str(q_id))
                if col_id and col_id in answers_by_column:
                    answers_by_column[col_id].append(ans)
                    continue

            # Prioridad 3: question_text → label
            qt = ans.get("question_text", "")
            if qt:
                for col_def in columns:
                    col_label = (col_def.get("props") or {}).get("label", "")
                    if col_label and col_label == qt:
                        col_id = col_def.get("id")
                        if col_id and col_id in answers_by_column:
                            answers_by_column[col_id].append(ans)
                            break

        # Estilos
        ts = props.get("tableStyle", {})
        h_bg = ts.get("headerBackgroundColor", "#F3F4F6")
        h_color = ts.get("headerTextColor", "#374151")
        c_bg = ts.get("cellBackgroundColor", "#FFFFFF")
        alt_bg = ts.get("alternateRowColor", "#F9FAFB")
        striped = ts.get("enableStripedRows", True)
        tb_bw = ts.get("borderWidth", "1px")
        tb_bc = ts.get("borderColor", "#D1D5DB")

        # Label
        label = props.get("label", "")
        label_html = f'<div style="font-weight:bold;font-size:11px;margin-bottom:6px;color:#1F2937;">{self._esc(label)}</div>' if label else ""

        # Encabezados
        headers = []
        for col_def in columns:
            child_label = (col_def.get("props") or {}).get("label", "Columna")
            headers.append(
                f'<th style="background-color:{h_bg};color:{h_color};font-weight:bold;'
                f'font-size:10px;border:{tb_bw} solid {tb_bc};padding:8px;text-align:center;">'
                f'{self._esc(child_label)}</th>'
            )
        header_row = f'<tr>{"".join(headers)}</tr>'

        # Filas
        max_rows = max((len(v) for v in answers_by_column.values()), default=0)
        body_rows = []

        if max_rows == 0:
            body_rows.append(
                f'<tr><td colspan="{len(columns)}" style="text-align:center;'
                f'color:#9CA3AF;font-style:italic;padding:12px;'
                f'border:{tb_bw} solid {tb_bc};">Sin datos registrados</td></tr>'
            )
        else:
            for row_idx in range(max_rows):
                bg = alt_bg if (striped and row_idx % 2 == 1) else c_bg
                cells = []
                for col_def in columns:
                    col_id = col_def.get("id")
                    col_answers = answers_by_column.get(col_id, [])

                    val = ""
                    file_path = ""
                    if row_idx < len(col_answers):
                        val = col_answers[row_idx].get("answer_text", "") or ""
                        file_path = col_answers[row_idx].get("file_path", "")

                    # Construir contenido de celda
                    if val and file_path:
                        cell_content = (
                            f'{self._esc(val)} '
                            f'<span style="color:#3B82F6;font-size:8px;">📎 {self._esc(file_path)}</span>'
                        )
                    elif file_path:
                        cell_content = f'<span style="color:#3B82F6;font-size:8px;">📎 {self._esc(file_path)}</span>'
                    elif val:
                        cell_content = self._esc(val)
                    else:
                        cell_content = '<span style="color:#9CA3AF;">-</span>'

                    cells.append(
                        f'<td style="background-color:{bg};border:{tb_bw} solid {tb_bc};'
                        f'padding:6px 8px;font-size:10px;color:#374151;">{cell_content}</td>'
                    )
                body_rows.append(f'<tr>{"".join(cells)}</tr>')

        return f'''
        {label_html}
        <table style="width:100%;border-collapse:collapse;margin-bottom:10px;border:{tb_bw} solid {tb_bc};">
            <thead>{header_row}</thead>
            <tbody>{"".join(body_rows)}</tbody>
        </table>'''

    # ── Footer HTML ──

    def _render_footer_html(self):
        sc = self._extract_style_config()
        footer = sc.get("footer", {})
        if not footer.get("show"):
            return ""
        text = self._esc(footer.get("text", ""))
        align = footer.get("align", "center")
        return f'<div style="text-align:{align};margin-top:16px;padding-top:8px;border-top:1px solid rgba(0,0,0,0.1);font-size:8px;color:#999999;">{text}</div>'

    # ── HTML completo ──

    def _build_html(self):
        sc = self._extract_style_config()
        bg_color = sc.get("backgroundColor", "#ffffff")
        font_family = sc.get("font", {}).get("family", "Arial, sans-serif")
        font_size = sc.get("font", {}).get("size", "12px")
        font_color = sc.get("font", {}).get("color", "#333333")

        header_html = self._render_header_table_html()
        doc_num_html = self._render_document_number_html()

        filtered = self._filter_form_items(self.form_design)
        fields_html_parts = []
        for f in filtered:
            fid = f.get("id")
            ftype = f.get("type", "")
            if fid and fid in self._consumed_by_repeater and ftype != "repeater":
                continue
            fields_html_parts.append(self._render_field_html(f))
        fields_html = "".join(fields_html_parts)

        footer_html = self._render_footer_html()

        return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        @page {{ size: letter landscape; margin: 1.5cm; }}
        body {{ font-family: {font_family}; font-size: {font_size}; color: {font_color};
               background-color: {bg_color}; margin: 0; padding: 0; }}
        .container {{ padding: 0; }}
        table {{ page-break-inside: auto; }}
        tr {{ page-break-inside: avoid; page-break-after: auto; }}
        .header-table {{ page-break-inside: avoid; }}
    </style>
</head>
<body>
    <div class="container">
        {header_html}
        {doc_num_html}
        {fields_html}
        {footer_html}
    </div>
</body>
</html>'''

    # ── Generar PDF ──

    def generate(self) -> BytesIO:
        from xhtml2pdf import pisa
        html_content = self._build_html()
        output = BytesIO()
        pisa_status = pisa.CreatePDF(html_content, dest=output)
        if pisa_status.err:
            raise Exception(f"Error generando PDF: {pisa_status.err}")
        output.seek(0)
        return output

    def generate_html(self) -> str:
        return self._build_html()


def generate_form_pdf(form_design, answers, style_config=None,
                      form_title="", response_id=None, logo_base64=None) -> BytesIO:
    return FormPdfExporter(
        form_design=form_design, answers=answers, style_config=style_config,
        form_title=form_title, response_id=response_id, logo_base64=logo_base64,
    ).generate()