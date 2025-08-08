import csv
from enum import Enum
from io import BytesIO
import io
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
import pandas as pd
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, func
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
from docx import Document
from app.core.security import get_current_user
from app.database import get_db
from app.models import Answer, Form, FormAnswer, FormApproval, FormApprovalNotification, FormCloseConfig, FormModerators, FormQuestion, FormSchedule, Question, QuestionFilterCondition, QuestionLocationRelation, QuestionTableRelation, QuestionType, Response, ResponseApproval, User
from app.schemas import DownloadRequest,FilterCondition

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4

router = APIRouter()


# Schemas de respuesta
class UserInfo(BaseModel):
    id: int
    name: str
    email: str
    user_type: str
    nickname: Optional[str] = None
    category_name: Optional[str] = None

class QuestionOptionInfo(BaseModel):
    id: int
    option_text: str

class QuestionInfo(BaseModel):
    id: int
    question_text: str
    question_type: str
    required: bool
    root: bool
    category_name: Optional[str] = None
    options: List[QuestionOptionInfo] = []

class AnswerInfo(BaseModel):
    id: int
    question_id: int
    answer_text: Optional[str] = None
    file_path: Optional[str] = None
    file_serial: Optional[str] = None

class ResponseInfo(BaseModel):
    id: int
    user_id: int
    user_name: str
    mode: str
    mode_sequence: int
    repeated_id: Optional[str] = None
    submitted_at: datetime
    answers: List[AnswerInfo] = []

class FormModeratorInfo(BaseModel):
    id: int
    user_id: int
    user_name: str
    assigned_at: datetime

class FormScheduleInfo(BaseModel):
    id: int
    user_id: int
    user_name: str
    frequency_type: str
    repeat_days: Optional[str] = None
    interval_days: Optional[int] = None
    specific_date: Optional[datetime] = None
    status: bool

class FormApprovalInfo(BaseModel):
    id: int
    user_id: int
    user_name: str
    sequence_number: int
    is_mandatory: bool
    deadline_days: Optional[int] = None
    is_active: bool

class ResponseApprovalInfo(BaseModel):
    id: int
    response_id: int
    user_id: int
    user_name: str
    sequence_number: int
    is_mandatory: bool
    status: str
    reviewed_at: Optional[datetime] = None
    message: Optional[str] = None

class FormNotificationInfo(BaseModel):
    id: int
    user_id: int
    user_name: str
    notify_on: str

class FormCloseConfigInfo(BaseModel):
    id: int
    send_download_link: bool
    send_pdf_attachment: bool
    generate_report: bool
    do_nothing: bool
    download_link_recipient: Optional[str] = None
    email_recipient: Optional[str] = None
    report_recipient: Optional[str] = None

class QuestionFilterConditionInfo(BaseModel):
    id: int
    filtered_question_id: int
    source_question_id: int
    condition_question_id: int
    expected_value: str
    operator: str

class QuestionLocationRelationInfo(BaseModel):
    id: int
    origin_question_id: int
    target_question_id: int

class QuestionTableRelationInfo(BaseModel):
    id: int
    question_id: int
    related_question_id: Optional[int] = None
    name_table: str
    field_name: Optional[str] = None

class FormCompleteInfo(BaseModel):
    # Información básica del formulario
    id: int
    title: str
    description: Optional[str] = None
    format_type: str
    created_at: datetime
    # CORREGIDO: Cambié de Dict[str, Any] a List[Dict[str, Any]]
    # form_design: Optional[List[Dict[str, Any]]] = None
    
    # Información del creador
    creator: UserInfo
    
    # Preguntas del formulario
    questions: List[QuestionInfo] = []
    
    # Moderadores
    moderators: List[FormModeratorInfo] = []
    
    # Programación
    schedules: List[FormScheduleInfo] = []
    
    # Configuración de aprobaciones
    approval_templates: List[FormApprovalInfo] = []
    
    # Notificaciones
    notifications: List[FormNotificationInfo] = []
    
    # Configuración de cierre
    close_config: Optional[FormCloseConfigInfo] = None
    
    # Respuestas
    responses: List[ResponseInfo] = []
    
    # Aprobaciones de respuestas
    response_approvals: List[ResponseApprovalInfo] = []
    
    # Condiciones de filtro
    filter_conditions: List[QuestionFilterConditionInfo] = []
    
    # Relaciones de ubicación
    location_relations: List[QuestionLocationRelationInfo] = []
    
    # Relaciones de tabla
    table_relations: List[QuestionTableRelationInfo] = []
    
    # Respuestas del formulario
    form_answers: List[Dict[str, Any]] = []

