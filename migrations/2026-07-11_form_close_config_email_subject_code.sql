-- ============================================================================
-- Migración: form_close_configs — código fijo de asunto de correo
-- Fecha: 2026-07-11
-- Idempotente. SOLO LOCAL (forms_sfisas @ localhost). NO aplicar a prod sin
-- autorización explícita.
--
-- Agrega la columna que respalda el "Código del asunto" configurable en la
-- sección "Personalizar correo" de la configuración de cierre. Es un texto fijo
-- que el admin dueño define al crear/editar el formato y que el backend antepone
-- SIEMPRE al asunto de todo correo del cierre (sobre el asunto personalizado o el
-- por defecto). Quien diligencia no lo ve ni lo modifica.
--
-- Mapea exactamente a app/models.py (class FormCloseConfig):
--   email_subject_code = Column(String(50), nullable=True)
-- ============================================================================

BEGIN;

ALTER TABLE form_close_configs
    ADD COLUMN IF NOT EXISTS email_subject_code VARCHAR(50) NULL;

COMMIT;

-- VERIFICACIÓN:
-- SELECT column_name, data_type, character_maximum_length, is_nullable
--   FROM information_schema.columns
--  WHERE table_name = 'form_close_configs'
--    AND column_name = 'email_subject_code';
