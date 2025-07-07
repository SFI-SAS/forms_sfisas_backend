# pdf_generator_api/src/services/pdf_service.py

import io
import logging
from jinja2 import Environment
from weasyprint import HTML, CSS
from typing import List, Dict, Any, Optional, Union


from app.api.schemas.form_data import FormData

# Configurar logging para el servicio
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class PdfGeneratorService:
    def __init__(self, templates_env: Environment):
        """
        Inicializa el servicio con el entorno de plantillas de Jinja2.
        """
        self.templates_env = templates_env

    def _generate_header_html(self, header_table_config: Dict[str, Any], logo_url: Optional[str]) -> str:
        """
        Genera el HTML para el encabezado del documento a partir de la configuración.
        """
        if not header_table_config.get("enabled", False):
            return ""

        cells_data = header_table_config.get("cells", [])
        
        # Usar f-string para construir la tabla de encabezado, aplicando estilos CSS directamente
        # FIX: Corregido border-collapse para usar 'collapse' o 'separate'
        header_html = f"<table style='width: {header_table_config.get('width', '100%')}; border-collapse: {'collapse' if header_table_config.get('borderCollapse', True) else 'separate'}; border: {header_table_config.get('borderWidth', '1px')} solid {header_table_config.get('borderColor', '#000000')};'>"
        
        for row_index, row in enumerate(cells_data):
            header_html += "<tr>"
            for col_index, cell in enumerate(row):
                # Generar estilos en línea para la celda
                cell_styles = [
                    f"text-align: {cell.get('textAlign', 'left')}",
                    f"font-size: {cell.get('fontSize', '12px')}",
                    f"color: {cell.get('textColor', '#000000')}",
                    f"background-color: {cell.get('backgroundColor', '#ffffff')}",
                    f"border: {cell.get('borderWidth', '1px')} solid {cell.get('borderColor', '#dddddd')}",
                    f"font-weight: {'bold' if cell.get('bold', False) else 'normal'}",
                ]
                
                # Manejar el logo
                cell_content = cell.get('content', '')
                if "[LOGO]" in cell_content and logo_url:
                    cell_content = cell_content.replace("[LOGO]", f"<img src='{logo_url}' style='max-width: 100px; max-height: 50px; vertical-align: middle;'>")
                    logging.info("Logo URL provided and [LOGO] placeholder found in header. Image will be rendered.")
                elif "[LOGO]" in cell_content and not logo_url:
                    cell_content = cell_content.replace("[LOGO]", " ") # Reemplazar con espacio si no hay URL
                    logging.warning("Placeholder [LOGO] found in header but no logo_url provided. Replacing with empty space to avoid rendering issues.")
                
                # Agregar customClass si existe
                custom_class = cell.get('customClass', '')
                class_attr = f"class='{custom_class}'" if custom_class else ""

                header_html += f"<td colspan='{cell.get('colSpan', 1)}' rowspan='{cell.get('rowSpan', 1)}' style='{' '.join(cell_styles)}' {class_attr}>{cell_content}</td>"
            header_html += "</tr>"
        header_html += "</table>"

        return header_html

    def _get_reduced_margin_css(self) -> str:
        """
        Genera CSS para reducir los márgenes del PDF.
        """
        return """
        @page {
            margin: 0.5cm;  /* Margen muy pequeño: 0.5cm en todos los lados */
            /* Alternativamente puedes usar: */
            /* margin-top: 0.5cm;
               margin-right: 0.5cm;
               margin-bottom: 0.5cm;
               margin-left: 0.5cm; */
        }
        
        body {
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
        }
        
        /* Reducir espaciado entre elementos */
        h1, h2, h3, h4, h5, h6 {
            margin-top: 0.5em;
            margin-bottom: 0.3em;
        }
        
        p {
            margin-top: 0.2em;
            margin-bottom: 0.2em;
        }
        
        table {
            margin-top: 0.2em;
            margin-bottom: 0.2em;
        }
        """

    def generate_pdf(self, form_data: Union[FormData, Dict[str, Any]]) -> bytes:
        """
        Genera un documento PDF a partir de los datos del formulario.
        Acepta tanto objetos FormData como diccionarios.
        """
        logging.info(f"Received request to generate PDF.")
        
        # Determinar si form_data es un objeto o un diccionario
        if isinstance(form_data, dict):
            # Si es un diccionario, acceder por claves
            response_id = form_data.get('response_id')
            form_info = form_data.get('form', {})
            submitted_at = form_data.get('submitted_at', 'N/A')
            approval_status = form_data.get('approval_status')
            form_message = form_data.get('message')
            answers = form_data.get('answers', [])
        else:
            # Si es un objeto FormData, acceder por atributos
            response_id = form_data.response_id
            form_info = form_data.form
            submitted_at = form_data.submitted_at if form_data.submitted_at else 'N/A'
            approval_status = form_data.approval_status
            form_message = form_data.message
            answers = form_data.answers
        
        logging.info(f"Processing form response with ID: {response_id}")

        html_content = None # Inicializar html_content

        try:
            logging.info(f"Starting PDF generation for response_id: {response_id}")

            # 1. Cargar la plantilla Jinja2
            template = self.templates_env.get_template('form_document.html')
            logging.info(f"Jinja2 template 'form_document.html' loaded.")

            # Preparar datos para la plantilla
            if isinstance(form_info, dict):
                form_title = form_info.get('title', '')
                form_description = form_info.get('description', '')
                form_design = form_info.get('form_design', [])
            else:
                form_title = form_info.title
                form_description = form_info.description
                form_design = form_info.form_design

            # Extraer la configuración del encabezado y el logo
            header_table_config = {}
            logo_url = None
            if form_design:
                for item in form_design:
                    if isinstance(item, dict):
                        props = item.get('props', {})
                        style_config = props.get('styleConfig', {}) if props else {}
                    else:
                        props = item.props
                        style_config = props.styleConfig if props and props.styleConfig else {}
                    
                    if style_config:
                        if isinstance(style_config, dict):
                            logo_config = style_config.get('logo', {})
                            if logo_config and logo_config.get('url'):
                                logo_url = str(logo_config['url'])
                            header_table = style_config.get('headerTable', {})
                            if header_table and header_table.get('enabled'):
                                header_table_config = header_table
                        else:
                            if style_config.logo and style_config.logo.url:
                                logo_url = str(style_config.logo.url)
                            if style_config.headerTable and style_config.headerTable.enabled:
                                header_table_config = style_config.headerTable.dict()
                        break

            # Generar el HTML del encabezado
            header_html = self._generate_header_html(header_table_config, logo_url)
            logging.info(f"Generated header HTML (first 200 chars): {header_html[:200]}...")
            if header_table_config:
                logging.info(f"Header table configuration found and processed.")

            # Extraer texto del footer
            footer_text = None
            if form_design:
                for item in form_design:
                    if isinstance(item, dict):
                        props = item.get('props', {})
                        style_config = props.get('styleConfig', {}) if props else {}
                    else:
                        props = item.props
                        style_config = props.styleConfig if props and props.styleConfig else {}
                    
                    if style_config:
                        if isinstance(style_config, dict):
                            footer_config = style_config.get('footer', {})
                            if footer_config and footer_config.get('show'):
                                footer_text = footer_config.get('text')
                                logging.info(f"Footer text found: '{footer_text}'")
                        else:
                            if style_config.footer and style_config.footer.show:
                                footer_text = style_config.footer.text
                                logging.info(f"Footer text found: '{footer_text}'")
                        break

            # Procesar respuestas
            processed_answers = []
            for answer in answers:
                if isinstance(answer, dict):
                    processed_answers.append({
                        'question_text': answer.get('question_text', ''),
                        'answer_text': answer.get('answer_text', ''),
                        'question_type': answer.get('question_type', ''),
                        'file_path': answer.get('file_path', ''),
                    })
                else:
                    processed_answers.append({
                        'question_text': answer.question_text,
                        'answer_text': answer.answer_text,
                        'question_type': answer.question_type,
                        'file_path': answer.file_path,
                    })
            logging.info(f"Processed {len(processed_answers)} answers.")

            template_data = {
                'form_title': form_title,
                'form_description': form_description,
                'submitted_at': submitted_at,
                'approval_status': approval_status,
                'form_message': form_message,
                'header_html': header_html,
                'footer_text': footer_text, # Pasar el texto del footer a la plantilla
                'answers': processed_answers,
                'response_id': response_id,
            }
            logging.info(f"Template data prepared.")

            # 3. Renderizar la plantilla con los datos
            html_content = template.render(template_data)
            logging.info(f"HTML content rendered successfully. First 500 chars: {html_content[:500]}...")
            
     
            # 4. Generar el PDF usando WeasyPrint con márgenes reducidos
            pdf_buffer = io.BytesIO()
            
            # Crear CSS para márgenes reducidos
            margin_css = CSS(string=self._get_reduced_margin_css())
            
            # Generar PDF con CSS personalizado
            HTML(string=html_content).write_pdf(pdf_buffer, stylesheets=[margin_css])
            pdf_buffer.seek(0) # Mueve el puntero al inicio del buffer

            pdf_bytes = pdf_buffer.getvalue()
            
            if not pdf_bytes:
                logging.warning("WeasyPrint generated empty PDF bytes. This usually indicates an issue with the HTML content or WeasyPrint installation.")
            else:
                logging.info(f"PDF generated successfully by WeasyPrint with reduced margins, size: {len(pdf_bytes)} bytes.")
            
            return pdf_bytes

        except Exception as e:
            logging.error(f"Error durante la generación del PDF: {e}", exc_info=True)
            if html_content:
                logging.error(f"HTML content before error (first 500 chars): {html_content[:500]}...")
            else:
                logging.error("HTML content was not generated before the error occurred.")
            raise # Re-lanza la excepción para que FastAPI la maneje