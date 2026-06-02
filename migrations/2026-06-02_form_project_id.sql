-- ============================================================================
-- Migración: form_project_id (asociación formato ↔ proyecto)
-- Fecha: 2026-06-02
-- Idempotente.
--
-- Agrega Form.project_id, usada por el endpoint /projects/by-project/{id} y por
-- la asociación form↔proyecto. La columna existía ad-hoc en andres_safemetrics
-- pero no tenía migración versionada (se reproducía mal en prod/staging).
--
-- Mapea exactamente a app/models.py:
--   project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=True, index=True)
-- ============================================================================

BEGIN;

ALTER TABLE forms
    ADD COLUMN IF NOT EXISTS project_id BIGINT NULL REFERENCES projects(id);

CREATE INDEX IF NOT EXISTS ix_forms_project_id
    ON forms (project_id);

COMMIT;

-- VERIFICACIÓN:
-- SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--  WHERE table_name = 'forms' AND column_name = 'project_id';
-- SELECT conname FROM pg_constraint
--  WHERE conrelid = 'public.forms'::regclass AND contype = 'f' AND conname ILIKE '%project%';
