-- ✅ EJECUTADO EN PRODUCCIÓN (forms_sfisas_dev) el 2026-08-06, con autorización.
-- ⚠️  OPERACIÓN IRREVERSIBLE — ya aplicada. Respaldo con las 1046 filas en
--    _db_backups/prod_question_request_fields_2026-08-06_antes_drop_user_id.sql
--
-- Elimina question_request_fields.user_id, una columna huérfana que:
--   * solo existía en PROD (nunca estuvo en LOCAL),
--   * NO está declarada en app/models.py — el código nunca la conoció,
--   * tenía 0 de 1046 filas con valor,
--   * no participaba en ningún índice.
--
-- Alguien la creó a mano en algún momento. Al borrarla se va también su clave
-- foránea question_request_fields_user_id_fkey.
--
-- Respaldo previo (esquema + las 1046 filas):
--   _db_backups/prod_question_request_fields_2026-08-06_antes_drop_user_id.sql

BEGIN;

ALTER TABLE public.question_request_fields
    DROP COLUMN IF EXISTS user_id;

COMMIT;
