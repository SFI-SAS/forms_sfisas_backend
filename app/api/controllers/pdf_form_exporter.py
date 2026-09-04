"""
FormPdfExporter v6.0
Replica exacta del componente FormResponseRenderer (ResponsesModal.tsx).
Lógica de lookup, layouts condicionales, repeaters y sub-repeaters
son puerto directo del frontend.
"""
from io import BytesIO
from typing import Any, Dict, List, Optional
import json
import os
import hashlib
import hmac
import time
import struct
import base64
import html as _html
import logging
from urllib.parse import quote as _url_quote

logger = logging.getLogger(__name__)

# ── utilidades HTML ───────────────────────────────────────────────────────────

def _e(v: Any) -> str:
    return _html.escape(str(v)) if v is not None else ""

def _req_star(required: bool) -> str:
    return '<span style="color:#DC2626;font-weight:bold;"> *</span>' if required else ""


# ── imagenes externas ────────────────────────────────────────────────────────
# El PDF referencia imagenes por URL (logo del formato y los QR de firma en
# api.qrserver.com). Si el servidor no tiene salida a internet, o el host tarda,
# el render se cuelga o revienta y el endpoint responde 500. Con este fetcher
# una imagen que no llega solo deja un hueco: el PDF sale igual.
_BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_URL_TIMEOUT = int(os.getenv("PDF_IMAGE_TIMEOUT", "8"))


def _safe_url_fetcher(url: str, timeout: int = _URL_TIMEOUT, ssl_context=None):
    from weasyprint import default_url_fetcher
    try:
        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)
    except Exception as exc:
        logger.warning("PDF: no se pudo traer %s (%s)", url[:120], exc)
        return {"string": _BLANK_PNG, "mime_type": "image/png"}


# ── ancho: cortar repeaters muy anchos ───────────────────────────────────────
# La hoja es letter landscape con 14mm de margen → ~251mm útiles. Pasado cierto
# número de columnas la tabla se sale del papel y las de la derecha no se ven,
# así que se parte en bloques apilados uno debajo del otro.
MAX_COLS_MAIN = 10   # columnas por bloque en el repeater principal
MAX_COLS_SUB  = 8    # el sub-repeater va indentado, le cabe menos


