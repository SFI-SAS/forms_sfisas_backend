-- ─────────────────────────────────────────────────────────────────────────────
-- Índices que faltaban en `answers` y `responses`.
--
-- Las dos tablas más consultadas del sistema no tenían índice en las columnas
-- por las que SIEMPRE se las filtra. Medido en local con 160.000 answers
-- (producción es bastante más grande, así que la diferencia allá es mayor):
--
--   · answers de UNA respuesta            7,12 ms  ->  0,13 ms   (55x)
--     La consulta más frecuente del sistema: consultar, PDF, Excel, aprobar,
--     movimientos, correlaciones de autocompletado.
--
--   · answers de una pregunta con un valor  30,9 ms  ->  1,1 ms   (28x)
--     Es la de `related-last-answer`, que corre UNA VEZ POR CAMPO dependiente
--     cada vez que alguien elige un valor en un campo con "Respuestas
--     relacionadas". De aquí venía la lentitud del autocompletado.
--
-- El índice compuesto (question_id, answer_text) sirve igual para las consultas
-- que solo filtran por question_id, así que no hace falta uno aparte.
--
-- Aplicados en LOCAL el 25-09-2026. En PRODUCCIÓN: usar la versión
-- CONCURRENTLY de abajo (no bloquea escrituras) y FUERA de una transacción.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_answers_response_id
    ON answers (response_id);

CREATE INDEX IF NOT EXISTS ix_answers_question_answer
    ON answers (question_id, answer_text);

CREATE INDEX IF NOT EXISTS ix_responses_form_id
    ON responses (form_id);

ANALYZE answers;
ANALYZE responses;

-- ── Para PRODUCCIÓN ──────────────────────────────────────────────────────────
-- Cada línea se corre SUELTA (CONCURRENTLY no funciona dentro de una
-- transacción; en pgAdmin hay que ejecutarlas de a una). Tarda más, pero no
-- bloquea a quien esté diligenciando.
--
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_answers_response_id
--     ON answers (response_id);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_answers_question_answer
--     ON answers (question_id, answer_text);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_responses_form_id
--     ON responses (form_id);
-- ANALYZE answers;
-- ANALYZE responses;
