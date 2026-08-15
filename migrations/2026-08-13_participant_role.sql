-- ═════════════════════════════════════════════════════════════════════════════
-- Recibidores de formatos (2026-08-13)
--
-- Hasta ahora todo el que estaba en la cadena de un formato era "aprobador".
-- Pero hay gente que no aprueba nada: RECIBE la orden que aprobó otro. Mismo
-- flujo, misma secuencia, mismos campos y filtros de fila — solo cambia el
-- papel que cumple y dónde le aparece el pendiente.
--
--   'approver' → aprobador de siempre (DEFAULT: nada cambia sin configurar)
--   'receiver' → recibidor: no aprueba, recibe
--
-- Se guarda en los dos lados, igual que `firm_mode`:
--   · form_approvals     → la plantilla del formato
--   · response_approvals → congelado al enviar la respuesta, para que cambiar
--                          la plantilla después no reescriba el pasado
--
-- APLICADO EN: forms_sfisas @ localhost
-- APLICADO EN PROD el 2026-08-14, vía 2026-08-14_pendientes_produccion_recibidores.sql
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS participant_role VARCHAR(20) NOT NULL DEFAULT 'approver';

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS participant_role VARCHAR(20) NOT NULL DEFAULT 'approver';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_form_approvals_participant_role') THEN
        ALTER TABLE form_approvals
            ADD CONSTRAINT ck_form_approvals_participant_role
            CHECK (participant_role IN ('approver', 'receiver'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_response_approvals_participant_role') THEN
        ALTER TABLE response_approvals
            ADD CONSTRAINT ck_response_approvals_participant_role
            CHECK (participant_role IN ('approver', 'receiver'));
    END IF;
END $$;

-- Se consulta "mis pendientes como recibidor" filtrando por usuario y papel.
CREATE INDEX IF NOT EXISTS ix_response_approvals_user_role
    ON response_approvals (user_id, participant_role);
