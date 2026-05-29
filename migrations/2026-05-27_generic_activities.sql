-- ============================================================================
-- Migración: Actividades genéricas (generic_activities + generic_activity_forms)
-- Fecha: 2026-05-27
-- ----------------------------------------------------------------------------
-- ⚠️  SOLO PROD. En LOCAL estas tablas las crea `Base.metadata.create_all`
--     automáticamente al arrancar el backend con ENV=development.
--
-- ⚠️  Por la Decisión 5 del CLAUDE.md, NO aplicar en producción sin
--     autorización explícita de Andrés. Aplica Programador A manualmente.
--
-- Idempotente: usa IF NOT EXISTS. Seguro de re-ejecutar.
-- ============================================================================

BEGIN;

-- Tabla cabecera: una actividad genérica (nombre + metadatos).
CREATE TABLE IF NOT EXISTS generic_activities (
    id          BIGSERIAL    PRIMARY KEY,
    name        VARCHAR(150) NOT NULL UNIQUE,
    description TEXT,
    created_by  BIGINT       REFERENCES users(id),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Tabla puente: por cada formato de la actividad, quién lo diligencia.
-- Varios diligenciadores por formato => varias filas con igual (activity_id,
-- form_id) y distinto user_id. profile_id recuerda desde qué perfil se eligió
-- al usuario (ON DELETE SET NULL: si se borra el perfil, la asignación queda).
CREATE TABLE IF NOT EXISTS generic_activity_forms (
    id          BIGSERIAL   PRIMARY KEY,
    activity_id BIGINT      NOT NULL REFERENCES generic_activities(id) ON DELETE CASCADE,
    form_id     BIGINT      NOT NULL REFERENCES forms(id)              ON DELETE CASCADE,
    profile_id  BIGINT               REFERENCES profiles(id)           ON DELETE SET NULL,
    user_id     BIGINT      NOT NULL REFERENCES users(id)              ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_generic_activity_form_user UNIQUE (activity_id, form_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_generic_activity_forms_activity_id ON generic_activity_forms (activity_id);
CREATE INDEX IF NOT EXISTS ix_generic_activity_forms_form_id     ON generic_activity_forms (form_id);
CREATE INDEX IF NOT EXISTS ix_generic_activity_forms_profile_id  ON generic_activity_forms (profile_id);
CREATE INDEX IF NOT EXISTS ix_generic_activity_forms_user_id     ON generic_activity_forms (user_id);

COMMIT;
