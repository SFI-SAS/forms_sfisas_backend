-- ============================================================================
-- Migración consolidada: Firma facial en aprobaciones
-- Fecha: 2026-05-14
-- Idempotente: puedes correrlo aunque ya hayas aplicado parte antes.
--
-- Tres métodos de aprobación por aprobador (form_approvals.firm_mode):
--   - 'button'           → solo botón clásico (default)
--   - 'button_or_facial' → botón o firma facial (aprobador elige al aprobar)
--   - 'facial'           → solo firma facial (obligatoria)
--
-- Datos persistidos:
--   - form_approvals.firm_mode        — configuración del admin
--   - response_approvals.firm_mode    — heredado al enviar respuesta
--   - response_approvals.firm_answer_id — evidencia (Answer.id regisfacial usado)
--
-- Cómo funciona:
--   1. Admin configura firm_mode al editar/crear aprobadores.
--   2. Al enviar respuesta, firm_mode se clona a response_approvals.
--   3. Al aprobar facialmente, se valida contra el registro regisfacial del
--      aprobador y se guarda el Answer.id en firm_answer_id como evidencia.
-- ============================================================================

BEGIN;

-- ── form_approvals: configuración del admin ─────────────────────────────
ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS firm_mode VARCHAR(20)
        NOT NULL DEFAULT 'button';

ALTER TABLE form_approvals
    DROP CONSTRAINT IF EXISTS form_approvals_firm_mode_check;
ALTER TABLE form_approvals
    ADD CONSTRAINT form_approvals_firm_mode_check
        CHECK (firm_mode IN ('button', 'button_or_facial', 'facial'));

-- ── response_approvals: heredado al enviar respuesta ───────────────────
ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS firm_mode VARCHAR(20)
        NOT NULL DEFAULT 'button';

ALTER TABLE response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_mode_check;
ALTER TABLE response_approvals
    ADD CONSTRAINT response_approvals_firm_mode_check
        CHECK (firm_mode IN ('button', 'button_or_facial', 'facial'));

-- ── response_approvals.firm_answer_id: evidencia de firma facial ───────
-- FK al Answer del registro regisfacial usado al firmar (NULL si no aplica).
-- ON DELETE SET NULL: si se borra el Answer (raro), la aprobación queda
-- registrada pero sin trazabilidad al registro específico.
ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS firm_answer_id BIGINT NULL
        REFERENCES answers(id) ON DELETE SET NULL;

-- ── Índice parcial: localiza solo aprobaciones firmadas facialmente ────
CREATE INDEX IF NOT EXISTS idx_response_approvals_firm_answer
    ON response_approvals(firm_answer_id)
    WHERE firm_answer_id IS NOT NULL;

COMMIT;

-- ============================================================================
-- VERIFICACIÓN (queries para confirmar que todo quedó bien)
-- ============================================================================

-- 1) Las 3 columnas existen con el tipo correcto:
-- SELECT table_name, column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE (table_name = 'form_approvals' AND column_name = 'firm_mode')
--    OR (table_name = 'response_approvals' AND column_name IN ('firm_mode','firm_answer_id'))
-- ORDER BY table_name, column_name;

-- 2) Los CHECK constraints están activos:
-- SELECT conname, pg_get_constraintdef(oid)
-- FROM pg_constraint
-- WHERE conname LIKE '%firm_mode%';

-- 3) Foreign key firm_answer_id → answers existe:
-- SELECT conname, pg_get_constraintdef(oid)
-- FROM pg_constraint
-- WHERE conrelid = 'response_approvals'::regclass
--   AND conname LIKE '%firm_answer%';

-- 4) Índice parcial creado:
-- SELECT indexname, indexdef FROM pg_indexes
-- WHERE indexname = 'idx_response_approvals_firm_answer';

-- 5) Aprobadores existentes recibieron 'button' por default:
-- SELECT firm_mode, COUNT(*) FROM form_approvals GROUP BY firm_mode;


-- ============================================================================
-- ROLLBACK (si necesitas revertir)
-- ============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS idx_response_approvals_firm_answer;
-- ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_answer_id;
-- ALTER TABLE response_approvals DROP CONSTRAINT IF EXISTS response_approvals_firm_mode_check;
-- ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_mode;
-- ALTER TABLE form_approvals DROP CONSTRAINT IF EXISTS form_approvals_firm_mode_check;
-- ALTER TABLE form_approvals DROP COLUMN IF EXISTS firm_mode;
-- COMMIT;
