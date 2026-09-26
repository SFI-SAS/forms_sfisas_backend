-- ─────────────────────────────────────────────────────────────────────────────
-- Índices que faltaban en `form_questions`.
--
-- Esa tabla (el vínculo pregunta ↔ formato) no tenía NINGÚN índice más allá de
-- su llave primaria, y se consulta por las dos columnas todo el tiempo:
--
--   · por `question_id`: lo hace el endpoint de correlaciones del autocompletado
--     en cada llamada (`FormQuestion.filter_by(question_id=...)`), que hoy barre
--     la tabla entera;
--   · por `form_id`: al armar el diseño de un formato y al listar sus preguntas.
--
-- La tabla crece con formatos × preguntas, así que el barrido empeora con el
-- tiempo.
--
-- Aplicados en LOCAL el 25-09-2026. En PRODUCCIÓN: usar la versión
-- CONCURRENTLY de abajo, una línea a la vez y fuera de una transacción.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_form_questions_question_id
    ON form_questions (question_id);

CREATE INDEX IF NOT EXISTS ix_form_questions_form_id
    ON form_questions (form_id);

ANALYZE form_questions;

-- ── Para PRODUCCIÓN ──────────────────────────────────────────────────────────
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_form_questions_question_id
--     ON form_questions (question_id);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_form_questions_form_id
--     ON form_questions (form_id);
-- ANALYZE form_questions;
