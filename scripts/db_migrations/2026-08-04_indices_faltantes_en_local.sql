-- Índices que existen en PRODUCCIÓN (forms_sfisas_dev) y faltaban en LOCAL.
--
-- Detectados el 2026-08-04 comparando los dos esquemas. La ausencia no rompía
-- nada, pero hacía que el rendimiento medido en local no fuera representativo:
-- consultas que en prod van por índice, en local iban a escaneo secuencial.
--
-- Se conservan los NOMBRES de producción (idx_*, no ix_*) para que las dos
-- bases queden realmente iguales y la próxima comparación salga limpia.
--
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). En producción ya existen,
-- así que allá este script no hace nada (todos llevan IF NOT EXISTS).

CREATE INDEX IF NOT EXISTS ix_forms_project_id
    ON public.forms USING btree (project_id);

CREATE INDEX IF NOT EXISTS idx_question_requests_form
    ON public.question_requests USING btree (form_id);

CREATE INDEX IF NOT EXISTS idx_question_requests_requester
    ON public.question_requests USING btree (requester_id);

CREATE INDEX IF NOT EXISTS idx_question_requests_status
    ON public.question_requests USING btree (status);

CREATE INDEX IF NOT EXISTS idx_question_request_fields_request
    ON public.question_request_fields USING btree (request_id);

CREATE INDEX IF NOT EXISTS idx_question_request_fields_status
    ON public.question_request_fields USING btree (status);
