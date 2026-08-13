-- ═════════════════════════════════════════════════════════════════════════════
-- Autoría de la respuesta (2026-08-12)
--
-- Hasta ahora toda answer colgaba de la Response y su autor era, por definición,
-- quien diligenció el formato. Con "campos por aprobador" un aprobador también
-- escribe answers dentro de la MISMA respuesta, así que hace falta saber quién
-- escribió cada dato.
--
-- NULL = lo escribió quien diligenció (Response.user_id). Todas las filas
-- históricas quedan en NULL, que es exactamente lo correcto.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
--
-- OJO: la tabla answers la comparten el backend web y el móvil. La columna es
-- nullable y sin default, así que los INSERT existentes de ambos siguen válidos.
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE answers
    ADD COLUMN IF NOT EXISTS answered_by_user_id BIGINT NULL
    REFERENCES users(id) ON DELETE SET NULL;

-- Se consulta siempre acotado a una respuesta; el índice parcial evita cargar
-- el 99% de filas en NULL (las del diligenciador).
CREATE INDEX IF NOT EXISTS ix_answers_answered_by
    ON answers (response_id, answered_by_user_id)
    WHERE answered_by_user_id IS NOT NULL;
