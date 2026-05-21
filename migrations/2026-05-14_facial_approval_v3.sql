-- ============================================================================
-- Migración: Firma facial en aprobaciones (v3 — basada en respuestas regisfacial)
-- Fecha: 2026-05-14
--
-- Diseño:
--   - El admin agrega un checkbox "Requerir firma facial" por aprobador.
--   - Al aprobar, el sistema valida contra cualquier respuesta regisfacial
--     del aprobador (consultada vía /responses/answers/regisfacial existente).
--   - Como evidencia, se guarda el Answer.id usado para validar la firma.
--
-- Tablas tocadas: form_approvals (1 col), response_approvals (2 cols)
-- No se toca: User, esquema previo.
-- Es 100% retrocompatible: aprobadores existentes quedan con firm_required=false.
-- ============================================================================

BEGIN;

-- 1) form_approvals.firm_required — config del admin
ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS firm_required BOOLEAN NOT NULL DEFAULT FALSE;

-- 2) response_approvals.firm_required — heredado al clonar al enviar respuesta
ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS firm_required BOOLEAN NOT NULL DEFAULT FALSE;

-- 3) response_approvals.firm_answer_id — evidencia: qué Answer regisfacial validó
--    la firma. Nullable porque solo aplica cuando se aprobó facialmente.
--    ON DELETE SET NULL: si se borra el Answer (raro), no rompe la aprobación.
ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS firm_answer_id BIGINT NULL
        REFERENCES answers(id) ON DELETE SET NULL;

-- 4) Índice parcial: solo indexa filas firmadas facialmente (auditoría)
CREATE INDEX IF NOT EXISTS idx_response_approvals_firm_answer
    ON response_approvals(firm_answer_id)
    WHERE firm_answer_id IS NOT NULL;

COMMIT;

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS idx_response_approvals_firm_answer;
-- ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_answer_id;
-- ALTER TABLE response_approvals DROP COLUMN IF EXISTS firm_required;
-- ALTER TABLE form_approvals DROP COLUMN IF EXISTS firm_required;
-- COMMIT;
