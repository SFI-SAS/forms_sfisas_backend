-- ============================================================================
-- Migración: approval_mode en form_categories
-- Fecha: 2026-05-15
-- Idempotente.
--
-- Permite que cada categoría defina el modo de aprobación de sus formatos:
--   - 'sequential' → flujo jerárquico (default, como siempre).
--   - 'parallel'   → todos los aprobadores actúan sin orden.
--
-- Política de sincronización: cuando un formato hereda los aprobadores de
-- su categoría (sync_form_approvals_from_category), también sobreescribe
-- Form.approval_mode con el valor de la categoría.
-- ============================================================================

BEGIN;

ALTER TABLE form_categories
    ADD COLUMN IF NOT EXISTS approval_mode VARCHAR(20)
        NOT NULL DEFAULT 'sequential';

ALTER TABLE form_categories
    DROP CONSTRAINT IF EXISTS form_categories_approval_mode_check;
ALTER TABLE form_categories
    ADD CONSTRAINT form_categories_approval_mode_check
        CHECK (approval_mode IN ('sequential', 'parallel'));

COMMIT;

-- VERIFICACIÓN:
-- SELECT approval_mode, COUNT(*) FROM form_categories GROUP BY approval_mode;
