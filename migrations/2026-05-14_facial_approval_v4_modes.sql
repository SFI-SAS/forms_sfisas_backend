-- ============================================================================
-- Migración: firm_required (boolean) → firm_mode (varchar) con 3 valores
-- Fecha: 2026-05-14
--
-- Tres métodos de aprobación:
--   - 'button'           → solo botón (clásico, actual)
--   - 'button_or_facial' → botón o firma facial (aprobador elige)
--   - 'facial'           → solo firma facial (obligatorio)
--
-- Backfill:
--   - firm_required = false → firm_mode = 'button'
--   - firm_required = true  → firm_mode = 'facial' (era el modo "obligatorio")
--
-- firm_answer_id se mantiene (evidencia de auditoría).
-- ============================================================================

BEGIN;

-- ── form_approvals ───────────────────────────────────────────────────────
ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS firm_mode VARCHAR(20)
        NOT NULL DEFAULT 'button';

UPDATE form_approvals
SET firm_mode = CASE
    WHEN firm_required = true THEN 'facial'
    ELSE 'button'
END;

ALTER TABLE form_approvals
    DROP CONSTRAINT IF EXISTS form_approvals_firm_mode_check;
ALTER TABLE form_approvals
    ADD CONSTRAINT form_approvals_firm_mode_check
        CHECK (firm_mode IN ('button', 'button_or_facial', 'facial'));

ALTER TABLE form_approvals DROP COLUMN IF EXISTS firm_required;

-- ── response_approvals ──────────────────────────────────────────────────
ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS firm_mode VARCHAR(20)
        NOT NULL DEFAULT 'button';

UPDATE response_approvals
SET firm_mode = CASE
    WHEN firm_required = true THEN 'facial'
    ELSE 'button'
END;

ALTER TABLE response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_mode_check;
ALTER TABLE response_approvals
    ADD CONSTRAINT response_approvals_firm_mode_check
        CHECK (firm_mode IN ('button', 'button_or_facial', 'facial'));

ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_required;

-- firm_answer_id y su índice quedan como están (auditoría de quien firmó).

COMMIT;

-- ============================================================================
-- ROLLBACK (volver a firm_required boolean)
-- ============================================================================
-- BEGIN;
-- ALTER TABLE response_approvals ADD COLUMN IF NOT EXISTS firm_required BOOLEAN NOT NULL DEFAULT FALSE;
-- UPDATE response_approvals SET firm_required = (firm_mode = 'facial');
-- ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_mode;
-- ALTER TABLE response_approvals DROP CONSTRAINT IF EXISTS response_approvals_firm_mode_check;
-- ALTER TABLE form_approvals ADD COLUMN IF NOT EXISTS firm_required BOOLEAN NOT NULL DEFAULT FALSE;
-- UPDATE form_approvals SET firm_required = (firm_mode = 'facial');
-- ALTER TABLE form_approvals DROP COLUMN IF EXISTS firm_mode;
-- ALTER TABLE form_approvals DROP CONSTRAINT IF EXISTS form_approvals_firm_mode_check;
-- COMMIT;
