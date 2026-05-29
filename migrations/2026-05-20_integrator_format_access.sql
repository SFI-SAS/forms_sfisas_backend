-- ============================================================================
-- Migración: integrator_format_access
-- Fecha: 2026-05-20
-- Idempotente.
--
-- Tabla que define qué formatos puede integrar cada usuario vía el endpoint
-- POST /integrations/answers. El admin asigna y revoca acceso por (user, format).
-- Cualquier usuario con al menos una fila aquí es de facto un "integrador" y
-- ve la sección de Integraciones en la UI.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS integrator_format_access (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    format_id    BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    assigned_by  BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_integrator_format UNIQUE (user_id, format_id)
);

CREATE INDEX IF NOT EXISTS ix_integrator_format_access_user_id
    ON integrator_format_access (user_id);

CREATE INDEX IF NOT EXISTS ix_integrator_format_access_format_id
    ON integrator_format_access (format_id);

COMMIT;

-- VERIFICACIÓN:
-- SELECT user_id, format_id, assigned_at FROM integrator_format_access ORDER BY assigned_at DESC LIMIT 10;
