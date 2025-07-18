from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

from app.core.security import get_current_user
from app.database import get_db
from app.models import Answer, Form, FormAnswer, FormApproval, FormApprovalNotification, FormCloseConfig, FormModerators, FormQuestion, FormSchedule, Question, QuestionFilterCondition, QuestionLocationRelation, QuestionTableRelation, Response, ResponseApproval, User


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
