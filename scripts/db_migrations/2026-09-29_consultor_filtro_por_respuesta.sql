-- ════════════════════════════════════════════════════════════════════════════
-- Consultores: acotar lo que ven por la respuesta de una pregunta tipo lista
--
-- Hasta ahora un consultor con alcance "formato" veía TODAS las respuestas del
-- formato. Con esto se le puede acotar: "solo las respuestas donde la pregunta
-- X se contestó Y" (p. ej. solo las del proyecto ALFA, o solo las del área de
-- mantenimiento).
--
-- Dos columnas, las dos opcionales: una asignación sin ellas se comporta
-- exactamente como antes.
--
--   filter_question_id → la pregunta que clasifica (ON DELETE SET NULL: si
--                        borran la pregunta, la asignación deja de acotar en
--                        vez de desaparecer o de quedar apuntando al vacío).
--   filter_value       → la respuesta escogida. TEXT y no varchar porque una
--                        opción de lista puede ser larga.
--
-- Solo tiene sentido con los alcances `form` y `form_user`; el backend no deja
-- ponerlas en los otros.
--
-- Aplicada en LOCAL el 29-sep-2026. En producción NO.
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE consultant_assignments
    ADD COLUMN IF NOT EXISTS filter_question_id BIGINT NULL
        REFERENCES questions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS filter_value TEXT NULL;

-- El filtro se resuelve con un EXISTS sobre answers por (question_id,
-- answer_text). Ese índice ya existe: ix_answers_question_answer.

COMMENT ON COLUMN consultant_assignments.filter_question_id IS
    'Pregunta tipo lista que acota lo que ve el consultor. NULL = sin acotar.';
COMMENT ON COLUMN consultant_assignments.filter_value IS
    'Respuesta que debe tener esa pregunta para que el envío sea visible.';
