-- ═════════════════════════════════════════════════════════════════════════════
-- LO QUE LE FALTA A PRODUCCIÓN (comparado el 2026-08-14)
--
-- Consolida lo pendiente desde la última puesta al día (2026-08-13). El diff se
-- sacó comparando information_schema/pg_indexes/pg_constraint de
-- forms_sfisas @ localhost (PG18) contra forms_sfisas_dev @ 207.246.75.205 (PG14),
-- no leyendo las migraciones: prod ya tenía aplicado todo lo demás.
--
-- Faltaban SOLO estas 6 columnas, 1 índice, 3 CHECK y 1 default. Ninguna tabla.
--
--   · form_approvals.participant_role / receives_from_user_ids   → recibidores
--   · response_approvals.participant_role / receives_from_user_ids
--   · forms.show_approver_answers_to_filler                      → ver lo de aprobadores
--   · users.is_active
--   · ix_response_approvals_user_role                            → "mis pendientes por recibir"
--   · form_templates.scope: default 'private' + CHECK
--
-- Todo ADITIVO: columnas nuevas con default, un índice y constraints de dominio.
-- No reescribe ni borra datos. Las filas existentes quedan como 'approver' /
-- FALSE / TRUE, que es exactamente el comportamiento que tenían antes.
--
-- Respaldo previo:
--   _db_backups/prod_forms_sfisas_dev_COMPLETO_2026-08-14_antes_recibidores.sql
--
-- Para deshacer (solo si hiciera falta):
--   ALTER TABLE form_templates ALTER COLUMN scope DROP DEFAULT;
--   ALTER TABLE form_templates DROP CONSTRAINT IF EXISTS form_templates_scope_check;
--   ALTER TABLE users DROP COLUMN IF EXISTS is_active;
--   ALTER TABLE forms DROP COLUMN IF EXISTS show_approver_answers_to_filler;
--   DROP INDEX IF EXISTS ix_response_approvals_user_role;
--   ALTER TABLE response_approvals DROP CONSTRAINT IF EXISTS ck_response_approvals_participant_role;
--   ALTER TABLE form_approvals   DROP CONSTRAINT IF EXISTS ck_form_approvals_participant_role;
--   ALTER TABLE response_approvals DROP COLUMN IF EXISTS receives_from_user_ids;
--   ALTER TABLE response_approvals DROP COLUMN IF EXISTS participant_role;
--   ALTER TABLE form_approvals     DROP COLUMN IF EXISTS receives_from_user_ids;
--   ALTER TABLE form_approvals     DROP COLUMN IF EXISTS participant_role;
-- ═════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Recibidores: papel en la cadena ──────────────────────────────────────
-- 'approver' por defecto → sin configurar nada, nada cambia.
ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS participant_role VARCHAR(20) NOT NULL DEFAULT 'approver';

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS participant_role VARCHAR(20) NOT NULL DEFAULT 'approver';

-- De qué aprobadores cuelga un recibidor. JSON como texto, igual que el resto
-- de listas del proyecto (el tipo AutoJSON del backend serializa a texto).
ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS receives_from_user_ids TEXT NULL;

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS receives_from_user_ids TEXT NULL;

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

-- "Mis pendientes por recibir" filtra por usuario y papel.
CREATE INDEX IF NOT EXISTS ix_response_approvals_user_role
    ON response_approvals (user_id, participant_role);

-- ── 2. Que quien diligencia vea lo que respondieron los aprobadores ─────────
-- FALSE por defecto: los formatos que ya existen se comportan igual que antes.
ALTER TABLE forms
    ADD COLUMN IF NOT EXISTS show_approver_answers_to_filler BOOLEAN NOT NULL DEFAULT FALSE;

-- ── 3. Usuario activo/inactivo ──────────────────────────────────────────────
-- TRUE por defecto: los usuarios que ya existen siguen pudiendo entrar.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- ── 4. form_templates.scope: alinear con local ──────────────────────────────
-- La columna y el enum `templatescope` ya existen en prod; faltaba el default
-- (sin él, un INSERT sin scope revienta por NOT NULL) y el CHECK. El CHECK es
-- redundante con el enum, pero se pone para que los dos esquemas queden iguales
-- y las comparaciones futuras no den falsos positivos.
ALTER TABLE form_templates
    ALTER COLUMN scope SET DEFAULT 'private'::templatescope;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_templates_scope_check') THEN
        ALTER TABLE form_templates
            ADD CONSTRAINT form_templates_scope_check
            CHECK (scope::text IN ('private', 'company', 'public'));
    END IF;
END $$;

COMMIT;

-- VERIFICACIÓN:
-- SELECT table_name, column_name FROM information_schema.columns
--  WHERE (table_name='form_approvals'     AND column_name IN ('participant_role','receives_from_user_ids'))
--     OR (table_name='response_approvals' AND column_name IN ('participant_role','receives_from_user_ids'))
--     OR (table_name='forms'              AND column_name='show_approver_answers_to_filler')
--     OR (table_name='users'              AND column_name='is_active')
--  ORDER BY 1,2;
-- SELECT indexname FROM pg_indexes WHERE indexname='ix_response_approvals_user_role';
