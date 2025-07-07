# pdf_router.py - Versión corregida
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from typing import List, Dict, Any
import io
import logging
from datetime import datetime
from app.api.controllers.pdf_service import PdfGeneratorService
from app.api.schemas.form_data import FormResponseList
from app.database import get_db
from app.models import Answer, AnswerHistory, Response, ResponseApproval

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

router = APIRouter()

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
    Función para generar un PDF a partir de un form_id.
    
    Args:
        form_id: ID del formulario
        db: Sesión de base de datos
        current_user: Usuario actual (obtenido del token de autenticación)
        request: Objeto Request de FastAPI para acceder al estado de la aplicación
        
    Returns:
        bytes: Contenido del PDF generado
        
    Raises:
        HTTPException: Si no se encuentran respuestas o hay errores en la generación
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
                joinedload(Response.form)  # Agregamos el joinedload para form
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

        # Procesar las respuestas
        form_data_list = []
        for r in responses:
            approval_result = get_response_approval_status(r.approvals)

            # Obtener respuestas actuales (excluyendo las que son previous_answer_ids)
            current_answers = []
            for answer in r.answers:
                # Solo incluir respuestas que no sean previous_answer_ids (es decir, las más recientes)
                if answer.id not in previous_answer_ids:
                    current_answers.append(answer)

            form_response_data = {
                "response_id": r.id,
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
                "answers": [
                    {
                        "id_answer": a.id,
                        "repeated_id": r.repeated_id,
                        "question_id": a.question.id,
                        "question_text": a.question.question_text,
                        "question_type": a.question.question_type,
                        "answer_text": a.answer_text,
                        "file_path": a.file_path
                    }
                    for a in current_answers
                ],
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

        # Tomamos el primer elemento como en el código original
        form_data_single = form_data_list[0]
        
        # ✅ CORRECTO - Usar notación de diccionario
        logging.info(f"Processing form response with ID: {form_data_single['response_id']}")
        
        # Obtener el servicio de PDF
        templates_env = request.app.state.templates_env
        pdf_service = PdfGeneratorService(templates_env=templates_env)
        
        # Generar el PDF
        pdf_bytes = pdf_service.generate_pdf(form_data=form_data_single)
        
        if not pdf_bytes:
            logging.error("PdfGeneratorService returned empty bytes.")
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
