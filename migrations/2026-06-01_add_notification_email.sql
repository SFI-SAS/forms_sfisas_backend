-- Migración: add_notification_email_to_relation_rules
-- Fecha: 2026-06-01
-- Objetivo: Corregir error ProgrammingError en bulk_create_question_reminder_rules

ALTER TABLE relation_question_rule ADD COLUMN IF NOT EXISTS notification_email VARCHAR(255);

-- Comentario de verificación:
-- SELECT notification_email FROM relation_question_rule LIMIT 1;
