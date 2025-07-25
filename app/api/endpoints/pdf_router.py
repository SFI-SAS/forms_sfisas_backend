# pdf_router.py - Versión modificada para mostrar todas las respuestas
import os
import json
import re
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from typing import List, Dict, Any, Optional
import io
import logging
from datetime import datetime
from app.api.controllers.pdf_service import PdfGeneratorService
from app.api.schemas.form_data import FormResponseList
from app.database import get_db
from app.models import Answer, AnswerHistory, Response, ResponseApproval

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

router = APIRouter()

# Funciones de procesamiento de ubicación (sin cambios)
def process_location_answer(answer_text: str, question_type: str) -> str:
    """
    Procesa las respuestas de tipo location para mostrar información legible
    en lugar del JSON crudo.
    """
    if question_type != 'location' or not answer_text:
        return answer_text
    
    try:
        # Intentar parsear como JSON
        location_data = json.loads(answer_text)
        
        if not isinstance(location_data, list):
            return answer_text
        
        # Extraer información relevante
        coordinates = None
        selection = None
        timestamp = None
        
        for item in location_data:
            if isinstance(item, dict):
                if item.get('type') == 'coordinates':
                    coordinates = item.get('value')
                    if not timestamp:
                        timestamp = item.get('timestamp')
                elif item.get('type') == 'selection':
                    selection = item.get('value')
                    if not timestamp:
                        timestamp = item.get('timestamp')
        
        # Construir respuesta legible
        result_parts = []
        
        if selection:
            # Limpiar la selección si contiene coordenadas duplicadas
            clean_selection = re.sub(r'\s*\([^)]*\)\s*$', '', selection).strip()
            result_parts.append(f"Ubicación: {clean_selection}")
        
        if coordinates:
            result_parts.append(f"Coordenadas: {coordinates}")
        
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                formatted_time = dt.strftime('%d/%m/%Y %H:%M:%S')
                result_parts.append(f"Fecha: {formatted_time}")
            except:
                pass
        
        return " | ".join(result_parts) if result_parts else answer_text
        
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # Si no se puede parsear o procesar, devolver el texto original
        return answer_text

# Dependencia para obtener una instancia del servicio de PDF
def get_pdf_generator_service(request: Request) -> PdfGeneratorService:
    templates_env = request.app.state.templates_env
    return PdfGeneratorService(templates_env=templates_env)

def get_response_approval_status(approvals: List[ResponseApproval]) -> Dict[str, Any]:
    if not approvals:
        return {"status": "pending", "message": "Sin aprobaciones"}

    latest_approval = max(approvals, key=lambda x: x.reviewed_at or datetime.min)
    return {
        "status": latest_approval.status.value,
        "message": latest_approval.message or "Sin mensaje"
    }
