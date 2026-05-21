-- ============================================================================
-- Migración: pregunta regisfacial fuente para aprobaciones por firma facial
-- Fecha: 2026-05-14
-- Idempotente. Aplica encima de firma_facial_aprobaciones_FINAL.sql.
--
-- Cambio: el admin ahora selecciona EXPLÍCITAMENTE de qué pregunta regisfacial
-- vendrán los registros para validar al aprobador (igual que un campo `firm`
-- tiene sourceQuestionId apuntando a una regisfacial).
--
-- Datos persistidos:
--   - form_approvals.firm_source_question_id        — configuración del admin
--   - response_approvals.firm_source_question_id    — heredado al enviar
--
-- Política de backfill:
--   - Aprobadores existentes con firm_mode != 'button' se bajan a 'button',
--     porque no tienen pregunta fuente configurada. El admin debe reconfigurar.
-- ============================================================================

BEGIN;

-- ── 1) Backfill de seguridad ────────────────────────────────────────────
-- Bajamos a 'button' cualquier aprobador con firma facial activa, para no
-- romper el CHECK constraint que añadimos abajo (firm_source_question_id
-- es obligatoria cuando firm_mode != 'button').
UPDATE form_approvals
   SET firm_mode = 'button'
 WHERE firm_mode <> 'button';

UPDATE response_approvals
   SET firm_mode = 'button',
       firm_answer_id = NULL
 WHERE firm_mode <> 'button';

-- ── 2) form_approvals: pregunta regisfacial fuente ──────────────────────
ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS firm_source_question_id BIGINT NULL
        REFERENCES questions(id) ON DELETE SET NULL;

ALTER TABLE form_approvals
    DROP CONSTRAINT IF EXISTS form_approvals_firm_source_required_check;
ALTER TABLE form_approvals
    ADD CONSTRAINT form_approvals_firm_source_required_check
        CHECK (firm_mode = 'button' OR firm_source_question_id IS NOT NULL);

-- ── 3) response_approvals: heredado al enviar respuesta ────────────────
ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS firm_source_question_id BIGINT NULL
        REFERENCES questions(id) ON DELETE SET NULL;

ALTER TABLE response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_source_required_check;
ALTER TABLE response_approvals
    ADD CONSTRAINT response_approvals_firm_source_required_check
        CHECK (firm_mode = 'button' OR firm_source_question_id IS NOT NULL);

-- ── 4) Índice para lookups del flujo de aprobación ─────────────────────
CREATE INDEX IF NOT EXISTS idx_response_approvals_firm_source
    ON response_approvals(firm_source_question_id)
    WHERE firm_source_question_id IS NOT NULL;

COMMIT;

-- ============================================================================
-- VERIFICACIÓN
-- ============================================================================

-- 1) Las nuevas columnas existen:
-- SELECT table_name, column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE column_name = 'firm_source_question_id'
-- ORDER BY table_name;

-- 2) Backfill aplicado (no debe quedar nada distinto de 'button'):
-- SELECT firm_mode, COUNT(*) FROM form_approvals GROUP BY firm_mode;
-- SELECT firm_mode, COUNT(*) FROM response_approvals GROUP BY firm_mode;

-- 3) CHECK constraints activos:
-- SELECT conname, pg_get_constraintdef(oid)
-- FROM pg_constraint
-- WHERE conname LIKE '%firm_source%';

-- 4) FK firm_source_question_id → questions existe:
-- SELECT conname, pg_get_constraintdef(oid)
-- FROM pg_constraint
-- WHERE conrelid IN ('form_approvals'::regclass, 'response_approvals'::regclass)
--   AND pg_get_constraintdef(oid) LIKE '%firm_source_question_id%';


-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS idx_response_approvals_firm_source;
-- ALTER TABLE response_approvals DROP CONSTRAINT IF EXISTS response_approvals_firm_source_required_check;
-- ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_source_question_id;
-- ALTER TABLE form_approvals DROP CONSTRAINT IF EXISTS form_approvals_firm_source_required_check;
-- ALTER TABLE form_approvals DROP COLUMN IF EXISTS firm_source_question_id;
-- COMMIT;
