-- ═════════════════════════════════════════════════════════════════════════════
-- Un recibidor puede colgar de VARIOS aprobadores (2026-08-14)
--
-- Reemplaza `receives_from_user_id` (una sola persona) por una lista: la misma
-- persona puede recibir lo que aprueban dos o más aprobadores, sin duplicarse
-- en la cadena.
--
--   #1 NEIDER (aprobador)  ┐
--   #2 ANA    (aprobadora) ┘→ #3 YESID (recibe de NEIDER y de ANA)
--
-- Al ser UNA sola fila por persona, sigue habiendo una sola configuración de
-- campos y una sola aprobación por respuesta para ella. Su lugar en la cadena
-- es después del ÚLTIMO de sus aprobadores: no puede recibir algo que todavía
-- no han aprobado todos.
--
-- Se guarda como JSON (texto) igual que el resto de listas del proyecto. Los
-- valores que hubiera en la columna anterior se migran a la lista.
--
-- APLICADO EN: forms_sfisas @ localhost
-- APLICADO EN PROD el 2026-08-14, vía 2026-08-14_pendientes_produccion_recibidores.sql
--   En prod nunca existió la columna vieja `receives_from_user_id`, así que allá
--   se creó directamente `receives_from_user_ids` y no hubo nada que migrar.
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS receives_from_user_ids TEXT NULL;

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS receives_from_user_ids TEXT NULL;

-- Migrar lo que ya estuviera configurado con un solo aprobador.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'form_approvals' AND column_name = 'receives_from_user_id'
    ) THEN
        UPDATE form_approvals
           SET receives_from_user_ids = '[' || receives_from_user_id || ']'
         WHERE receives_from_user_id IS NOT NULL
           AND receives_from_user_ids IS NULL;

        UPDATE response_approvals
           SET receives_from_user_ids = '[' || receives_from_user_id || ']'
         WHERE receives_from_user_id IS NOT NULL
           AND receives_from_user_ids IS NULL;
    END IF;
END $$;

DROP INDEX IF EXISTS ix_form_approvals_receives_from;
ALTER TABLE form_approvals DROP COLUMN IF EXISTS receives_from_user_id;
ALTER TABLE response_approvals DROP COLUMN IF EXISTS receives_from_user_id;