def _split_columns(n_cols: int, max_per_block: int) -> List[tuple]:
    """Parte n columnas en bloques balanceados de a lo sumo max_per_block."""
    if n_cols <= max_per_block:
        return [(0, n_cols)]
    n_blocks = -(-n_cols // max_per_block)          # ceil
    base, extra = divmod(n_cols, n_blocks)
    out, start = [], 0
    for i in range(n_blocks):
        size = base + (1 if i < extra else 0)
        out.append((start, start + size))
        start += size
    return out


def _density(n_cols: int, base_font: float = 10.0) -> str:
    """Aprieta letra y padding cuando el bloque lleva muchas columnas."""
    if n_cols <= 6:
        return ""
    if n_cols <= 8:
        return "font-size:{f}px;padding:5px 6px;".format(f=base_font - 1)
    return "font-size:{f}px;padding:4px 5px;".format(f=base_font - 1.5)


def _block_caption(start: int, end: int, total: int) -> str:
    return (
        '<div class="rep-block-caption">Columnas {a} a {b} de {t}</div>'
    ).format(a=start + 1, b=end, t=total)

# ── formateadores de tipos de campo ──────────────────────────────────────────

def _fmt_firm(answer_text: str) -> str:
    """Renderiza firma igual que renderInputFieldResponse caso firm.

    Sin display:flex — ver la nota en _fmt_firm_cell.
    """
    try:
        data = json.loads(answer_text)
        firm = data.get("firmData", {})
        if isinstance(firm, dict) and firm.get("qr_url"):
            qr_url      = firm["qr_url"]
            person_name = firm.get("person_name", "")
            person_id   = firm.get("person_id", "")
        elif isinstance(firm, dict) and isinstance(firm.get("firmData"), dict):
            inner = firm["firmData"]
            qr_url      = inner.get("qr_url", "")
            person_name = inner.get("person_name", "")
            person_id   = inner.get("person_id", "")
        else:
            qr_url = person_name = person_id = ""

        if qr_url:
            qr_img = "https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=" + _url_quote(qr_url)
            name_html = ('<span style="font-size:11px;color:#374151;">por ' + _e(person_name) + '</span>') if person_name else ""
            id_html   = ('<span style="font-size:10px;color:#6B7280;">(ID: ' + _e(person_id) + ')</span>') if person_id else ""
            return (
                '<div>'
                '<div style="margin-bottom:6px;">'
                '<span style="font-size:10px;font-weight:600;color:#065F46;background:#D1FAE5;'
                'padding:2px 7px;border-radius:4px;">&#10003; Firma validada</span>'
                + name_html + id_html +
                '</div>'
                '<div style="text-align:center;">'
                '<span style="font-size:10px;color:#6B7280;display:block;margin-bottom:4px;">C\u00f3digo QR de verificaci\u00f3n:</span>'
                '<img src="' + _e(qr_img) + '" alt="QR firma" '
                'style="width:100px;height:100px;border:1px solid #D1D5DB;border-radius:6px;'
                'display:block;margin:0 auto 4px auto;"/>'
                '<span style="font-size:9px;color:#9CA3AF;text-align:center;word-break:break-all;'
                'max-width:200px;display:block;margin:0 auto;">'
                + _e(qr_url) + '</span>'
                '</div></div>'
            )
        else:
            n = _e(person_name) if person_name else "Sin nombre"
            return (
                '<span style="font-size:10px;color:#DC2626;background:#FEF2F2;'
                'padding:2px 6px;border-radius:4px;">Firma no validada</span>&nbsp;' + n
            )
    except Exception:
        return (
            '<span style="font-size:10px;color:#DC2626;background:#FEF2F2;'
            'padding:2px 6px;border-radius:4px;">Error en firma</span>&nbsp;' + _e(answer_text)
        )


def _fmt_firm_cell(answer_text: str) -> str:
    """Versi\u00f3n compacta para celdas de repeater (renderFirmCell)."""
    try:
        data = json.loads(answer_text)
        firm = data.get("firmData", {})
        if isinstance(firm, dict) and firm.get("qr_url"):
            qr_url      = firm["qr_url"]
            person_name = firm.get("person_name", "")
            person_id   = firm.get("person_id", "")
        elif isinstance(firm, dict) and isinstance(firm.get("firmData"), dict):
            inner = firm["firmData"]
            qr_url      = inner.get("qr_url", "")
            person_name = inner.get("person_name", "")
            person_id   = inner.get("person_id", "")
        else:
            qr_url = person_name = person_id = ""

        if not qr_url:
            return '<span style="font-size:9px;color:#DC2626;background:#FEF2F2;padding:1px 5px;border-radius:4px;">Firma sin QR</span>'

        qr_img   = "https://api.qrserver.com/v1/create-qr-code/?size=90x90&data=" + _url_quote(qr_url)
        id_part  = ('<span style="font-size:9px;color:#9CA3AF;">ID: ' + _e(person_id) + '</span>') if person_id else ""
        name_part = ('<span style="font-size:9px;color:#374151;font-weight:500;">' + _e(person_name) + '</span>') if person_name else ""
        # OJO: nada de display:flex aqui dentro. Esta celda vive DENTRO de la
        # tabla del repeater, y el flexbox de WeasyPrint se rompe cuando un hijo
        # flex no alcanza a caber y su layout devuelve None: revienta con
        # "AttributeError: 'NoneType' object has no attribute 'height'"
        # (flex.py:253) y el PDF entero se cae con 500. Con bloque + inline-block
        # se ve igual y no pasa por esa ruta fragil.
        return (
            '<div style="text-align:center;padding:2px 0;">'
            '<div style="margin-bottom:3px;">'
            '<span style="font-size:9px;font-weight:600;color:#15803D;background:#F0FDF4;'
            'padding:1px 5px;border-radius:99px;border:1px solid #BBF7D0;'
            'display:inline-block;vertical-align:middle;">&#10003; Firmado</span>'
            + (('&nbsp;' + name_part) if name_part else '') +
            '</div>'
            + ((id_part + '<div style="height:3px;"></div>') if id_part else '') +
            '<img src="' + _e(qr_img) + '" alt="QR" '
            'style="width:70px;height:70px;border:1px solid #E5E7EB;border-radius:4px;'
            'display:block;margin:3px auto;"/>'
            '<span style="font-size:8px;color:#9CA3AF;">Escanea para verificar</span>'
            '</div>'
        )
    except Exception:
        return _e(answer_text)


def _fmt_location(answer_text: str) -> str:
    try:
        loc = json.loads(answer_text)
        parts = []
        if loc.get("selection"):
            parts.append('<div style="font-weight:600;color:#374151;">' + _e(loc["selection"]) + '</div>')
        coords = []
        if loc.get("lat") is not None:
            coords.append("Lat: " + str(loc["lat"]))
        if loc.get("lng") is not None:
            coords.append("Lng: " + str(loc["lng"]))
        if coords:
            parts.append('<div style="font-size:10px;color:#6B7280;">' + " | ".join(coords) + '</div>')
        if loc.get("address"):
            parts.append('<div style="font-size:10px;color:#6B7280;">' + _e(loc["address"]) + '</div>')
        return "\n".join(parts) if parts else _e(answer_text)
    except Exception:
        return _e(answer_text)


def _fmt_checkbox(answer_text: str) -> str:
    try:
        vals = json.loads(answer_text)
        if isinstance(vals, list):
            return _e(", ".join(str(v) for v in vals))
    except Exception:
        pass
    return _e(answer_text)


def _fmt_number(answer_text: str, props: dict) -> str:
    try:
        num      = float(answer_text)
        prefix   = str(props.get("currencyPrefix") or "")
        suffix   = str(props.get("currencySuffix") or "")
        decimals = int(props.get("decimalPlaces") or 2)
        formatted = "{:,.{d}f}".format(num, d=decimals)
        return _e(prefix + formatted + suffix)
    except Exception:
        return _e(answer_text)


def _fmt_date(answer_text: str) -> str:
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(answer_text[:len(fmt.replace('%Y','0000').replace('%m','00').replace('%d','00').replace('%H','00').replace('%M','00').replace('%S','00'))], fmt).strftime("%d/%m/%Y")
        except Exception:
            pass
    return _e(answer_text)


def _fmt_datetime(answer_text: str) -> str:
    from datetime import datetime
    try:
        s = answer_text.replace("T", " ").split(".")[0]
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
    except Exception:
        return _e(answer_text)


def _render_cell_value(cell_data: Any) -> str:
    """Puerto de renderRepeaterCell del frontend."""
    if cell_data is None:
        return '<span style="color:#9CA3AF;font-style:italic;">-</span>'

    if isinstance(cell_data, str):
        try:
            parsed = json.loads(cell_data)
            fd = parsed.get("firmData", {})
            if isinstance(fd, dict) and (fd.get("qr_url") or (isinstance(fd.get("firmData"), dict) and fd["firmData"].get("qr_url"))):
                return _fmt_firm_cell(cell_data)
        except Exception:
            pass
        return _e(cell_data) if cell_data else '<span style="color:#9CA3AF;font-style:italic;">-</span>'

    if isinstance(cell_data, dict):
        qtype = cell_data.get("question_type", "")
        atext = str(cell_data.get("answer_text") or "")
        fpath = str(cell_data.get("file_path") or "")

        if qtype == "firm" and atext:
            try:
                return _fmt_firm_cell(atext)
            except Exception:
                pass

        if atext:
            try:
                p = json.loads(atext)
                fd = p.get("firmData", {})
                if isinstance(fd, dict) and (fd.get("qr_url") or (isinstance(fd.get("firmData"), dict) and fd["firmData"].get("qr_url"))):
                    return _fmt_firm_cell(atext)
            except Exception:
                pass

        parts = []
        if atext:
            parts.append(_e(atext))
        if fpath:
            parts.append('<span style="font-size:9px;color:#2563EB;background:#EFF6FF;'
                         'padding:1px 6px;border-radius:3px;border:1px solid #BFDBFE;">&#128206; Archivo adjunto</span>')
        return "\n".join(parts) if parts else '<span style="color:#9CA3AF;font-style:italic;">-</span>'

    return _e(str(cell_data))


def _build_sub_rows(filtered: list, sub_normal: list) -> List[Dict]:
    """
    Puerto EXACTO de la lógica subRows en renderSubRepeaterForRow (ResponsesModal.tsx línea 958-1000).

    - Con repeater_row_index → agrupar por él.
    - Sin repeater_row_index → agrupar por columna y reconstruir por posición.
      (el frontend NUNCA agrupa por repeated_id aquí)
    """
    sub_rows: List[Dict] = []
    has_ri = any(a.get("repeater_row_index") is not None for a in filtered)

    if has_ri:
        # Agrupar por repeater_row_index (línea 964-977 frontend)
        by_ri: Dict[int, List] = {}
        for ans in filtered:
            by_ri.setdefault(ans.get("repeater_row_index") or 0, []).append(ans)
        for ri in sorted(by_ri):
            rd: Dict[str, Any] = {}
            for c in sub_normal:
                cid = c.get("id", "")
                # La más reciente, no la primera: una celda re-escrita (por
                # ejemplo una firma sobre el documento del firmante) tiene
                # varias respuestas y la buena es la última.
                _cands = [a for a in by_ri[ri] if a.get("form_design_element_id") == cid]
                m = max(_cands, key=lambda a: (a.get("id_answer") or 0)) if _cands else None
                if m:
                    rd[cid] = {"answer_text": m.get("answer_text"),
                               "file_path":   m.get("file_path"),
                               "question_type": m.get("question_type")}
            if rd:
                sub_rows.append(rd)
    else:
        # Sin repeater_row_index: agrupar por COLUMNA y reconstruir por posición (línea 979-998 frontend)
        by_col: Dict[str, List] = {}
        for c in sub_normal:
            cid = c.get("id", "")
            by_col[cid] = sorted(
                [a for a in filtered if a.get("form_design_element_id") == cid],
                key=lambda a: (a.get("id_answer") or 0),
            )
        max_r = max((len(v) for v in by_col.values()), default=0)
        for i in range(max_r):
            rd: Dict[str, Any] = {}
            for c in sub_normal:
                cid = c.get("id", "")
                if i < len(by_col.get(cid, [])):
                    a = by_col[cid][i]
                    rd[cid] = {"answer_text": a.get("answer_text"),
                               "file_path":   a.get("file_path"),
                               "question_type": a.get("question_type")}
            if rd:
                sub_rows.append(rd)

    return sub_rows


# ── Clase principal ───────────────────────────────────────────────────────────

class FormPdfExporter:
    """
    Genera PDF/HTML de una respuesta de formulario
    replicando exactamente el componente FormResponseRenderer.
    """

    def __init__(
        self,
        form_design: list,
        answers: list,
        style_config: Optional[dict] = None,
        form_title: str = "",
        submitted_at: str = "",
        response_id: Optional[int] = None,
        filler_name: str = "",
        orientation: str = "landscape",
    ):
        self.form_design  = form_design
        self.answers      = answers
        self.style_config = style_config or {}
        self.form_title   = form_title
        self.submitted_at = submitted_at
        self.response_id  = response_id
        self.filler_name  = filler_name
        self.orientation  = "portrait" if orientation == "portrait" else "landscape"

        # Ancho útil de la hoja: en vertical hay bastante menos espacio, así
        # que los bloques de columnas del repeater tienen que ser más
        # angostos o la tabla se sale del papel.
        if self.orientation == "portrait":
            self.max_cols_main = 5
            self.max_cols_sub  = 4
        else:
            self.max_cols_main = MAX_COLS_MAIN
            self.max_cols_sub  = MAX_COLS_SUB

        # answersMap — mismo orden de prioridad que el frontend
        self._answers_map: Dict[str, Any] = {}
        for ans in answers:
            if ans.get("question_text"):
                self._answers_map[str(ans["question_text"])] = ans
            if ans.get("question_id") is not None:
                self._answers_map[str(ans["question_id"])] = ans
            if ans.get("form_design_element_id"):
                self._answers_map[str(ans["form_design_element_id"])] = ans

    # ── getAnswerForField ─────────────────────────────────────────────────────

    def _get_answer(self, field: dict) -> Optional[dict]:
        fid   = str(field.get("id") or "")
        props = field.get("props") or {}
        if fid and fid in self._answers_map:
            return self._answers_map[fid]
        lex = str(field.get("linkExternalId") or "")
        if lex and lex in self._answers_map:
            return self._answers_map[lex]
        sqid = str(props.get("sourceQuestionId") or "")
        if sqid and sqid in self._answers_map:
            return self._answers_map[sqid]
        lbl = str(props.get("label") or "")
        if lbl and lbl in self._answers_map:
            return self._answers_map[lbl]
        return None

    # ── shouldRenderLayout ────────────────────────────────────────────────────

    def _find_recursive(self, items: list, qid: str) -> Optional[dict]:
        for item in items:
            if str(item.get("id_question", "")) == qid:
                return item
            found = self._find_recursive(item.get("children") or [], qid)
            if found:
                return found
        return None

    def _should_render(self, layout: dict) -> bool:
        props = layout.get("props") or {}
        if not props.get("hidden"):
            return True
        condicion = str(props.get("condicion") or "")
        valor     = str(props.get("valor") or "")
        if not condicion or not valor:
            return False
        parts = condicion.split("-")
        if len(parts) < 2:
            return False
        cond_field = self._find_recursive(self.form_design, parts[1])
        if not cond_field:
            return False
        answer = self._get_answer(cond_field)
        current = str((answer or {}).get("answer_text", "") or "")
        allowed = [v.strip() for v in valor.split(",")]
        return current in allowed

    # ── HeaderTable ───────────────────────────────────────────────────────────

    def _render_header_table(self, ht: dict, logo: dict) -> str:
        cells = ht.get("cells") or []
        bw  = ht.get("borderWidth", "1px")
        bc  = ht.get("borderColor", "#000000")
        bd  = bw + " solid " + bc
        rows_html = []
        for row in cells:
            tds = []
            for cell in row:
                cs    = cell.get("colSpan", 1)
                rs    = cell.get("rowSpan", 1)
                cbg   = cell.get("backgroundColor", "#ffffff")
                cc    = cell.get("textColor") or cell.get("color", "#000000")
                cbord = cell.get("borderColor", bc)
                cbw2  = cell.get("borderWidth", bw)
                cpad  = cell.get("padding", "5px 8px")
                cal   = cell.get("align", "left")
                cfw   = "bold" if cell.get("bold", False) else "normal"
                cfs   = cell.get("fontSize", "11px")
                cont  = cell.get("content", "")
                is_logo = cell.get("customClass") == "logo-cell" or cont == "[LOGO]"
                if is_logo and logo.get("url"):
                    h     = logo.get("height", 44)
                    inner = '<img src="' + _e(logo["url"]) + '" alt="Logo" style="height:' + str(h) + 'px;max-width:100%;display:block;margin:auto;"/>'
                else:
                    inner = _e(cont) if (cont and cont != "[LOGO]") else ""
                cell_s = (
                    "background:{cbg};color:{cc};padding:{cpad};text-align:{cal};"
                    "font-weight:{cfw};font-size:{cfs};border:{cbw2} solid {cbord};vertical-align:middle;"
                ).format(cbg=cbg, cc=cc, cpad=cpad, cal=cal, cfw=cfw, cfs=cfs, cbw2=cbw2, cbord=cbord)
                tds.append(
                    '<td colspan="{cs}" rowspan="{rs}" style="{s}">{inner}</td>'.format(
                        cs=cs, rs=rs, s=cell_s, inner=inner
                    )
                )
            rows_html.append('<tr>' + "".join(tds) + '</tr>')
        return (
            '<table style="width:100%;border-collapse:collapse;border:' + bd + ';margin-bottom:14px;">'
            + "".join(rows_html) + '</table>'
        )

    def _header_html(self) -> str:
        sc    = self.style_config
        parts = []
        ht    = sc.get("headerTable") or {}
        if ht.get("enabled") and ht.get("cells"):
            parts.append(self._render_header_table(ht, sc.get("logo") or {}))
        logo = sc.get("logo") or {}
        has_logo_in_ht = False
        if ht.get("enabled") and ht.get("cells"):
            for row in ht["cells"]:
                for cell in row:
                    if cell.get("customClass") == "logo-cell" or cell.get("content") == "[LOGO]":
                        has_logo_in_ht = True
        if logo.get("url") and not has_logo_in_ht:
            align = logo.get("position", "left")
            h     = logo.get("height", 60)
            parts.append(
                '<div style="text-align:' + align + ';margin-bottom:16px;">'
                '<img src="' + _e(logo["url"]) + '" alt="Logo" style="height:' + str(h) + 'px;display:inline-block;"/>'
                '</div>'
            )
        return "\n".join(parts)

    def _footer_html(self) -> str:
        footer = (self.style_config or {}).get("footer") or {}
        if not footer.get("show"):
            return ""
        align = footer.get("align", "center")
        text  = _e(footer.get("text", ""))
        return (
            '<div style="text-align:' + align + ';margin-top:16px;padding-top:8px;'
            'border-top:1px solid rgba(0,0,0,0.1);font-size:0.8em;opacity:0.8;">'
            + text + '</div>'
        )

    # ── renderDecorativeElement ───────────────────────────────────────────────

    def _decorative(self, field: dict) -> str:
        ftype = field.get("type", "")
        props = field.get("props") or {}

        if ftype == "label":
            return (
                '<div style="font-size:{fs};font-weight:{fw};color:{c};'
                'text-align:{ta};margin-bottom:16px;">{t}</div>'.format(
                    fs=props.get("fontSize", "1rem"),
                    fw=props.get("fontWeight", "normal"),
                    c=props.get("color", "#333"),
                    ta=props.get("align", "left"),
                    t=_e(props.get("text", "Etiqueta de texto")),
                )
            )
        if ftype == "helpText":
            return (
                '<div style="font-size:{fs};color:{c};font-style:italic;margin-bottom:16px;">{t}</div>'.format(
                    fs=props.get("fontSize", "0.875rem"),
                    c=props.get("color", "#6B7280"),
                    t=_e(props.get("text", "Texto de ayuda")),
                )
            )
        if ftype == "divider":
            return (
                '<hr style="height:{h}px;background-color:{c};border:none;margin:16px 0;"/>'.format(
                    h=props.get("thickness", 1),
                    c=props.get("color", "#E5E7EB"),
                )
            )
        if ftype == "image":
            lbl     = _e(props.get("label", ""))
            lbl_html = ('<div style="margin-bottom:6px;font-size:12px;font-weight:500;">' + lbl + '</div>') if lbl else ""
            src     = props.get("src", "")
            if src:
                return lbl_html + '<div style="margin-bottom:16px;"><img src="' + _e(src) + '" alt="' + _e(props.get("alt", "")) + '" style="max-width:100%;height:auto;border-radius:8px;"/></div>'
            else:
                return lbl_html + '<div style="border:2px dashed #D1D5DB;border-radius:8px;padding:24px;text-align:center;color:#9CA3AF;margin-bottom:16px;">Sin imagen</div>'
        if ftype == "button":
            w = "100%" if props.get("fullWidth") else "auto"
            return (
                '<button disabled style="width:' + w + ';background:#D1D5DB;color:#6B7280;'
                'padding:6px 12px;border-radius:6px;border:none;margin-bottom:16px;">'
                + _e(props.get("text", "Bot\u00f3n")) + ' (deshabilitado)</button>'
            )
        return ""

    # ── renderInputFieldResponse ──────────────────────────────────────────────

    def _input_field(self, field: dict) -> str:
        props  = field.get("props") or {}
        label  = _e(props.get("label") or "Campo")
        req    = ('<span class="req">*</span>' if props.get("required") else "")
        answer = self._get_answer(field)
        ftype  = field.get("type", "")

        if answer is not None:
            atext = str(answer.get("answer_text") or "")
            fpath = str(answer.get("file_path") or "")
            qtype = str(answer.get("question_type") or ftype)

            if qtype == "firm" and atext:
                content_html = _fmt_firm(atext)
            elif qtype == "location" and atext:
                content_html = _fmt_location(atext)
            elif qtype in ("checkbox", "multiselect") and atext:
                content_html = _fmt_checkbox(atext)
            elif qtype == "number" and atext:
                content_html = _fmt_number(atext, props)
            elif qtype == "date" and atext:
                content_html = _fmt_date(atext)
            elif qtype in ("datetime", "datetimelocal") and atext:
                content_html = _fmt_datetime(atext)
            elif ftype == "table":
                content_html = self._render_table_field(props)
            elif atext:
                content_html = _e(atext)
            else:
                content_html = '<span class="field-empty">Sin respuesta</span>'

            file_html = (' <span class="file-badge">&#128206; Archivo adjunto</span>' if fpath else "")
            value_html = content_html + file_html
        else:
            value_html = '<span class="field-empty">Sin respuesta registrada</span>'

        return (
            '<div class="field-row">'
            '<div class="field-label">' + label + req + '</div>'
            '<div class="field-value">' + value_html + '</div>'
            '</div>'
        )

    def _render_table_field(self, props: dict) -> str:
        options = props.get("options") or []
        if not options:
            return '<span style="color:#9CA3AF;font-style:italic;">Sin datos</span>'
        rows = "".join(
            '<tr><td style="padding:4px 8px;border:1px solid #E5E7EB;">' + _e(str(o)) + '</td></tr>'
            for o in options
        )
        return '<table style="border-collapse:collapse;font-size:11px;">' + rows + '</table>'

    # ── renderRepeaterResponse ────────────────────────────────────────────────

    def _repeater(self, field: dict) -> str:
        props    = field.get("props") or {}
        children = field.get("children") or []

        normal_ch = [c for c in children if c.get("type") != "repeater"]
        sub_ch    = [c for c in children if c.get("type") == "repeater"]

        if not children:
            return (
                '<div style="margin-bottom:16px;padding:16px;text-align:center;'
                'color:#6B7280;border:2px dashed #D1D5DB;border-radius:8px;">'
                '<p>Tabla sin columnas configuradas</p></div>'
            )

        col_ids  = [c["id"] for c in normal_ch if c.get("id")]
        col_qids = [
            str(c.get("linkExternalId") or (c.get("props") or {}).get("sourceQuestionId") or "")
            for c in normal_ch
        ]
        col_qids = [q for q in col_qids if q]

        # ── PORT EXACTO de la línea 735 en ResponsesModal.tsx ──
        # repeaterAnswers = answers donde:
        #   • repeated_id es válido (no null/vacío)
        #   • NO tiene parent_repeated_id (excluye respuestas de sub-repeaters)
        #   • pertenece a una columna de ESTE repeater (por UUID o question_id)
        rep_answers = [
            ans for ans in self.answers
            if (ans.get("repeated_id") not in (None, "", "null"))
            and not ans.get("parent_repeated_id")
            and (
                (ans.get("form_design_element_id") and ans["form_design_element_id"] in col_ids)
                or (ans.get("question_id") and str(ans["question_id"]) in col_qids)
            )
        ]

        # Ordenar antes de agrupar para garantizar orden estable por fila
        rep_answers = sorted(
            rep_answers,
            key=lambda a: (
                a.get("repeater_row_index") if a.get("repeater_row_index") is not None else 999999,
                a.get("id_answer") or 0,
            )
        )

        # ── PORT EXACTO de la línea 755 en ResponsesModal.tsx ──
        # Agrupar por repeated_id, construir parentRows igual que el frontend
        grouped: Dict[str, List] = {}
        group_first_ri: Dict[str, int] = {}   # para sort secundario estable
        for ans in rep_answers:
            rid = str(ans["repeated_id"])
            if rid not in grouped:
                grouped[rid] = []
                group_first_ri[rid] = (
                    int(ans["repeater_row_index"]) if ans.get("repeater_row_index") is not None
                    else (ans.get("id_answer") or 0)
                )
            grouped[rid].append(ans)

        parent_rows: List[Dict] = []

        def _celda(candidatas: List[dict]) -> Optional[dict]:
            """De varias respuestas para la misma celda, gana la más reciente.

            Una celda puede tener más de una respuesta porque /save-answers/
            siempre inserta: al firmar quedaba el documento de quien iba a
            firmar y encima el certificado. La última escrita es la buena.
            """
            if not candidatas:
                return None
            a = max(candidatas, key=lambda x: (x.get("id_answer") or 0))
            return {
                "answer_text":   a.get("answer_text"),
                "file_path":     a.get("file_path"),
                "question_type": a.get("question_type"),
            }

        for repeated_id, grp in grouped.items():
            # answersByColumn: igual que frontend línea 763
            by_col: Dict[str, List] = {}
            for child in normal_ch:
                cid  = child.get("id", "")
                qid  = str(child.get("linkExternalId") or (child.get("props") or {}).get("sourceQuestionId", "") or "")
                col  = [a for a in grp if a.get("form_design_element_id") == cid]
                if not col and qid:
                    col = [a for a in grp if str(a.get("question_id", "")) == qid]
                # Ordenar por repeater_row_index si existe, sino por id_answer (línea 776-780)
                has_idx = any(a.get("repeater_row_index") is not None for a in col)
                col = sorted(col, key=lambda a: ((a.get("repeater_row_index") or 0) if has_idx else (a.get("id_answer") or 0)))
                by_col[cid] = col

            # La fila la manda repeater_row_index, igual que en el sub-repeater
            # (_build_sub_rows). Contar entradas por columna solo vale cuando el
            # dato no trae índice: si una columna tiene una entrada de más se
            # inventan filas y el resto queda corrido.
            hay_indice = any(a.get("repeater_row_index") is not None for a in grp)

            if hay_indice:
                por_fila: Dict[int, List] = {}
                for ans in grp:
                    por_fila.setdefault(ans.get("repeater_row_index") or 0, []).append(ans)

                for fila in sorted(por_fila):
                    del_grupo = por_fila[fila]
                    row_data: Dict[str, Any] = {}
                    for child in normal_ch:
                        cid = child.get("id", "")
                        qid = str(child.get("linkExternalId") or (child.get("props") or {}).get("sourceQuestionId", "") or "")
                        cands = [a for a in del_grupo if a.get("form_design_element_id") == cid]
                        if not cands and qid:
                            cands = [a for a in del_grupo if str(a.get("question_id", "")) == qid]
                        celda = _celda(cands)
                        if celda is not None:
                            row_data[cid] = celda
                    if row_data:
                        parent_rows.append({
                            "rowIndex":   fila,
                            "repeatedId": repeated_id,
                            "rowData":    row_data,
                        })
                continue

            max_r = max((len(v) for v in by_col.values()), default=1)

            # rowIndex es el ÍNDICE LOCAL dentro del grupo (igual que frontend línea 786)
            for row_index in range(max_r):
                row_data: Dict[str, Any] = {}
                for child in normal_ch:
                    cid = child.get("id", "")
                    col = by_col.get(cid, [])
                    if row_index < len(col):
                        a = col[row_index]
                        row_data[cid] = {
                            "answer_text":  a.get("answer_text"),
                            "file_path":    a.get("file_path"),
                            "question_type": a.get("question_type"),
                        }
                if row_data:
                    parent_rows.append({
                        "rowIndex":   row_index,   # índice LOCAL (igual que frontend)
                        "repeatedId": repeated_id,
                        "rowData":    row_data,
                    })

        # Sort por rowIndex (igual que frontend línea 808)
        # Sort secundario por group_first_ri para estabilidad cuando todos tienen rowIndex=0
        parent_rows.sort(key=lambda r: (r["rowIndex"], group_first_ri.get(r["repeatedId"], 999999)))

        n_parent_rows = len(parent_rows)

        ts = props.get("tableStyle") or {}
        bd    = "{bw} {bs} {bc}".format(
            bw=ts.get("borderWidth", "1px"),
            bs=ts.get("borderStyle", "solid"),
            bc=ts.get("borderColor", "#d1d5db"),
        )
        th_s  = ("background:{hbg};color:{htc};font-weight:{hfw};"
                 "text-align:{hta};padding:{hp};border:{bd};font-size:11px;").format(
            hbg=ts.get("headerBackgroundColor", "#f3f4f6"),
            htc=ts.get("headerTextColor", "#374151"),
            hfw=ts.get("headerFontWeight", "bold"),
            hta=ts.get("headerTextAlign", "left"),
            hp=ts.get("headerPadding", "12px"),
            bd=bd,
        )
        td_s  = ("background:{cbg};color:{ctc};"
                 "text-align:{cta};padding:{cp};"
                 "vertical-align:{cva};border:{bd};font-size:11px;").format(
            cbg=ts.get("cellBackgroundColor", "#ffffff"),
            ctc=ts.get("cellTextColor", "#374151"),
            cta=ts.get("cellTextAlign", "left"),
            cp=ts.get("cellPadding", "8px"),
            cva=ts.get("cellVerticalAlign", "middle"),
            bd=bd,
        )
        alt_bg  = ts.get("alternateRowColor", "#f9fafb")
        striped = ts.get("enableStripedRows", True)
        n_cols  = len(normal_ch) or 1

        table_body = ""
        if normal_ch:
            # th_s: inline styles del tableStyle configurado por el usuario
            th_s = (
                "background:{hbg};color:{htc};font-weight:{hfw};"
                "text-align:{hta};padding:{hp};border-right:1px solid {bc};font-size:10px;"
            ).format(
                hbg=ts.get("headerBackgroundColor", "#f3f4f6"),
                htc=ts.get("headerTextColor", "#374151"),
                hfw=ts.get("headerFontWeight", "bold"),
                hta=ts.get("headerTextAlign", "left"),
                hp=ts.get("headerPadding", "8px"),
                bc=ts.get("borderColor", "#d1d5db"),
            )
            # Filas renderizadas celda a celda: después se reparten entre bloques
            rendered_rows = []
            if parent_rows:
                for disp_idx, prow in enumerate(parent_rows):
                    row_data    = prow["rowData"]
                    repeated_id = prow["repeatedId"]
                    row_idx     = prow["rowIndex"]   # LOCAL index (igual que frontend)

                    is_alt = striped and disp_idx % 2 == 1
                    cbg  = alt_bg if is_alt else ts.get("cellBackgroundColor", "#ffffff")
                    td_s = (
                        "background:{cbg};color:{ctc};text-align:{cta};"
                        "padding:{cp};vertical-align:{cva};"
                        "border-bottom:1px solid {bc};border-right:1px solid {bc};font-size:10px;"
                    ).format(
                        cbg=cbg,
                        ctc=ts.get("cellTextColor", "#374151"),
                        cta=ts.get("cellTextAlign", "left"),
                        cp=ts.get("cellPadding", "8px"),
                        cva=ts.get("cellVerticalAlign", "middle"),
                        bc=ts.get("borderColor", "#d1d5db"),
                    )
                    cells = []
                    for child in normal_ch:
                        cid      = child.get("id", "")
                        lex      = str(child.get("linkExternalId") or "")
                        cell_val = row_data.get(cid) or (row_data.get(lex) if lex else None)
                        cell_html = _render_cell_value(cell_val) if cell_val else '<span class="cell-empty">-</span>'
                        cells.append(cell_html)

                    sub_html = ""
                    if sub_ch:
                        sub_html = "".join(
                            self._sub_repeater_for_row(
                                sf, row_idx, repeated_id, ts,
                                parent_field_id=str(field.get("id") or ""),
                                n_parent_rows=n_parent_rows,
                            )
                            for sf in sub_ch
                        )

                    rendered_rows.append({
                        "num": disp_idx + 1,
                        "td_s": td_s,
                        "cells": cells,
                        "sub": sub_html,
                    })

            # Si hay más columnas de las que caben a lo ancho, se apilan bloques
            blocks    = _split_columns(len(normal_ch), self.max_cols_main)
            multi     = len(blocks) > 1
            last_blk  = len(blocks) - 1
            num_th_s  = th_s + "width:22px;text-align:center;"
            tables    = []

            for b_i, (start, end) in enumerate(blocks):
                cols     = normal_ch[start:end]
                span     = len(cols) + (1 if multi else 0)
                dens     = _density(span)

                ths = ('<th style="' + num_th_s + dens + '">#</th>') if multi else ""
                ths += "".join(
                    '<th style="{s}">{lbl}{req}</th>'.format(
                        s=th_s + dens,
                        lbl=_e((c.get("props") or {}).get("label") or "Campo"),
                        req=('<span style="color:#ef4444;margin-left:3px;">*</span>' if (c.get("props") or {}).get("required") else ""),
                    )
                    for c in cols
                )

                table_body = ""
                if rendered_rows:
                    for r in rendered_rows:
                        tds = ""
                        if multi:
                            tds += (
                                '<td style="' + r["td_s"] + dens +
                                'text-align:center;color:#9ca3af;">' + str(r["num"]) + '</td>'
                            )
                        tds += "".join(
                            '<td style="' + r["td_s"] + dens + '">' + h + '</td>'
                            for h in r["cells"][start:end]
                        )
                        table_body += '<tr>' + tds + '</tr>'

                        # los sub-repeaters se pintan una sola vez, bajo el último bloque
                        if r["sub"] and b_i == last_blk:
                            table_body += (
                                '<tr><td colspan="{n}" class="sub-td">{sh}</td></tr>'
                            ).format(n=span, sh=r["sub"])
                else:
                    table_body = (
                        '<tr><td colspan="{n}" style="text-align:center;padding:12px;">'
                        '<span class="cell-empty">Sin datos registrados</span></td></tr>'
                    ).format(n=span or n_cols)

                caption = _block_caption(start, end, len(normal_ch)) if multi else ""
                tables.append(
                    '<div class="rep-block">' + caption +
                    '<table class="rep-table">'
                    '<thead><tr>' + ths + '</tr></thead>'
                    '<tbody>' + table_body + '</tbody>'
                    '</table></div>'
                )

            table_html = "".join(tables)
        else:
            table_html = ""

        # solo sub-repeaters (sin columnas normales)
        if not normal_ch and sub_ch:
            subs = ""
            pfid = str(field.get("id") or "")
            if parent_rows:
                for prow in parent_rows:
                    inner = "".join(
                        self._sub_repeater_for_row(
                            sf, prow["rowIndex"], prow["repeatedId"], ts,
                            parent_field_id=pfid,
                            n_parent_rows=n_parent_rows,
                        )
                        for sf in sub_ch
                    )
                    subs += (
                        '<div style="margin-bottom:12px;">'
                        '<div style="font-size:10px;color:#9CA3AF;margin-bottom:4px;">'
                        'Registro {n}</div>{inner}</div>'
                    ).format(n=prow["rowIndex"] + 1, inner=inner)
            else:
                subs = "".join(
                    self._sub_repeater_for_row(sf, 0, "", ts, parent_field_id=pfid, n_parent_rows=1)
                    for sf in sub_ch
                )
            table_html = '<div style="padding:8px 14px;">' + subs + '</div>'

        lbl = props.get("label", "")
        # No mostrar header en el PDF si el label es genérico / de UI
        skip_labels = ("agregar filas", "tabla de datos", "sub-tabla", "repetidor")
        show_header = bool(lbl) and not any(s in lbl.lower() for s in skip_labels)
        REP_SVG = ('<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                   'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                   '<rect x="3" y="3" width="18" height="18" rx="2"/>'
                   '<path d="M3 9h18M3 15h18M9 3v18"/></svg>')
        header_div = ('<div class="repeater-header">' + REP_SVG + _e(lbl) + '</div>') if show_header else ""

        return '<div class="repeater-wrap">' + header_div + table_html + '</div>'

    def _sub_repeater_for_row(
        self,
        sub_field: dict,
        parent_row_idx: int,           # rowIndex LOCAL del grupo (igual que frontend)
        parent_repeated_id: str,       # repeatedId del padre (UUID o "")
        parent_ts: dict,
        parent_field_id: str = "",     # field.id del repeater PADRE (para estrategia 2)
        n_parent_rows: int = 1,        # len(parentRows) — necesario para estrategia 3
    ) -> str:
        # IDs de columnas normales del sub-repeater (línea 874 frontend)
        sub_children = sub_field.get("children") or []
        sub_normal   = [c for c in sub_children if c.get("type") != "repeater"]
        sub_col_ids  = [c["id"] for c in sub_normal if c.get("id")]

        # Todas las respuestas de columnas de este sub-repeater (línea 880 frontend)
        all_sub = [
            ans for ans in self.answers
            if ans.get("form_design_element_id") in sub_col_ids
            and ans.get("repeated_id") not in (None, "", "null")
        ]
        if not all_sub:
            return ""

        # ── ESTRATEGIA 1 (línea 896-899 frontend) ──────────────────────────────
        # parent_repeated_id === UUID de la fila padre
        filtered = [
            a for a in all_sub
            if str(a.get("parent_repeated_id") or "") == str(parent_repeated_id or "")
            and (parent_repeated_id not in (None, "", "null"))
        ]

        # ── ESTRATEGIA 2 (línea 901-907 frontend) ──────────────────────────────
        # parent_repeated_id === field.id (id del repeater PADRE) + parent_row_index
        if not filtered and parent_field_id:
            filtered = [
                a for a in all_sub
                if str(a.get("parent_repeated_id") or "") == str(parent_field_id)
                and a.get("parent_row_index") == parent_row_idx
            ]

        # ── ESTRATEGIA 3 FALLBACK (línea 909-943 frontend) ─────────────────────
        # Porto EXACTAMENTE el fallback del frontend para datos sin parent_repeated_id
        if not filtered and all_sub:
            col_count        = len(sub_col_ids) or 1
            total_sub_rows   = round(len(all_sub) / col_count)
            total_parent_rows = max(1, n_parent_rows)
            sub_rows_per_parent = max(1, -(-total_sub_rows // total_parent_rows))  # ceil
            sub_row_start    = parent_row_idx * sub_rows_per_parent
            sub_row_end      = sub_row_start + sub_rows_per_parent

            has_ri = any(a.get("repeater_row_index") is not None for a in all_sub)
            if has_ri:
                # Filtrar por repeater_row_index absoluto en el rango [start, end)
                filtered = [
                    a for a in all_sub
                    if sub_row_start <= (a.get("repeater_row_index") or 0) < sub_row_end
                ]
            else:
                # Sin repeater_row_index: ordenar por id_answer y dividir por posición
                sorted_sub     = sorted(all_sub, key=lambda a: (a.get("id_answer") or 0))
                answers_per_parent = sub_rows_per_parent * col_count
                start_idx      = parent_row_idx * answers_per_parent
                filtered       = sorted_sub[start_idx: start_idx + answers_per_parent]

        if not filtered:
            return ""

        # ── Construir subRows (línea 958-1000 frontend) ─────────────────────────
        sub_rows = _build_sub_rows(filtered, sub_normal)

        if not sub_rows:
            return ""

        sts   = (sub_field.get("props") or {}).get("tableStyle") or parent_ts
        sbd   = "{bw} {bs} {bc}".format(
            bw=sts.get("borderWidth", "1px"),
            bs=sts.get("borderStyle", "solid"),
            bc=sts.get("borderColor", "#d1d5db"),
        )
        sth_s = ("background:{h};color:{c};font-weight:{fw};"
                 "text-align:{ta};padding:{p};border:{bd};font-size:10px;").format(
            h=sts.get("headerBackgroundColor", "#f3f4f6"),
            c=sts.get("headerTextColor", "#374151"),
            fw=sts.get("headerFontWeight", "bold"),
            ta=sts.get("headerTextAlign", "left"),
            p=sts.get("headerPadding", "8px"),
            bd=sbd,
        )
        std_s = ("background:{b};color:{c};"
                 "text-align:{ta};padding:{p};border:{bd};font-size:10px;").format(
            b=sts.get("cellBackgroundColor", "#ffffff"),
            c=sts.get("cellTextColor", "#374151"),
            ta=sts.get("cellTextAlign", "left"),
            p=sts.get("cellPadding", "6px 8px"),
            bd=sbd,
        )
        salt = sts.get("alternateRowColor", "#f9fafb")

        sts   = (sub_field.get("props") or {}).get("tableStyle") or parent_ts
        sbc   = sts.get("borderColor", "#d1d5db")
        sth_s = (
            "background:{h};color:{c};font-weight:{fw};text-align:{ta};"
            "padding:{p};border-right:1px solid {bc};font-size:9.5px;"
        ).format(
            h=sts.get("headerBackgroundColor", "#f3f4f6"),
            c=sts.get("headerTextColor", "#374151"),
            fw=sts.get("headerFontWeight", "bold"),
            ta=sts.get("headerTextAlign", "left"),
            p=sts.get("headerPadding", "7px 10px"),
            bc=sbc,
        )
        salt  = sts.get("alternateRowColor", "#f9fafb")
        scbg  = sts.get("cellBackgroundColor", "#ffffff")
        std_s = (
            "background:{b};color:{c};text-align:{ta};padding:{p};"
            "border-bottom:1px solid {bc};border-right:1px solid {bc};font-size:9.5px;"
        ).format(
            b=scbg,
            c=sts.get("cellTextColor", "#374151"),
            ta=sts.get("cellTextAlign", "left"),
            p=sts.get("cellPadding", "6px 10px"),
            bc=sbc,
        )

        SUB_SVG = ('<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                   'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
                   '<rect x="3" y="3" width="18" height="18" rx="2"/>'
                   '<path d="M3 9h18M3 15h18M9 3v18"/></svg>')
        sub_lbl = _e((sub_field.get("props") or {}).get("label") or "Sub-tabla")

        # Mismo corte por ancho que el repeater principal
        blocks = _split_columns(len(sub_normal), self.max_cols_sub)
        multi  = len(blocks) > 1
        tables = []

        for start, end in blocks:
            cols = sub_normal[start:end]
            span = len(cols) + (1 if multi else 0)
            dens = _density(span, base_font=9.5)

            ths = ('<th style="' + sth_s + dens + 'width:20px;text-align:center;">#</th>') if multi else ""
            ths += "".join(
                '<th style="' + sth_s + dens + '">'
                + _e((c.get("props") or {}).get("label") or "Campo") + '</th>'
                for c in cols
            )

            trs = ""
            for ri, rd in enumerate(sub_rows):
                row_bg  = salt if ri % 2 == 1 else scbg
                row_td  = std_s.replace("background:" + scbg, "background:" + row_bg) + dens
                tds = (
                    '<td style="' + row_td + 'text-align:center;color:#9ca3af;">'
                    + str(ri + 1) + '</td>'
                ) if multi else ""
                tds += "".join(
                    '<td style="' + row_td + '">'
                    + _render_cell_value(rd.get(c.get("id", ""))) + '</td>'
                    for c in cols
                )
                trs += '<tr>' + tds + '</tr>'

            caption = _block_caption(start, end, len(sub_normal)) if multi else ""
            tables.append(
                caption +
                '<table class="sub-table">'
                '<thead><tr>' + ths + '</tr></thead>'
                '<tbody>' + trs + '</tbody>'
                '</table>'
            )

        return (
            '<div class="sub-wrap">'
            '<div class="sub-header">' + SUB_SVG + sub_lbl + '</div>'
            + "".join(tables) +
            '</div>'
        )

    # ── renderField ───────────────────────────────────────────────────────────

    def _render_field(self, field: dict) -> str:
        ftype = field.get("type", "")
        if not ftype or not field.get("id"):
            return ""
        props = field.get("props") or {}

        if ftype == "verticalLayout":
            if not self._should_render(field):
                return ""
            spacing = int(props.get("spacing") or 2) * 4
            inner   = "".join(
                '<div style="margin-bottom:{g}px;">{c}</div>'.format(g=spacing, c=self._render_field(c))
                for c in (field.get("children") or [])
            )
            # Sin flex (ver _fmt_firm_cell): apilar en bloque y separar con
            # margen es equivalente aqui, y no pasa por el layout flex de
            # WeasyPrint, que se cae cuando un hijo no alcanza a caber.
            return '<div style="margin-bottom:16px;">{i}</div>'.format(i=inner)

        if ftype == "horizontalLayout":
            if not self._should_render(field):
                return ""
            gap = int(props.get("spacing") or 2) * 8
            ch_html = ""
            for child in (field.get("children") or []):
                space = int((child.get("props") or {}).get("space") or 3)
                w     = (space / 12) * 100
                ch_html += (
                    '<div style="display:inline-block;vertical-align:top;'
                    'width:{w:.4f}%;padding-left:{h}px;padding-right:{h}px;'
                    'box-sizing:border-box;min-width:0;">{c}</div>'
                ).format(w=w, h=gap / 2, c=self._render_field(child))
            # Columnas con inline-block en vez de flex — es el mismo patron que
            # ya usa _render_all_fields, y evita el layout flex de WeasyPrint.
            # Los hijos van concatenados sin espacios en blanco entre ellos, asi
            # que no aparecen huecos fantasma entre columnas.
            return (
                '<div style="'
                'margin-left:-{h}px;margin-right:-{h}px;'
                'width:calc(100% + {g}px);box-sizing:border-box;margin-bottom:16px;">{ch}</div>'
            ).format(h=gap / 2, g=gap, ch=ch_html)

        if ftype in ("label", "helpText", "divider", "image", "button"):
            return self._decorative(field)
        if ftype == "repeater":
            return self._repeater(field)
        return self._input_field(field)

    # ── renderFieldsWithAutoLayout ────────────────────────────────────────────

    def _render_all_fields(self) -> str:
        """Render todos los campos, ignorando dicts de config sin type."""
        items = ""
        for field in self.form_design:
            ftype = field.get("type", "")
            if not ftype:
                continue  # objeto style_config embebido, omitir
            rendered = self._render_field(field)
            if not rendered:
                continue
            space = int((field.get("props") or {}).get("space") or 12)
            w     = (space / 12) * 100
            if w >= 100 or ftype in ("horizontalLayout", "verticalLayout", "repeater"):
                items += '<div style="margin-bottom:10px;">' + rendered + '</div>'
            else:
                items += (
                    '<div style="display:inline-block;width:{w:.1f}%;'
                    'vertical-align:top;padding-right:8px;margin-bottom:10px;">{f}</div>'
                ).format(w=w, f=rendered)
        return '<div>' + items + '</div>'

    # ── HTML completo ─────────────────────────────────────────────────────────

    def _qr_html(self) -> str:
        """Genera QR de verificacion para el PDF."""
        if not self.response_id:
            return ""
        try:
            import qrcode
        except ImportError:
            return ""
        try:
            from app.core.security import SECRET_KEY
            qr_secret = hashlib.sha256(f"qr-view-{SECRET_KEY}".encode()).digest()
            ts = int(time.time())
            payload = struct.pack(">II", self.response_id, ts)
            sig = hmac.new(qr_secret, payload, hashlib.sha256).digest()[:16]
            raw = payload + sig
            token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

            frontend_url = os.getenv("FRONTEND_URL", "https://safemetrics-sfi-dev.service.saferut.com")
            url = f"{frontend_url}/public/response/{token}"

            # box_size más grande → el PNG sale con más resolución nativa, no
            # solo estirado por CSS: se ve nítido al agrandarlo.
            qr = qrcode.QRCode(version=1, box_size=6, border=2,
                               error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()

            return (
                '<div style="position:fixed;top:8px;right:8px;text-align:center;opacity:0.9;">'
                f'<img src="data:image/png;base64,{b64}" style="width:78px;height:78px;"/>'
                '<div style="font-size:6px;color:#94a3b8;margin-top:1px;">Verificar</div>'
                '</div>'
            )
        except Exception:
            return ""

    def _build_html(self) -> str:
        sc = self.style_config
        bg  = sc.get("backgroundColor") or "#ffffff"
        ff  = (sc.get("font") or {}).get("family", "Arial, sans-serif")
        fs  = (sc.get("font") or {}).get("size", "13px")
        fc  = (sc.get("font") or {}).get("color", "#111827")
        br  = sc.get("borderRadius") or "0"
        bw  = sc.get("borderWidth") or ""
        bc  = sc.get("borderColor") or ""
        bdr = ("border:{bw} solid {bc};".format(bw=bw, bc=bc)) if bw and bc else ""
        css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: """ + ff + """;
    font-size: 10px;
    color: """ + fc + """;
    background: #f0f2f5;
    padding: 0;
    line-height: 1.5;
}
.page-wrapper {
    background: """ + bg + """;
    border-radius: """ + br + """;
    """ + bdr + """
    max-width: 100%;
    padding: 0;
}
/* ── Metadata strip ── */
/* Sin flex a proposito: el flexbox de WeasyPrint revienta cuando un hijo no
   alcanza a caber (flex.py:253, 'NoneType' has no attribute 'height'). Estas
   son filas de una sola linea, con inline-block quedan igual y no se caen. */
.meta-strip {
    padding: 7px 14px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    font-size: 9px;
    color: #64748b;
}
.meta-strip .resp-badge {
    background: #0f8594;
    color: #fff;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 99px;
    font-size: 9px;
    letter-spacing: 0.03em;
}
.meta-strip .dot { color: #cbd5e1; }
.meta-strip > span { display: inline-block; vertical-align: middle; margin-right: 8px; }

/* ── Fields area ── */
.fields-area { padding: 16px 18px 10px 18px; }

/* ── Field row (label arriba, value abajo) — match con FormResponseRenderer ── */
.field-row {
    display: block;
    width: 100%;
    margin-bottom: 16px;       /* mb-4 */
}
.field-label {
    display: block;
    font-weight: 500;          /* font-medium */
    font-size: 11px;           /* label-text */
    color: #1f2937;            /* gray-800 — default Tailwind label color */
    margin-bottom: 4px;
    word-break: break-word;
    line-height: 1.4;
}
.field-label .req {
    color: #ef4444;            /* text-red-500, igual que en FormResponseRenderer */
    margin-left: 3px;
    font-weight: 500;
}
.field-value {
    display: block;
    padding: 12px;             /* p-3 */
    font-size: 11px;
    color: #1f2937;            /* text-gray-800 */
    background: #f9fafb;       /* bg-gray-50 — igual al UI */
    border: 1px solid #e5e7eb; /* border-gray-200 — igual al UI */
    border-radius: 6px;        /* rounded-md */
    min-height: 30px;
    line-height: 1.5;
    word-break: break-word;
}
.field-value > * { vertical-align: middle; }
.field-empty {
    color: #9ca3af;            /* text-gray-400 */
    font-style: italic;
    font-size: 11px;
}

/* ── Repeater wrapper ── */
.repeater-wrap {
    margin-bottom: 16px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.repeater-header {
    padding: 8px 12px;
    background: #0CA4A5;        /* teal exacto del UI (FormResponseRenderer) */
    color: #fff;
    font-size: 11px;
    font-weight: 600;           /* font-weight 600 igual al UI */
    letter-spacing: 0.03em;
    text-transform: none;       /* el UI no lo pone uppercase */
}
.repeater-header svg { vertical-align: middle; margin-right: 6px; }

/* ── Repeater table ── */
.rep-table {
    width: 100%;
    max-width: 100%;
    border-collapse: collapse;
}
/* th y td usan inline styles del tableStyle del usuario */

/* Bloque de columnas: cuando el repeater es muy ancho se parte en varios */
.rep-block + .rep-block { margin-top: 10px; }
.rep-block-caption {
    font-size: 8.5px;
    font-weight: 600;
    color: #0CA4A5;
    background: #f1f5f9;
    padding: 3px 12px;
    border-top: 1px solid #e2e8f0;
    letter-spacing: 0.02em;
}

/* Nada de contenido puede empujar la tabla fuera del papel */
.rep-table th, .rep-table td,
.sub-table th, .sub-table td {
    word-break: break-word;
    overflow-wrap: anywhere;
}
.rep-table img, .sub-table img {
    max-width: 100% !important;
    height: auto !important;
}

/* ── Sub-repeater ── */
.sub-wrap {
    margin: 6px 0 6px 0;
    border-left: 3px solid #0CA4A5;
    border-radius: 0 6px 6px 0;
    overflow: hidden;
    background: #f8fafc;
}
.sub-header {
    padding: 5px 10px;
    background: #e6f7f8;
    color: #0CA4A5;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: none;
    border-bottom: 1px solid #b2e8ec;
}
.sub-header svg { vertical-align: middle; margin-right: 5px; }
.sub-table {
    width: 100%;
    max-width: 100%;
    border-collapse: collapse;
}
.sub-table + .rep-block-caption { margin-top: 6px; }
/* th y td usan inline styles del tableStyle del usuario */

/* ── File badge ── */
.file-badge {
    font-size: 8.5px;
    color: #2563eb;
    background: #eff6ff;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid #bfdbfe;
}

.sub-td {
    padding: 6px 10px 10px 18px;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
}

/* ── Empty cell ── */
.cell-empty { color: #9ca3af; font-style: italic; }

/* ── Page ── */
/* Margen superior ampliado: dentro de esa franja va el encabezado
   `position:fixed` con título + quien diligenció, que por eso SÍ se repite
   en cada hoja nueva (antes solo estaba en el flujo normal del documento,
   así que aparecía una única vez, en la primera página). */
@page {
    size: letter """ + self.orientation + """;
    margin: 26mm 14mm 12mm 14mm;
}
table { border-collapse: collapse; }
img { max-width: 100%; }
"""
        resp_id    = self.response_id
        sub_at     = str(self.submitted_at or "")[:19].replace("T", " ")

        # Encabezado fijo: se repite en TODAS las hojas (vive en la franja
        # de margen superior, no en el flujo normal del contenido).
        header_bits = []
        if self.form_title:
            header_bits.append(
                '<div style="font-size: 15px; font-weight: 700; color: #0f172a;'
                ' line-height: 1.25; letter-spacing: -0.01em;">'
                + _e(self.form_title) + '</div>'
            )
        meta_parts = []
        if self.filler_name:
            meta_parts.append('<span>' + _e(self.filler_name) + '</span>')
        if resp_id:
            meta_parts.append('<span class="resp-badge">Respuesta #' + str(resp_id) + '</span>')
        if sub_at:
            meta_parts.append('<span>' + _e(sub_at) + '</span>')
        if meta_parts:
            header_bits.append(
                '<div class="meta-strip" style="padding:0;background:transparent;border:0;'
                'font-size: 8.5px; color: #64748b; margin-top: 3px;">'
                + '<span class="dot">●</span>'.join(meta_parts) + '</div>'
            )
        fixed_header_html = (
            '<div style="position:fixed;top:6mm;left:14mm;right:95px;">'
            + "".join(header_bits) + '</div>'
        ) if header_bits else ""

        return (
            "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n"
            "<meta charset=\"UTF-8\"/>\n<style>\n" + css + "\n</style>\n</head>\n<body>\n"
            '<div class="page-wrapper">\n'
            + fixed_header_html + "\n"
            + '<div class="fields-area">'
            + self._header_html()
            + self._render_all_fields()
            + '</div>'
            + self._footer_html()
            + self._qr_html()
            + "\n</div>\n</body>\n</html>"
        )

    # ── API pública ───────────────────────────────────────────────────────────

    def generate(self) -> BytesIO:
        try:
            from weasyprint import HTML as WH
        except Exception as exc:                      # ImportError y OSError de libs nativas
            logger.exception("weasyprint no se pudo importar")
            raise RuntimeError("weasyprint no disponible: %s" % exc)
        buf = BytesIO()
        WH(string=self._build_html(), url_fetcher=_safe_url_fetcher).write_pdf(buf)
        buf.seek(0)
        return buf

    def generate_html(self) -> str:
        return self._build_html()


def generate_form_pdf(
    form_design: list,
    answers: list,
    style_config: Optional[dict] = None,
    form_title: str = "",
    submitted_at: str = "",
    response_id: Optional[int] = None,
    filler_name: str = "",
    orientation: str = "landscape",
) -> BytesIO:
    return FormPdfExporter(
        form_design=form_design,
        answers=answers,
        style_config=style_config,
        form_title=form_title,
        submitted_at=submitted_at,
        response_id=response_id,
        filler_name=filler_name,
        orientation=orientation,
    ).generate()