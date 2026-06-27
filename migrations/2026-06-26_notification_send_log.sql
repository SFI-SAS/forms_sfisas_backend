-- ============================================================================
-- Migracion: notification_send_log (log real de correos/notificaciones enviados)
-- Fecha: 2026-06-26
-- Idempotente. Aplicar manual (las migraciones NO autocorren en prod).
--
-- Registra cada envio de correo del sistema: acciones de cierre de formato
-- (PDF, Excel, reporte, plantilla), notificaciones de aprobacion/rechazo,
-- aprobacion final y recordatorios programados.
--
-- Mapea exactamente a app/models_audit.py:
--   class NotificationSendLog (__tablename__='notification_send_log')
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS notification_send_log (
    id                BIGSERIAL PRIMARY KEY,
    form_id           BIGINT REFERENCES forms(id) ON DELETE SET NULL,
    response_id       BIGINT REFERENCES responses(id) ON DELETE SET NULL,
    event_type        VARCHAR(50) NOT NULL,
    -- Valores esperados:
    --   close_download_link, close_pdf, close_report, close_custom_template,
    --   approval_notification, rejection_notice, final_approval_notice,
    --   scheduled_reminder
    recipient_email   VARCHAR(255) NOT NULL,
    recipient_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'sent',   -- sent / failed
    detail            TEXT,
    sent_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indices para consultas frecuentes desde el endpoint audit-trail
CREATE INDEX IF NOT EXISTS idx_notification_send_log_response
    ON notification_send_log (response_id);

CREATE INDEX IF NOT EXISTS idx_notification_send_log_form
    ON notification_send_log (form_id);

CREATE INDEX IF NOT EXISTS idx_notification_send_log_event_type
    ON notification_send_log (event_type);

CREATE INDEX IF NOT EXISTS idx_notification_send_log_sent_at
    ON notification_send_log (sent_at DESC);

COMMIT;

-- VERIFICACION:
-- \d notification_send_log
-- SELECT id, form_id, response_id, event_type, recipient_email, status, sent_at
--   FROM notification_send_log ORDER BY sent_at DESC LIMIT 10;