@router.get("/forms/{form_id}/complete-info", response_model=FormCompleteInfo)
async def get_form_complete_info(form_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    
    """
    Obtiene toda la información relacionada con un formulario específico
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get form"
        )
    # Obtener el formulario con todas sus relaciones
    form = db.query(Form).options(
        # Cargar el usuario creador con su categoría
        joinedload(Form.user).joinedload(User.category),
        
        # Cargar preguntas con sus opciones y categorías
        selectinload(Form.questions).selectinload(Question.options),
        selectinload(Form.questions).selectinload(Question.category),
        
        # Cargar moderadores con información del usuario
        selectinload(Form.form_moderators).selectinload(FormModerators.user),
        
        # Cargar respuestas con usuarios y respuestas
        selectinload(Form.responses).selectinload(Response.user),
        selectinload(Form.responses).selectinload(Response.answers).selectinload(Answer.question),
        selectinload(Form.responses).selectinload(Response.answers).selectinload(Answer.file_serial),
        
        # Cargar form_answers
        selectinload(Form.form_answers).selectinload(FormAnswer.question),
        
    ).filter(Form.id == form_id).first()
    
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    
    # Obtener información adicional relacionada con consultas separadas para obtener usuarios
    schedules = db.query(FormSchedule).filter(FormSchedule.form_id == form_id).all()
    
    # Obtener usuarios para schedules
    schedule_user_ids = [sched.user_id for sched in schedules]
    schedule_users = {}
    if schedule_user_ids:
        users = db.query(User).filter(User.id.in_(schedule_user_ids)).all()
        schedule_users = {user.id: user for user in users}
    
    approval_templates = db.query(FormApproval).filter(FormApproval.form_id == form_id).all()
    
    # Obtener usuarios para approval templates
    approval_user_ids = [approval.user_id for approval in approval_templates]
    approval_users = {}
    if approval_user_ids:
        users = db.query(User).filter(User.id.in_(approval_user_ids)).all()
        approval_users = {user.id: user for user in users}
    
    notifications = db.query(FormApprovalNotification).filter(FormApprovalNotification.form_id == form_id).all()
    
    # Obtener usuarios para notifications
    notification_user_ids = [notif.user_id for notif in notifications]
    notification_users = {}
    if notification_user_ids:
        users = db.query(User).filter(User.id.in_(notification_user_ids)).all()
        notification_users = {user.id: user for user in users}
    
    close_config = db.query(FormCloseConfig).filter(
        FormCloseConfig.form_id == form_id
    ).first()
    
    # Obtener aprobaciones de respuestas
    response_approvals = db.query(ResponseApproval).join(Response).filter(Response.form_id == form_id).all()
    
    # Obtener usuarios para response approvals
    response_approval_user_ids = [approval.user_id for approval in response_approvals]
    response_approval_users = {}
    if response_approval_user_ids:
        users = db.query(User).filter(User.id.in_(response_approval_user_ids)).all()
        response_approval_users = {user.id: user for user in users}
    
    # Obtener condiciones de filtro
    filter_conditions = db.query(QuestionFilterCondition).filter(
        QuestionFilterCondition.form_id == form_id
    ).all()
    
    # Obtener relaciones de ubicación
    location_relations = db.query(QuestionLocationRelation).filter(
        QuestionLocationRelation.form_id == form_id
    ).all()
    
    # Obtener relaciones de tabla para las preguntas del formulario
    question_ids = [q.id for q in form.questions]
    table_relations = db.query(QuestionTableRelation).filter(
        QuestionTableRelation.question_id.in_(question_ids)
    ).all()
    
    # Construir la respuesta
    result = FormCompleteInfo(
        id=form.id,
        title=form.title,
        description=form.description,
        format_type=form.format_type.value,
        created_at=form.created_at,
        
        # Información del creador
        creator=UserInfo(
            id=form.user.id,
            name=form.user.name,
            email=form.user.email,
            user_type=form.user.user_type.value,
            nickname=form.user.nickname,
            category_name=form.user.category.name if form.user.category else None
        ),
        
        # Preguntas
        questions=[
            QuestionInfo(
                id=q.id,
                question_text=q.question_text,
                question_type=q.question_type.value,
                required=q.required,
                root=q.root,
                category_name=q.category.name if q.category else None,
                options=[
                    QuestionOptionInfo(
                        id=opt.id,
                        option_text=opt.option_text
                    ) for opt in q.options
                ]
            ) for q in form.questions
        ],
        
        # Moderadores
        moderators=[
            FormModeratorInfo(
                id=mod.id,
                user_id=mod.user.id,
                user_name=mod.user.name,
                assigned_at=mod.assigned_at
            ) for mod in form.form_moderators
        ],
        
        # Programación
        schedules=[
            FormScheduleInfo(
                id=sched.id,
                user_id=sched.user_id,
                user_name=schedule_users[sched.user_id].name if sched.user_id in schedule_users else "Usuario no encontrado",
                frequency_type=sched.frequency_type,
                repeat_days=sched.repeat_days,
                interval_days=sched.interval_days,
                specific_date=sched.specific_date,
                status=sched.status
            ) for sched in schedules
        ],
        
        # Configuración de aprobaciones
        approval_templates=[
            FormApprovalInfo(
                id=approval.id,
                user_id=approval.user_id,
                user_name=approval_users[approval.user_id].name if approval.user_id in approval_users else "Usuario no encontrado",
                sequence_number=approval.sequence_number,
                is_mandatory=approval.is_mandatory,
                deadline_days=approval.deadline_days,
                is_active=approval.is_active
            ) for approval in approval_templates
        ],
        
        # Notificaciones
        notifications=[
            FormNotificationInfo(
                id=notif.id,
                user_id=notif.user_id,
                user_name=notification_users[notif.user_id].name if notif.user_id in notification_users else "Usuario no encontrado",
                notify_on=notif.notify_on
            ) for notif in notifications
        ],
        
        # Configuración de cierre
        close_config=FormCloseConfigInfo(
            id=close_config.id,
            send_download_link=close_config.send_download_link,
            send_pdf_attachment=close_config.send_pdf_attachment,
            generate_report=close_config.generate_report,
            do_nothing=close_config.do_nothing,
            download_link_recipient=close_config.download_link_recipient,
            email_recipient=close_config.email_recipient,
            report_recipient=close_config.report_recipient
        ) if close_config else None,
        
        # Respuestas
        responses=[
            ResponseInfo(
                id=resp.id,
                user_id=resp.user.id,
                user_name=resp.user.name,
                mode=resp.mode,
                mode_sequence=resp.mode_sequence,
                repeated_id=resp.repeated_id,
                submitted_at=resp.submitted_at,
                answers=[
                    AnswerInfo(
                        id=ans.id,
                        question_id=ans.question.id,
                        answer_text=ans.answer_text,
                        file_path=ans.file_path,
                        file_serial=ans.file_serial.serial if ans.file_serial else None
                    ) for ans in resp.answers
                ]
            ) for resp in form.responses
        ],
        
        # Aprobaciones de respuestas
        response_approvals=[
            ResponseApprovalInfo(
                id=approval.id,
                response_id=approval.response_id,
                user_id=approval.user_id,
                user_name=response_approval_users[approval.user_id].name if approval.user_id in response_approval_users else "Usuario no encontrado",
                sequence_number=approval.sequence_number,
                is_mandatory=approval.is_mandatory,
                status=approval.status.value,
                reviewed_at=approval.reviewed_at,
                message=approval.message
            ) for approval in response_approvals
        ],
        
        # Condiciones de filtro
        filter_conditions=[
            QuestionFilterConditionInfo(
                id=cond.id,
                filtered_question_id=cond.filtered_question_id,
                source_question_id=cond.source_question_id,
                condition_question_id=cond.condition_question_id,
                expected_value=cond.expected_value,
                operator=cond.operator
            ) for cond in filter_conditions
        ],
        
        # Relaciones de ubicación
        location_relations=[
            QuestionLocationRelationInfo(
                id=rel.id,
                origin_question_id=rel.origin_question_id,
                target_question_id=rel.target_question_id
            ) for rel in location_relations
        ],
        
        # Relaciones de tabla
        table_relations=[
            QuestionTableRelationInfo(
                id=rel.id,
                question_id=rel.question_id,
                related_question_id=rel.related_question_id,
                name_table=rel.name_table,
                field_name=rel.field_name
            ) for rel in table_relations
        ],
        
        # Form answers
        form_answers=[
            {
                "id": fa.id,
                "question_id": fa.question.id,
                "question_text": fa.question.question_text,
                "is_repeated": fa.is_repeated
            } for fa in form.form_answers
        ]
    )
    
    return result




@router.get("/forms/available")
async def get_available_forms(db: Session = Depends(get_db)):
    """Obtiene todos los formularios disponibles para descarga"""
    forms = db.query(Form).options(
        joinedload(Form.category),
        joinedload(Form.questions)
    ).all()
    
    return [
        {
            "id": form.id,
            "title": form.title,
            "description": form.description,
            "category": form.category.name if form.category else None,
            "total_responses": len(form.responses),
            "created_at": form.created_at
        }
        for form in forms
    ]
    
@router.get("/forms/{form_id}/fields")
async def get_form_fields(form_id: int, db: Session = Depends(get_db)):
    """Obtiene todos los campos/preguntas de un formulario específico"""
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    
    fields = []
    for question in form.questions:
        field_info = {
            "id": question.id,
            "text": question.question_text,
            "type": question.question_type.value,
            "required": question.required,
            "category": question.category.name if question.category else None
        }
        
        # Si es multiple choice, agregar opciones
        if question.question_type in [QuestionType.multiple_choice, QuestionType.one_choice]:
            field_info["options"] = [
                {"id": opt.id, "text": opt.option_text} 
                for opt in question.options
            ]
        
        fields.append(field_info)
    
    return {
        "form_id": form_id,
        "form_title": form.title,
        "fields": fields,
        "date_range": {
            "min_date": db.query(func.min(Response.submitted_at))
                         .filter(Response.form_id == form_id).scalar(),
            "max_date": db.query(func.max(Response.submitted_at))
                         .filter(Response.form_id == form_id).scalar()
        }
    }
    
@router.post("/download/preview")
async def preview_download_data(
    request: DownloadRequest, 
    db: Session = Depends(get_db)
):
    """Genera una vista previa de los datos que se descargarán"""
    
    # Construir query base
    query = db.query(Response).filter(Response.form_id.in_(request.form_ids))
    
    # Aplicar filtro de fecha si existe
    if request.date_filter:
        if request.date_filter.start_date:
            query = query.filter(Response.submitted_at >= request.date_filter.start_date)
        if request.date_filter.end_date:
            query = query.filter(Response.submitted_at <= request.date_filter.end_date)
    
    # Aplicar condiciones personalizadas
    for condition in request.conditions:
        subquery = db.query(Answer.response_id).filter(
            Answer.question_id == condition.field_id
        )
        
        if condition.operator == "=":
            subquery = subquery.filter(Answer.answer_text == condition.value)
        elif condition.operator == "!=":
            subquery = subquery.filter(Answer.answer_text != condition.value)
        elif condition.operator == "contains":
            subquery = subquery.filter(Answer.answer_text.contains(condition.value))
        # ... más operadores
        
        query = query.filter(Response.id.in_(subquery))
    
    # Obtener respuestas
    responses = query.limit(request.limit).all()
    
    # Formatear datos para preview
    preview_data = []
    for response in responses:
        row = {
            "response_id": response.id,
            "user_id": response.user_id,
            "submitted_at": response.submitted_at,
            "form_title": response.form.title
        }
        
        # Agregar respuestas de campos seleccionados
        for answer in response.answers:
            if answer.question_id in request.selected_fields:
                row[f"question_{answer.question_id}"] = answer.answer_text
        
        preview_data.append(row)
    
    return {
        "total_records": query.count(),
        "preview_records": len(preview_data),
        "data": preview_data,
        "columns": get_column_headers(request.selected_fields, db)
    }

def get_column_headers(field_ids: List[int], db: Session):
    """Obtiene los headers de las columnas"""
    questions = db.query(Question).filter(Question.id.in_(field_ids)).all()
    headers = [
         "Fecha Envío", "Formulario"
    ]
    headers.extend([q.question_text for q in questions])
    return headers


class DownloadFormat(str, Enum):
    excel = "excel"
    csv = "csv"
    pdf = "pdf"
    word = "word"

class FinalDownloadRequest(DownloadRequest):
    format: DownloadFormat

@router.post("/download/generate")
async def generate_download(
    request: FinalDownloadRequest,
    db: Session = Depends(get_db)
):
    """Genera el archivo de descarga en el formato solicitado"""
    
    # Reutilizar la lógica de preview pero sin límite
    data = await get_filtered_data(request, db, limit=None)
    
    if request.format == DownloadFormat.excel:
        return generate_excel_response(data)
    elif request.format == DownloadFormat.csv:
        return generate_csv_response(data)
    elif request.format == DownloadFormat.pdf:
        return generate_pdf_response(data)
    elif request.format == DownloadFormat.word:
        return generate_word_response(data)

async def get_filtered_data(request: FinalDownloadRequest, db: Session, limit: Optional[int] = None):
    """Función auxiliar que obtiene los datos filtrados"""
    # Construir query base
    query = db.query(Response).filter(Response.form_id.in_(request.form_ids))
    
    # Aplicar filtro de fecha si existe
    if request.date_filter:
        if request.date_filter.start_date:
            query = query.filter(Response.submitted_at >= request.date_filter.start_date)
        if request.date_filter.end_date:
            query = query.filter(Response.submitted_at <= request.date_filter.end_date)
    
    # Aplicar condiciones personalizadas
    for condition in request.conditions:
        subquery = db.query(Answer.response_id).filter(
            Answer.question_id == condition.field_id
        )
        
        if condition.operator == "=":
            subquery = subquery.filter(Answer.answer_text == condition.value)
        elif condition.operator == "!=":
            subquery = subquery.filter(Answer.answer_text != condition.value)
        elif condition.operator == "contains":
            subquery = subquery.filter(Answer.answer_text.contains(condition.value))
        elif condition.operator == "starts_with":
            subquery = subquery.filter(Answer.answer_text.startswith(condition.value))
        elif condition.operator == "ends_with":
            subquery = subquery.filter(Answer.answer_text.endswith(condition.value))
        elif condition.operator == ">":
            subquery = subquery.filter(Answer.answer_text > condition.value)
        elif condition.operator == "<":
            subquery = subquery.filter(Answer.answer_text < condition.value)
        elif condition.operator == ">=":
            subquery = subquery.filter(Answer.answer_text >= condition.value)
        elif condition.operator == "<=":
            subquery = subquery.filter(Answer.answer_text <= condition.value)
        
        query = query.filter(Response.id.in_(subquery))
    
    # Aplicar límite si se especifica
    if limit:
        responses = query.limit(limit).all()
    else:
        responses = query.all()
    
    # Obtener preguntas seleccionadas para headers
    questions = db.query(Question).filter(Question.id.in_(request.selected_fields)).all()
    question_dict = {q.id: q.question_text for q in questions}
    
    # Formatear datos
    formatted_data = []
    for response in responses:
        row = {
            "response_id": response.id,
            "user_id": response.user_id,
            "user_name": response.user.name if response.user else "N/A",
            "submitted_at": response.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
            "form_title": response.form.title
        }
        
        # Agregar respuestas de campos seleccionados
        for answer in response.answers:
            if answer.question_id in request.selected_fields:
                column_name = question_dict.get(answer.question_id, f"Pregunta_{answer.question_id}")
                row[column_name] = answer.answer_text or answer.file_path or "Sin respuesta"
        
        formatted_data.append(row)
    
    return {
        "data": formatted_data,
        "total_records": len(formatted_data),
        "columns": list(formatted_data[0].keys()) if formatted_data else []
    }

def generate_excel_response(data: Dict):
    """Genera archivo Excel"""
    output = io.BytesIO()
    
    # Crear DataFrame
    df = pd.DataFrame(data['data'])
    
    # Escribir a Excel con formato
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Datos', index=False)
        
        # Obtener workbook y worksheet para aplicar formato
        workbook = writer.book
        worksheet = writer.sheets['Datos']
        
        # Formato para headers
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#D7E4BC',
            'border': 1
        })
        
        # Aplicar formato a headers
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 20)  # Ancho de columna
        
        # Agregar filtros automáticos
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=datos_formularios.xlsx"}
    )

def generate_csv_response(data: Dict):
    """Genera archivo CSV"""
    output = io.StringIO()
    df = pd.DataFrame(data['data'])
    df.to_csv(output, index=False, encoding='utf-8', sep=',')
    
    content = output.getvalue().encode('utf-8')
    
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=datos_formularios.csv"}
    )

def generate_pdf_response(data: Dict):
    """Genera archivo PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    
    output = io.BytesIO()
    
    # Crear documento PDF
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Título
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.darkblue,
        spaceAfter=30
    )
    story.append(Paragraph("Reporte de Datos de Formularios", title_style))
    story.append(Spacer(1, 20))
    
    # Información del reporte
    info_text = f"Fecha de generación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>"
    info_text += f"Total de registros: {data['total_records']}"
    story.append(Paragraph(info_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Preparar datos para la tabla
    if data['data']:
        # Headers
        headers = list(data['data'][0].keys())
        table_data = [headers]
        
        # Datos (limitar a primeras 50 filas para PDF)
        for row in data['data'][:50]:
            table_data.append([str(row.get(header, '')) for header in headers])
        
        # Crear tabla
        table = Table(table_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        
        if len(data['data']) > 50:
            story.append(Spacer(1, 20))
            story.append(Paragraph(f"Nota: Se muestran los primeros 50 registros de {data['total_records']} totales.", styles['Italic']))
    
    # Generar PDF
    doc.build(story)
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=datos_formularios.pdf"}
    )

def generate_word_response(data: Dict):
    """Genera archivo Word"""
    from docx import Document
    from docx.shared import Inches
    from docx.enum.table import WD_TABLE_ALIGNMENT
    
    output = io.BytesIO()
    
    # Crear documento Word
    doc = Document()
    
    # Título
    title = doc.add_heading('Reporte de Datos de Formularios', 0)
    title.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Información del reporte
    info_paragraph = doc.add_paragraph()
    info_paragraph.add_run('Fecha de generación: ').bold = True
    info_paragraph.add_run(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    info_paragraph.add_run('\nTotal de registros: ').bold = True
    info_paragraph.add_run(str(data['total_records']))
    
    # Agregar tabla con datos
    if data['data']:
        doc.add_paragraph()  # Espacio
        
        headers = list(data['data'][0].keys())
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = 'Table Grid'
        
        # Headers
        hdr_cells = table.rows[0].cells
        for i, header in enumerate(headers):
            hdr_cells[i].text = header
            # Hacer el header en negrita
            for paragraph in hdr_cells[i].paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
        
        # Datos (limitar a primeras 100 filas para Word)
        for row_data in data['data'][:100]:
            row_cells = table.add_row().cells
            for i, header in enumerate(headers):
                row_cells[i].text = str(row_data.get(header, ''))
        
        if len(data['data']) > 100:
            doc.add_paragraph()
            note_paragraph = doc.add_paragraph()
            note_paragraph.add_run('Nota: ').bold = True
            note_paragraph.add_run(f'Se muestran los primeros 100 registros de {data["total_records"]} totales.')
    
    # Guardar documento
    doc.save(output)
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=datos_formularios.docx"}
    )