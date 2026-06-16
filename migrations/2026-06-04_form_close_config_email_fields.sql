-- ============================================================================
-- Migración: form_close_config — campos de email personalizado
-- Fecha: 2026-06-04
-- Idempotente.
--
-- La tabla `form_close_configs` existe en andres_safemetrics pero le faltan dos
-- columnas que el modelo SQLAlchemy declara desde hace tiempo. El ORM las incluye
-- en el SELECT al cargar un FormCloseConfig, así que la BD respondía
-- "column does not exist" → HTTP 500 en GET /forms/form_close_config/{id} y en
-- POST /forms/create_form_close_config. Es drift de esquema (modelo actualizado
-- sin migración versionada), mismo patrón que form_project_id.
--
-- Hallado por el harness determinístico de cobertura de tools de ArIA (2026-06-04).
--
-- Mapea exactamente a app/models.py (class FormCloseConfig):
--   custom_email_subject = Column(String(255), nullable=True)
--   custom_email_body    = Column(Text, nullable=True)
-- ============================================================================

BEGIN;

ALTER TABLE form_close_configs
    ADD COLUMN IF NOT EXISTS custom_email_subject VARCHAR(255) NULL;

ALTER TABLE form_close_configs
    ADD COLUMN IF NOT EXISTS custom_email_body TEXT NULL;

COMMIT;

-- VERIFICACIÓN:
-- SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--  WHERE table_name = 'form_close_configs'
--    AND column_name IN ('custom_email_subject', 'custom_email_body');
