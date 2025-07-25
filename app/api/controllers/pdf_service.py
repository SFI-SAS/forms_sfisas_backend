# pdf_generator_api/src/services/pdf_service.py

import io
import os
import base64
import logging
from jinja2 import Environment
import qrcode
from weasyprint import HTML, CSS
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urljoin, urlparse
import requests
from pathlib import Path

from app.api.schemas.form_data import FormData

# Configurar logging para el servicio
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class PdfGeneratorService:
    def __init__(self, templates_env, upload_folder: str, base_url: str = "http://localhost:4321"):
        self.templates_env = templates_env
        self.upload_folder = upload_folder
        self.base_url = base_url  # Base URL de tu aplicación

    def _generate_qr_code(self, url: str) -> str:
        """
        Genera un código QR para la URL dada y lo retorna como base64 string.
        """
        try:
            # Crear el código QR
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)

            # Crear imagen del QR
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Convertir a base64
            buffered = io.BytesIO()
            qr_image.save(buffered, format="PNG")
            qr_base64 = base64.b64encode(buffered.getvalue()).decode()
            
            return f"data:image/png;base64,{qr_base64}"
            
        except Exception as e:
            logging.error(f"Error generating QR code: {e}")
            return None


    def _should_show_qr_for_response(self, response: dict) -> bool:
        """
        Determina si debe mostrar QR en lugar de la información detallada.
        Retorna True si hay información de aprobaciones o datos generales significativos.
        """
        # Verificar si hay aprobaciones
        has_approvals = response.get('approvals') and len(response.get('approvals', [])) > 0
        
        # Verificar si hay información general significativa
        has_general_info = (
            response.get('response_id') or 
            response.get('submitted_at') or 
            response.get('approval_status') or 
            response.get('message')
        )
        
        return has_approvals or has_general_info
    def _convert_image_to_base64(self, image_path: str) -> Optional[str]:
        """
        Convierte una imagen local a base64 para uso en WeasyPrint.
        
        Args:
            image_path: Ruta de la imagen
            
        Returns:
            String base64 de la imagen o None si hay error
        """
        try:
            # Verificar si el archivo existe
            if not os.path.exists(image_path):
                logging.error(f"Image file not found: {image_path}")
                return None
            
            # Determinar el tipo MIME basado en la extensión
            file_extension = Path(image_path).suffix.lower()
            mime_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml'
            }
            
            mime_type = mime_types.get(file_extension, 'image/png')
            
            # Leer y convertir a base64
            with open(image_path, 'rb') as image_file:
                image_data = image_file.read()
                base64_data = base64.b64encode(image_data).decode('utf-8')
                base64_url = f"data:{mime_type};base64,{base64_data}"
                
                logging.info(f"✅ Image converted to base64. Size: {len(image_data)} bytes, Type: {mime_type}")
                return base64_url
                
        except Exception as e:
            logging.error(f"Error converting image to base64: {e}")
            return None

    def _download_remote_image_to_base64(self, url: str) -> Optional[str]:
        """
        Descarga una imagen remota y la convierte a base64.
        
        Args:
            url: URL de la imagen remota
            
        Returns:
            String base64 de la imagen o None si hay error
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Determinar el tipo MIME de la respuesta
            content_type = response.headers.get('content-type', 'image/png')
            
            # Convertir a base64
            image_data = response.content
            base64_data = base64.b64encode(image_data).decode('utf-8')
            base64_url = f"data:{content_type};base64,{base64_data}"
            
            logging.info(f"✅ Remote image downloaded and converted to base64. Size: {len(image_data)} bytes")
            return base64_url
            
        except Exception as e:
            logging.error(f"Error downloading remote image: {e}")
            return None
    def _process_logo_url(self, logo_url: str) -> Optional[str]:
        """
        Procesa la URL del logo y la convierte a base64 para WeasyPrint.
        WeasyPrint funciona mejor con imágenes en base64.
        """
        if not logo_url:
            logging.warning("Logo URL is empty")
            return None
        
        logging.info(f"Processing logo URL: {logo_url}")
        
        # Si ya es base64, devolverlo tal como está
        if logo_url.startswith('data:image'):
            logging.info("Logo is already base64 encoded")
            return logo_url
        
        # Si es una URL HTTP/HTTPS, descargar y convertir a base64
        if logo_url.startswith(('http://', 'https://')):
            logging.info("Logo is remote URL, downloading...")
            return self._download_remote_image_to_base64(logo_url)
        
        # Si es una ruta local, convertir a base64
        full_path = None
        
        # ✅ NUEVO: Detectar si es una ruta que viene del endpoint upload-logo
        if logo_url.startswith('logo/'):
            # Construir la ruta completa usando upload_folder
            full_path = os.path.join(self.upload_folder, logo_url.replace('logo/', ''))
            logging.info(f"Logo path from upload endpoint: {full_path}")
        elif logo_url.startswith('/'):
            # Ruta absoluta
            full_path = logo_url
        elif logo_url.startswith('./'):
            # Ruta relativa desde el directorio actual
            full_path = os.path.abspath(logo_url)
        else:
            # Nombre de archivo, construir la ruta usando upload_folder
            full_path = os.path.join(self.upload_folder, logo_url)
        
        logging.info(f"Attempting to load local image: {full_path}")
        
        # ✅ NUEVO: Buscar logo automáticamente si no se especifica archivo
        if not os.path.exists(full_path):
            logging.warning(f"Logo file not found: {full_path}")
            
            # Buscar automáticamente en la carpeta logo
            logo_file = self._find_logo_file()
            if logo_file:
                full_path = logo_file
                logging.info(f"Found logo automatically: {full_path}")
            else:
                logging.error(f"No logo file found in {self.upload_folder}")
                return None
        
        return self._convert_image_to_base64(full_path)
    def _find_logo_file(self) -> Optional[str]:
        """
        Busca automáticamente el archivo de logo en la carpeta de uploads.
        Busca archivos que comiencen con 'logo.' y tengan extensiones válidas.
        """
        if not os.path.exists(self.upload_folder):
            logging.warning(f"Upload folder does not exist: {self.upload_folder}")
            return None
        
        valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']
        
        try:
            # Buscar archivos en la carpeta logo
            for file in os.listdir(self.upload_folder):
                file_lower = file.lower()
                # Buscar archivos que comiencen con 'logo.'
                if file_lower.startswith('logo.'):
                    file_path = os.path.join(self.upload_folder, file)
                    if os.path.isfile(file_path):
                        file_ext = os.path.splitext(file_lower)[1]
                        if file_ext in valid_extensions:
                            logging.info(f"Found logo file: {file_path}")
                            return file_path
            
            # Si no encuentra logo.*, buscar cualquier archivo de imagen
            for file in os.listdir(self.upload_folder):
                file_lower = file.lower()
                file_path = os.path.join(self.upload_folder, file)
                if os.path.isfile(file_path):
                    file_ext = os.path.splitext(file_lower)[1]
                    if file_ext in valid_extensions:
                        logging.info(f"Found image file as logo: {file_path}")
                        return file_path
        
        except Exception as e:
            logging.error(f"Error searching for logo file: {e}")
        
        return None
    def _generate_header_html(self, header_table_config: Dict[str, Any], logo_url: Optional[str]) -> str:
        """
        Genera el HTML para el encabezado del documento a partir de la configuración.
        """
        if not header_table_config.get("enabled", False):
            return ""

        cells_data = header_table_config.get("cells", [])
        
        # ✅ MEJORADO: Procesar la URL del logo con mejor manejo
        processed_logo_url = None
        if logo_url:
            processed_logo_url = self._process_logo_url(logo_url)
        
        # ✅ NUEVO: Si no hay logo_url especificada, buscar automáticamente
        if not processed_logo_url:
            logging.info("No logo URL specified, searching for logo file automatically...")
            logo_file = self._find_logo_file()
            if logo_file:
                processed_logo_url = self._convert_image_to_base64(logo_file)
                logging.info("✅ Logo found automatically and converted to base64")
        
        # Usar f-string para construir la tabla de encabezado
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
                    f"padding: {cell.get('padding', '8px')}",
                ]
                
                # Manejar el logo con conversión a base64
                cell_content = cell.get('content', '')
                
                if "[LOGO]" in cell_content:
                    if processed_logo_url:
                        # Crear imagen con base64 - WeasyPrint funciona mejor así
                        logo_img = f"""<img src='{processed_logo_url}' 
                                    style='max-width: 120px; 
                                            max-height: 60px; 
                                            height: auto; 
                                            width: auto; 
                                            object-fit: contain;
                                            vertical-align: middle; 
                                            display: block; 
                                            margin: 0 auto;' 
                                    alt='Logo' />"""
                        cell_content = cell_content.replace("[LOGO]", logo_img)
                        logging.info(f"✅ Logo successfully inserted into header (base64)")
                    else:
                        # Placeholder cuando no hay logo o hay error
                        placeholder = """<div style='width: 120px; height: 60px; 
                                                border: 2px dashed #ccc; 
                                                display: flex; 
                                                align-items: center; 
                                                justify-content: center; 
                                                margin: 0 auto; 
                                                font-size: 10px; 
                                                color: #999;
                                                background-color: #f9f9f9;'>
                                        <span>Logo no disponible</span>
                                    </div>"""
                        cell_content = cell_content.replace("[LOGO]", placeholder)
                        logging.warning("⚠️ Logo not available, using placeholder")
                
                # Agregar customClass si existe
                custom_class = cell.get('customClass', '')
                class_attr = f"class='{custom_class}'" if custom_class else ""

                header_html += f"<td colspan='{cell.get('colSpan', 1)}' rowspan='{cell.get('rowSpan', 1)}' style='{' '.join(cell_styles)}' {class_attr}>{cell_content}</td>"
            header_html += "</tr>"
        header_html += "</table>"

        logging.info(f"Header HTML generated. Length: {len(header_html)} chars")
        return header_html

    def _get_reduced_margin_css(self) -> str:
        """
        Genera CSS para reducir los márgenes del PDF.
        """
        return """
        @page {
            margin: 0.5cm;
        }
        
        body {
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
        }
        
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
        
        /* Estilos específicos para imágenes */
        img {
            max-width: 100% !important;
            height: auto !important;
            object-fit: contain !important;
            -webkit-print-color-adjust: exact;
            color-adjust: exact;
            print-color-adjust: exact;
        }
        
        /* Estilos para imágenes en el header */
        .header-table-container img {
            max-width: 150px !important;
            max-height: 80px !important;
            height: auto !important;
            width: auto !important;
            object-fit: contain !important;
            display: block !important;
        }
        """

    def _debug_form_design(self, form_design: List[Any]) -> None:
        """
        Función de debug para revisar la estructura del form_design
        """
        logging.info("=== DEBUG FORM DESIGN ===")
        if not form_design:
            logging.info("Form design is empty or None")
            return
            
        for idx, item in enumerate(form_design):
            logging.info(f"Item {idx}: {type(item)}")
            
            if isinstance(item, dict):
                logging.info(f"  Keys: {list(item.keys())}")
                props = item.get('props', {})
                if props:
                    logging.info(f"  Props keys: {list(props.keys())}")
                    style_config = props.get('styleConfig', {})
                    if style_config:
                        logging.info(f"  StyleConfig keys: {list(style_config.keys())}")
                        if 'logo' in style_config:
                            logo_info = style_config['logo']
                            logging.info(f"  Logo info: {logo_info}")
                        if 'headerTable' in style_config:
                            header_info = style_config['headerTable']
                            logging.info(f"  HeaderTable enabled: {header_info.get('enabled', False)}")
            else:
                # Para objetos
                if hasattr(item, 'props'):
                    logging.info(f"  Has props: {bool(item.props)}")
                    if item.props and hasattr(item.props, 'styleConfig'):
                        logging.info(f"  Has styleConfig: {bool(item.props.styleConfig)}")
        logging.info("=== END DEBUG ===")

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
            approvals = form_data.get('approvals', [])
        else:
            # Si es un objeto FormData, acceder por atributos
            response_id = form_data.response_id
            form_info = form_data.form
            submitted_at = form_data.submitted_at if form_data.submitted_at else 'N/A'
            approval_status = form_data.approval_status
            form_message = form_data.message
            answers = form_data.answers
            approvals = form_data.approvals if hasattr(form_data, 'approvals') else []
        
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

            # Debug del form_design
            self._debug_form_design(form_design)

            # Extraer la configuración del encabezado y el logo
            header_table_config = {}
            logo_url = None
            
            logging.info(f"Form design items count: {len(form_design) if form_design else 0}")
            
            if form_design:
                for idx, item in enumerate(form_design):
                    logging.info(f"Processing form design item {idx}: {type(item)}")
                    
                    if isinstance(item, dict):
                        props = item.get('props', {})
                        style_config = props.get('styleConfig', {}) if props else {}
                    else:
                        props = item.props
                        style_config = props.styleConfig if props and props.styleConfig else {}
                    
                    if style_config:
                        logging.info(f"Style config found in item {idx}")
                        
                        if isinstance(style_config, dict):
                            # Buscar logo en la configuración
                            logo_config = style_config.get('logo', {})
                            if logo_config:
                                potential_logo_url = logo_config.get('url') or logo_config.get('src') or logo_config.get('path')
                                if potential_logo_url:
                                    logo_url = str(potential_logo_url)
                                    logging.info(f"✅ Logo URL found: {logo_url}")
                                else:
                                    logging.info(f"Logo config found but no URL/src/path: {logo_config.keys()}")
                            
                            # Buscar header table
                            header_table = style_config.get('headerTable', {})
                            if header_table and header_table.get('enabled'):
                                header_table_config = header_table
                                logging.info(f"✅ Header table config found and enabled")
                                
                                # Debug: revisar si las celdas contienen [LOGO]
                                cells = header_table.get('cells', [])
                                for row_idx, row in enumerate(cells):
                                    for col_idx, cell in enumerate(row):
                                        cell_content = cell.get('content', '')
                                        if '[LOGO]' in cell_content:
                                            logging.info(f"✅ [LOGO] placeholder found in cell [{row_idx}][{col_idx}]: {cell_content}")
                        else:
                            # Manejo para objetos (no diccionarios)
                            if hasattr(style_config, 'logo') and style_config.logo:
                                if hasattr(style_config.logo, 'url') and style_config.logo.url:
                                    logo_url = str(style_config.logo.url)
                                    logging.info(f"✅ Logo URL found (object): {logo_url}")
                            
                            if hasattr(style_config, 'headerTable') and style_config.headerTable and style_config.headerTable.enabled:
                                header_table_config = style_config.headerTable.dict()
                                logging.info(f"✅ Header table config found (object)")
                        
                        # Si encontramos configuración, no necesitamos seguir buscando
                        if header_table_config or logo_url:
                            break
            
            logging.info(f"Final logo URL: {logo_url}")
            logging.info(f"Header table enabled: {bool(header_table_config.get('enabled'))}")

            # Generar el HTML del encabezado
            header_html = self._generate_header_html(header_table_config, logo_url)
            logging.info(f"Generated header HTML (first 200 chars): {header_html[:200]}...")

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

            # Procesar aprobaciones
            processed_approvals = []
            for approval in approvals:
                if isinstance(approval, dict):
                    user_info = approval.get('user', {})
                    processed_approvals.append({
                        'approval_id': approval.get('approval_id'),
                        'sequence_number': approval.get('sequence_number'),
                        'is_mandatory': approval.get('is_mandatory', False),
                        'reconsideration_requested': approval.get('reconsideration_requested', False),
                        'status': approval.get('status', ''),
                        'reviewed_at': approval.get('reviewed_at', 'N/A'),
                        'message': approval.get('message', ''),
                        'user': {
                            'name': user_info.get('name', ''),
                            'email': user_info.get('email', ''),
                            'nickname': user_info.get('nickname', ''),
                            'num_document': user_info.get('num_document', ''),
                        }
                    })
                else:
                    # Si es un objeto, acceder por atributos
                    processed_approvals.append({
                        'approval_id': approval.approval_id if hasattr(approval, 'approval_id') else approval.id,
                        'sequence_number': approval.sequence_number,
                        'is_mandatory': approval.is_mandatory,
                        'reconsideration_requested': approval.reconsideration_requested,
                        'status': approval.status,
                        'reviewed_at': approval.reviewed_at if approval.reviewed_at else 'N/A',
                        'message': approval.message if approval.message else '',
                        'user': {
                            'name': approval.user.name if approval.user else '',
                            'email': approval.user.email if approval.user else '',
                            'nickname': approval.user.nickname if approval.user else '',
                            'num_document': approval.user.num_document if approval.user else '',
                        }
                    })
            
            # Ordenar aprobaciones por sequence_number
            processed_approvals.sort(key=lambda x: x.get('sequence_number', 0))
            logging.info(f"Processed {len(processed_approvals)} approvals.")

            template_data = {
                'form_title': form_title,
                'form_description': form_description,
                'submitted_at': submitted_at,
                'approval_status': approval_status,
                'form_message': form_message,
                'header_html': header_html,
                'footer_text': footer_text,
                'answers': processed_answers,
                'approvals': processed_approvals,
                'response_id': response_id,
            }
            logging.info(f"Template data prepared.")

            # 3. Renderizar la plantilla con los datos
            html_content = template.render(template_data)
            logging.info(f"HTML content rendered successfully.")
            
            # 4. Generar el PDF usando WeasyPrint con márgenes reducidos
            pdf_buffer = io.BytesIO()
            
            # Crear CSS para márgenes reducidos
            margin_css = CSS(string=self._get_reduced_margin_css())
            
            # Generar PDF con CSS personalizado
            HTML(string=html_content).write_pdf(pdf_buffer, stylesheets=[margin_css])
            pdf_buffer.seek(0)

            pdf_bytes = pdf_buffer.getvalue()
            
            if not pdf_bytes:
                logging.warning("WeasyPrint generated empty PDF bytes.")
            else:
                logging.info(f"PDF generated successfully. Size: {len(pdf_bytes)} bytes.")
            
            return pdf_bytes

        except Exception as e:
            logging.error(f"Error durante la generación del PDF: {e}", exc_info=True)
            if html_content:
                logging.error(f"HTML content before error (first 500 chars): {html_content[:500]}...")
            else:
                logging.error("HTML content was not generated before the error occurred.")
            raise



    def generate_pdf_multi_responses(self, form_data: Dict[str, Any]) -> bytes:
        """
        Genera un documento PDF a partir de múltiples respuestas del formulario.
        MODIFICADO: Incluye generación de códigos QR para detalles de respuesta.
        """
        logging.info(f"Received request to generate PDF for multiple responses.")
        
        form_info = form_data.get('form_info', {})
        responses = form_data.get('responses', [])
        total_responses = form_data.get('total_responses', len(responses))
        
        if not responses:
            logging.error("No responses provided for PDF generation")
            raise ValueError("No responses provided for PDF generation")
        
        logging.info(f"Processing {total_responses} responses for PDF generation")

        html_content = None

        try:
            # 1. Cargar la plantilla Jinja2
            template = self.templates_env.get_template('form_document_multi_with_qr.html')
            logging.info(f"Jinja2 template 'form_document_multi_with_qr.html' loaded.")

            # Preparar datos para la plantilla
            form_title = form_info.get('title', '')
            form_description = form_info.get('description', '')
            form_design = form_info.get('form_design', [])
            form_id = form_data.get('form_id')

            # Debug del form_design
            self._debug_form_design(form_design)

            # Extraer la configuración del encabezado y el logo
            header_table_config = {}
            logo_url = None
            
            logging.info(f"Form design items count: {len(form_design) if form_design else 0}")
            
            if form_design:
                for idx, item in enumerate(form_design):
                    logging.info(f"Processing form design item {idx}: {type(item)}")
                    
                    if isinstance(item, dict):
                        props = item.get('props', {})
                        style_config = props.get('styleConfig', {}) if props else {}
                    else:
                        props = item.props
                        style_config = props.styleConfig if props and props.styleConfig else {}
                    
                    if style_config:
                        logging.info(f"Style config found in item {idx}")
                        
                        if isinstance(style_config, dict):
                            # Buscar logo en la configuración
                            logo_config = style_config.get('logo', {})
                            if logo_config:
                                potential_logo_url = logo_config.get('url') or logo_config.get('src') or logo_config.get('path')
                                if potential_logo_url:
                                    logo_url = str(potential_logo_url)
                                    logging.info(f"✅ Logo URL found: {logo_url}")
                            
                            # Buscar header table
                            header_table = style_config.get('headerTable', {})
                            if header_table and header_table.get('enabled'):
                                header_table_config = header_table
                                logging.info(f"✅ Header table config found and enabled")
                        else:
                            # Manejo para objetos (no diccionarios)
                            if hasattr(style_config, 'logo') and style_config.logo:
                                if hasattr(style_config.logo, 'url') and style_config.logo.url:
                                    logo_url = str(style_config.logo.url)
                                    logging.info(f"✅ Logo URL found (object): {logo_url}")
                            
                            if hasattr(style_config, 'headerTable') and style_config.headerTable and style_config.headerTable.enabled:
                                header_table_config = style_config.headerTable.dict()
                                logging.info(f"✅ Header table config found (object)")
                        
                        # Si encontramos configuración, no necesitamos seguir buscando
                        if header_table_config or logo_url:
                            break
            
            logging.info(f"Final logo URL: {logo_url}")
            logging.info(f"Header table enabled: {bool(header_table_config.get('enabled'))}")

            # Generar el HTML del encabezado
            header_html = self._generate_header_html(header_table_config, logo_url)
            logging.info(f"Generated header HTML (first 200 chars): {header_html[:200]}...")

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

            # ✅ MODIFICADO: Procesar todas las respuestas con QR codes
            processed_responses = []
            for response in responses:
                # Procesar respuestas de cada formulario
                processed_answers = []
                for answer in response.get('answers', []):
                    processed_answers.append({
                        'question_text': answer.get('question_text', ''),
                        'answer_text': answer.get('answer_text', ''),
                        'question_type': answer.get('question_type', ''),
                        'file_path': answer.get('file_path', ''),
                    })

                # Procesar aprobaciones
                processed_approvals = []
                for approval in response.get('approvals', []):
                    user_info = approval.get('user', {})
                    processed_approvals.append({
                        'approval_id': approval.get('approval_id'),
                        'sequence_number': approval.get('sequence_number'),
                        'is_mandatory': approval.get('is_mandatory', False),
                        'reconsideration_requested': approval.get('reconsideration_requested', False),
                        'status': approval.get('status', ''),
                        'reviewed_at': approval.get('reviewed_at', 'N/A'),
                        'message': approval.get('message', ''),
                        'user': {
                            'name': user_info.get('name', ''),
                            'email': user_info.get('email', ''),
                            'num_document': user_info.get('num_document', ''),
                        }
                    })
                
                # Ordenar aprobaciones por sequence_number
                processed_approvals.sort(key=lambda x: x.get('sequence_number', 0))

                # ✅ NUEVO: Determinar si mostrar QR y generar URL
                show_qr = self._should_show_qr_for_response(response)
                qr_code_data = None
                details_url = None
                            
                if show_qr:
                    # Generar URL para el frontend Astro
                    response_id = response.get('response_id')
                    details_url = urljoin(
                        self.base_url, 
                        f"/forms/{form_id}/response/{response_id}/details"  # ← Esta será tu página de Astro
                    )
                    
                    # Generar código QR
                    qr_code_data = self._generate_qr_code(details_url)
                    logging.info(f"✅ QR code generated for response {response_id}: {details_url}")
                

                # Agregar respuesta procesada
                processed_responses.append({
                    'response_id': response.get('response_id'),
                    'repeated_id': response.get('repeated_id'),
                    'submitted_at': response.get('submitted_at', 'N/A'),
                    'approval_status': response.get('approval_status'),
                    'message': response.get('message'),
                    'responded_by': response.get('responded_by', {}),
                    'answers': processed_answers,
                    'approvals': processed_approvals,
                    'show_qr': show_qr,  # ✅ NUEVO
                    'qr_code_data': qr_code_data,  # ✅ NUEVO
                    'details_url': details_url  # ✅ NUEVO
                })

            logging.info(f"Processed {len(processed_responses)} responses with QR codes.")

            # ✅ MODIFICADO: Template data para múltiples respuestas con QR
            template_data = {
                'form_title': form_title,
                'form_description': form_description,
                'header_html': header_html,
                'footer_text': footer_text,
                'responses': processed_responses,  # ✅ TODAS las respuestas con QR
                'total_responses': total_responses,
                'form_id': form_data.get('form_id'),
            }
            logging.info(f"Template data prepared for {len(processed_responses)} responses with QR codes.")

            # 3. Renderizar la plantilla con los datos
            html_content = template.render(template_data)
            logging.info(f"HTML content rendered successfully.")
            
            # 4. Generar el PDF usando WeasyPrint con márgenes reducidos
            pdf_buffer = io.BytesIO()
            
            # Crear CSS para márgenes reducidos
            margin_css = CSS(string=self._get_reduced_margin_css())
            
            # Generar PDF con CSS personalizado
            HTML(string=html_content).write_pdf(pdf_buffer, stylesheets=[margin_css])
            pdf_buffer.seek(0)

            pdf_bytes = pdf_buffer.getvalue()
            
            if not pdf_bytes:
                logging.warning("WeasyPrint generated empty PDF bytes.")
            else:
                logging.info(f"PDF generated successfully. Size: {len(pdf_bytes)} bytes.")
            
            return pdf_bytes

        except Exception as e:
            logging.error(f"Error durante la generación del PDF: {e}", exc_info=True)
            if html_content:
                logging.error(f"HTML content before error (first 500 chars): {html_content[:500]}...")
            else:
                logging.error("HTML content was not generated before the error occurred.")
            raise