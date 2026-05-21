-- ============================================================================
-- Migración: firma facial en aprobadores por categoría
-- Fecha: 2026-05-15
-- Idempotente. Aplica encima de firma_facial_source_question.sql.
--
-- Mismos 3 métodos que para form_approvals:
--   - 'button'           → solo botón (default)
--   - 'button_or_facial' → botón o firma facial
--   - 'facial'           → firma facial obligatoria
--
-- Cuando un formato hereda los aprobadores de su categoría
-- (sync_form_approvers_with_category), ya se propaga firm_mode y
-- firm_source_question_id al FormApproval clonado.
-- ============================================================================

BEGIN;

-- ── 1) firm_mode ────────────────────────────────────────────────────────
ALTER TABLE category_approvals
    ADD COLUMN IF NOT EXISTS firm_mode VARCHAR(20)
        NOT NULL DEFAULT 'button';

ALTER TABLE category_approvals
    DROP CONSTRAINT IF EXISTS category_approvals_firm_mode_check;
ALTER TABLE category_approvals
    ADD CONSTRAINT category_approvals_firm_mode_check
        CHECK (firm_mode IN ('button', 'button_or_facial', 'facial'));

-- ── 2) firm_source_question_id ─────────────────────────────────────────
ALTER TABLE category_approvals
    ADD COLUMN IF NOT EXISTS firm_source_question_id BIGINT NULL
        REFERENCES questions(id) ON DELETE SET NULL;

ALTER TABLE category_approvals
    DROP CONSTRAINT IF EXISTS category_approvals_firm_source_required_check;
ALTER TABLE category_approvals
    ADD CONSTRAINT category_approvals_firm_source_required_check
        CHECK (firm_mode = 'button' OR firm_source_question_id IS NOT NULL);

-- ── 3) Índice ──────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_category_approvals_firm_source
    ON category_approvals(firm_source_question_id)
    WHERE firm_source_question_id IS NOT NULL;

COMMIT;

-- VERIFICACIÓN:
-- SELECT firm_mode, COUNT(*) FROM category_approvals GROUP BY firm_mode;
-- SELECT conname FROM pg_constraint WHERE conrelid = 'category_approvals'::regclass AND conname LIKE '%firm%';
