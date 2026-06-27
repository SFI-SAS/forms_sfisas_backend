"""Modelos de auditoría — tablas nuevas que NO modifican las existentes."""

from sqlalchemy import (
    BigInteger, Column, String, Text, TIMESTAMP, ForeignKey, func,
)
from app.database import Base


class NotificationSendLog(Base):
    """Registro real de cada correo/notificación enviado por el sistema.

    Se inserta desde los puntos de envío en mail.py y crud.py con un
    try/except propio para no afectar el flujo de envío si el log falla.
    """
    __tablename__ = "notification_send_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_id = Column(BigInteger, ForeignKey("forms.id"), nullable=True)
    response_id = Column(BigInteger, ForeignKey("responses.id"), nullable=True)
    event_type = Column(String(50), nullable=False)
    # Valores esperados:
    #   close_download_link, close_pdf, close_report, close_custom_template,
    #   approval_notification, rejection_notice, final_approval_notice,
    #   scheduled_reminder
    recipient_email = Column(String(255), nullable=False)
    recipient_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), nullable=False, default="sent")  # sent / failed
    detail = Column(Text, nullable=True)
    sent_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