async def generate_pdf_from_form_id(
    form_id: int,
    db: Session,
    current_user: Any,
    request: Request
) -> bytes:
    """
    Función para generar un PDF a partir de un form_id con procesamiento de ubicación.
    MODIFICADO: Ahora incluye códigos QR para detalles de respuesta.
    """
    logging.info(f"Generating PDF for form_id: {form_id}, user: {current_user.id}")
    
    try:
        # Obtener las respuestas del formulario para el usuario actual
        stmt = (
            select(Response)
            .where(Response.form_id == form_id, Response.user_id == current_user.id)
            .options(
                joinedload(Response.answers).joinedload(Answer.question),
                joinedload(Response.approvals).joinedload(ResponseApproval.user),
                joinedload(Response.form)
            )
        )

        responses = db.execute(stmt).unique().scalars().all()

        if not responses:
            logging.warning(f"No responses found for form_id: {form_id}, user: {current_user.id}")
            raise HTTPException(status_code=404, detail="No se encontraron respuestas")

        # Obtener todos los response_ids para buscar el historial
        response_ids = [response.id for response in responses]
        
        # Obtener historiales de respuestas
        histories = db.query(AnswerHistory).filter(AnswerHistory.response_id.in_(response_ids)).all()
        
        # Obtener todos los IDs de respuestas (previous y current) del historial
        all_answer_ids = set()
        for history in histories:
            if history.previous_answer_id:
                all_answer_ids.add(history.previous_answer_id)
            all_answer_ids.add(history.current_answer_id)
        
        # Obtener todas las respuestas del historial con sus preguntas
        historical_answers = {}
        if all_answer_ids:
            historical_answer_list = (
                db.query(Answer)
                .options(joinedload(Answer.question))
                .filter(Answer.id.in_(all_answer_ids))
                .all()
            )
            
            # Crear mapeo de answer_id -> Answer
            for answer in historical_answer_list:
                historical_answers[answer.id] = answer
        
        # Crear mapeo de current_answer_id -> history
        history_map = {}
        # Crear conjunto de previous_answer_ids para saber cuáles no mostrar individualmente
        previous_answer_ids = set()
        
        for history in histories:
            history_map[history.current_answer_id] = history
            if history.previous_answer_id:
                previous_answer_ids.add(history.previous_answer_id)

        # ✅ MODIFICADO: Procesar TODAS las respuestas en lugar de solo la primera
        form_data_list = []
        for r in responses:
            approval_result = get_response_approval_status(r.approvals)

            # Obtener respuestas actuales (excluyendo las que son previous_answer_ids)
            current_answers = []
            for answer in r.answers:
                # Solo incluir respuestas que no sean previous_answer_ids (es decir, las más recientes)
                if answer.id not in previous_answer_ids:
                    current_answers.append(answer)

            # Procesar respuestas con ubicación
            processed_answers = []
            for a in current_answers:
                answer_data = {
                    "id_answer": a.id,
                    "repeated_id": r.repeated_id,
                    "question_id": a.question.id,
                    "question_text": a.question.question_text,
                    "question_type": a.question.question_type,
                    "answer_text": process_location_answer(a.answer_text, a.question.question_type),
                    "file_path": a.file_path,
                    "original_answer_text": a.answer_text
                }
                processed_answers.append(answer_data)

            form_response_data = {
                "response_id": r.id,
                "repeated_id": r.repeated_id,  # ✅ AGREGADO: repeated_id para diferenciación
                "submitted_at": r.submitted_at,
                "approval_status": approval_result["status"],
                "message": approval_result["message"],
                "form": {
                    "form_id": r.form.id,
                    "title": r.form.title,
                    "description": r.form.description,
                    "format_type": r.form.format_type.value if r.form.format_type else None,
                    "form_design": r.form.form_design
                },
                "answers": processed_answers,
                "approvals": [
                    {
                        "approval_id": ap.id,
                        "sequence_number": ap.sequence_number,
                        "is_mandatory": ap.is_mandatory,
                        "reconsideration_requested": ap.reconsideration_requested,
                        "status": ap.status.value,
                        "reviewed_at": ap.reviewed_at,
                        "message": ap.message,
                        "user": {
                            "id": ap.user.id,
                            "name": ap.user.name,
                            "email": ap.user.email,
                            "nickname": ap.user.nickname,
                            "num_document": ap.user.num_document
                        }
                    }
                    for ap in r.approvals
                ]
            }
            
            form_data_list.append(form_response_data)

        if not form_data_list:
            logging.warning(f"No form data processed for form_id: {form_id}")
            raise HTTPException(status_code=404, detail="No se pudieron procesar los datos del formulario")

        # ✅ MODIFICADO: Pasar TODAS las respuestas en lugar de solo la primera
        # Crear un objeto que contenga todas las respuestas
        form_data_complete = {
            "form_id": form_id,
            "form_info": form_data_list[0]["form"],  # La info del formulario es la misma para todas
            "responses": form_data_list,  # ✅ TODAS las respuestas
            "user_id": current_user.id,
            "total_responses": len(form_data_list)
        }
        
        logging.info(f"Processing {len(form_data_list)} form responses for form_id: {form_id}")
        
        # Configurar la carpeta de uploads para el logo con ruta absoluta
        UPLOAD_FOLDER = "logo"
        ABSOLUTE_UPLOAD_FOLDER = os.path.abspath(UPLOAD_FOLDER)
        
        # Asegurar que la carpeta exista
        os.makedirs(ABSOLUTE_UPLOAD_FOLDER, exist_ok=True)
        
        logging.info(f"Using upload folder for logos: {ABSOLUTE_UPLOAD_FOLDER}")
        
        # Verificar si existe algún logo en la carpeta
        logo_files = []
        if os.path.exists(ABSOLUTE_UPLOAD_FOLDER):
            for file in os.listdir(ABSOLUTE_UPLOAD_FOLDER):
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')):
                    logo_files.append(file)
        
        if logo_files:
            logging.info(f"✅ Found logo files in {ABSOLUTE_UPLOAD_FOLDER}: {logo_files}")
        else:
            logging.warning(f"⚠️ No logo files found in {ABSOLUTE_UPLOAD_FOLDER}")
        
        # ✅ NUEVO: Obtener la URL base desde el request
        base_url = f"{request.url.scheme}://{request.url.netloc}"
        logging.info(f"Using base URL for QR codes: {base_url}")
        
        # Obtener el servicio de PDF con la carpeta de uploads absoluta y URL base
        templates_env = request.app.state.templates_env
        frontend_url = "http://localhost:4321" 
        pdf_service = PdfGeneratorService(
            templates_env=templates_env,
            upload_folder=ABSOLUTE_UPLOAD_FOLDER,
            base_url=frontend_url  # ✅ NUEVO: Pasar URL base
        )
        
        logging.info(f"PDF service initialized with upload folder: {ABSOLUTE_UPLOAD_FOLDER} and base URL: {base_url}")
        
        # ✅ MODIFICADO: Generar el PDF con todas las respuestas y QR codes
        pdf_bytes = pdf_service.generate_pdf_multi_responses(form_data=form_data_complete)
        
        if not pdf_bytes:
            logging.error("PdfGeneratorService returned empty PDF bytes.")
            raise HTTPException(
                status_code=500, 
                detail="La generación del PDF resultó en un archivo vacío. Por favor, revisa los logs del servidor para más detalles."
            )
        
        logging.info(f"PDF bytes generated successfully. Size: {len(pdf_bytes)} bytes.")
        return pdf_bytes

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error inesperado en la generación de PDF: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Error interno del servidor al generar el PDF: {e}. Revisa los logs para más información."
        )