-- ═════════════════════════════════════════════════════════════════════════════
-- Filtros de pregunta: quedarse solo con la respuesta MÁS RECIENTE por valor
-- 2026-09-02
--
-- Migración que faltaba para el modelo de ntorres: `QuestionFilterCondition`
-- ganó la columna `use_latest_only` (app/models.py) pero no vino con el .sql.
-- Sin esta columna el backend nuevo revienta con UndefinedColumn en cualquier
-- consulta a question_filter_conditions.
--
-- Qué hace: cuando es TRUE, el filtro agrupa por el valor de source_question_id
-- y solo considera la última respuesta de cada grupo. Sirve cuando un mismo
-- valor (ej. un proyecto) tiene varias respuestas con estados distintos y solo
-- importa el estado actual.
--
-- Idempotente y aditivo. El default FALSE conserva el comportamiento de antes.
--
-- APLICADO EN: forms_sfisas_dev (oficial) — ya la tenía antes de este archivo.
-- PENDIENTE: forms_sfisas, dairo_safemetrics, andres/daniel/prueba4/prueba5.
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE question_filter_conditions
    ADD COLUMN IF NOT EXISTS use_latest_only BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN question_filter_conditions.use_latest_only IS
    'TRUE = agrupa por el valor de source_question_id y solo mira la respuesta '
    'más reciente de cada grupo. FALSE (default) = considera todas.';
