-- 2026-09-21 — question_filter_conditions.use_latest_only
--
-- La columna entró en models.py el 2026-09-02 (commit 14175f7) SIN migración, así que
-- toda BD anterior a esa fecha se quedó sin ella. El backend la consulta en
-- `get_related_or_filtered_answers_optimized`, que es lo que alimenta TODO campo
-- "Lista con origen Respuestas":
--
--   GET /questions/question-table-relation/answers/{question_id}
--     → 500  (psycopg2.errors.UndefinedColumn: question_filter_conditions.use_latest_only)
--
-- El front no muestra el error: la lista abre y dice "Sin resultados". Medido en dairo
-- el 2026-09-21 diligenciando F3_BD_MATERIALES (com_MAT_UNIDAD, 329 vínculos mudos).
--
-- ⚠️ OFICIAL (`forms_sfisas`) TAMBIÉN le falta, y tiene 424 vínculos de lista y 87
-- condiciones de filtro. Hoy no se cae porque `api-forms-sfi` corre una imagen del
-- 2026-01-30 que no conoce la columna: el día que se despliegue el main actual sin
-- correr esto, se caen los 424. Correrla ANTES del próximo deploy del backend.
--
-- Idempotente: se puede correr las veces que haga falta.

ALTER TABLE question_filter_conditions
    ADD COLUMN IF NOT EXISTS use_latest_only BOOLEAN NOT NULL DEFAULT FALSE;
