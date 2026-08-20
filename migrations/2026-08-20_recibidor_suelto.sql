-- ═════════════════════════════════════════════════════════════════════════════
-- Recibidores SIN aprobador ("recibidor suelto") — 2026-08-20
--
-- Hasta ahora todo recibidor colgaba de un aprobador: se asignaba desde la
-- tarjeta de él y su turno lo mandaba `receives_from_user_ids`. Un formato sin
-- aprobadores no podía tener recibidores.
--
-- El recibidor SUELTO cuelga del DILIGENCIADOR: `receives_from_user_ids` va
-- vacío y lo que decide su turno es esta columna nueva:
--
--   'on_submit'       → le llega apenas se envía la respuesta, en paralelo con
--                       la cadena de aprobación (si es que hay alguna).
--   'after_approvals' → espera a que todos los aprobadores obligatorios
--                       aprueben. DEFAULT: es lo que hacía antes.
--
-- En un formato SIN aprobadores las dos opciones son lo mismo (no hay a quién
-- esperar): le llega al enviarse.
--
-- La columna NO aplica a los recibidores que cuelgan de un aprobador: para esos
-- sigue mandando `receives_from_user_ids`, y esto se ignora.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PROD (forms_sfisas_dev): NO aplicado.
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS receive_timing VARCHAR(20) NOT NULL DEFAULT 'after_approvals';

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS receive_timing VARCHAR(20) NOT NULL DEFAULT 'after_approvals';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_form_approvals_receive_timing'
    ) THEN
        ALTER TABLE form_approvals
            ADD CONSTRAINT ck_form_approvals_receive_timing
            CHECK (receive_timing IN ('on_submit', 'after_approvals'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_response_approvals_receive_timing'
    ) THEN
        ALTER TABLE response_approvals
            ADD CONSTRAINT ck_response_approvals_receive_timing
            CHECK (receive_timing IN ('on_submit', 'after_approvals'));
    END IF;
END $$;
