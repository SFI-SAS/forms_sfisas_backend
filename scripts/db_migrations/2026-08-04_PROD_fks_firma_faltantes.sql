-- ✅ EJECUTADO EN PRODUCCIÓN (forms_sfisas_dev) el 2026-08-06, con autorización.
--    Respaldo previo: _db_backups/prod_forms_sfisas_dev_ESQUEMA_2026-08-06_antes_fks_firma.sql
--    Las 4 columnas estaban 100% en NULL, así que el cambio fue puramente estructural.
--    Es idempotente: volver a correrlo no hace daño.
--
-- QUÉ ARREGLA
-- El modelo (app/models.py) declara ON DELETE SET NULL en las cuatro claves
-- foráneas de firma facial de las aprobaciones. Producción no las tiene, así
-- que hoy, en prod:
--
--   * borrar una PREGUNTA usada como origen de firma en una aprobación, o
--   * borrar una RESPUESTA (answer) usada como evidencia de firma
--
-- falla con violación de integridad referencial, en vez de dejar el campo en
-- NULL como espera el código. En local sí funciona: de ahí que el bug no se
-- vea al desarrollar.
--
-- RIESGO: bajo. Solo cambia el comportamiento AL BORRAR el registro
-- referenciado; no modifica ni una fila de datos existente. Es reversible
-- volviendo a crear la FK sin la cláusula ON DELETE.
--
-- Comprobar antes cuántas filas hay apuntando a algo, para dimensionar:
--   SELECT count(*) FROM form_approvals      WHERE firm_source_question_id IS NOT NULL;
--   SELECT count(*) FROM category_approvals  WHERE firm_source_question_id IS NOT NULL;
--   SELECT count(*) FROM response_approvals  WHERE firm_source_question_id IS NOT NULL;
--   SELECT count(*) FROM response_approvals  WHERE firm_answer_id IS NOT NULL;

BEGIN;

ALTER TABLE public.form_approvals
    DROP CONSTRAINT IF EXISTS form_approvals_firm_source_question_id_fkey;
ALTER TABLE public.form_approvals
    ADD CONSTRAINT form_approvals_firm_source_question_id_fkey
    FOREIGN KEY (firm_source_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

ALTER TABLE public.category_approvals
    DROP CONSTRAINT IF EXISTS category_approvals_firm_source_question_id_fkey;
ALTER TABLE public.category_approvals
    ADD CONSTRAINT category_approvals_firm_source_question_id_fkey
    FOREIGN KEY (firm_source_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

ALTER TABLE public.response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_source_question_id_fkey;
ALTER TABLE public.response_approvals
    ADD CONSTRAINT response_approvals_firm_source_question_id_fkey
    FOREIGN KEY (firm_source_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

ALTER TABLE public.response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_answer_id_fkey;
ALTER TABLE public.response_approvals
    ADD CONSTRAINT response_approvals_firm_answer_id_fkey
    FOREIGN KEY (firm_answer_id) REFERENCES public.answers(id) ON DELETE SET NULL;

COMMIT;

-- APARTE — columna huérfana:
-- question_request_fields.user_id existe en prod, NO está en el modelo y tiene
-- 0 de 928 filas con valor. Si se confirma que nadie la usa, se limpia con:
--
--   ALTER TABLE public.question_request_fields DROP COLUMN user_id;
--
-- (arrastra su FK question_request_fields_user_id_fkey). No se incluye arriba
-- porque borrar una columna es irreversible sin respaldo.
