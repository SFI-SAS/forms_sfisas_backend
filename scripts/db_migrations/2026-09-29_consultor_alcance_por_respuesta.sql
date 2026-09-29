-- ════════════════════════════════════════════════════════════════════════════
-- Consultores: alcance nuevo "por respuesta"
--
-- "Que este consultor vea todos los formatos donde se respondió PORCE III".
-- No cuelga de un formato ni de un usuario: cuelga del VALOR. Medido en prod,
-- "PORCE III" aparece en 32 respuestas repartidas en 17 formatos distintos.
--
-- El valor se guarda en la columna `filter_value` que ya existe (la del acotado
-- por formato). Varios valores = varias asignaciones: el consultor ve la UNIÓN
-- de sus reglas, así que no hace falta una columna de lista.
--
-- Aplicada en LOCAL el 29-sep-2026. En producción NO.
-- ════════════════════════════════════════════════════════════════════════════

-- 1. El valor nuevo del enum.
--
--    Ojo: en PostgreSQL, un valor de enum recién añadido NO se puede usar en la
--    misma transacción que lo creó. Por eso esto va suelto, sin BEGIN/COMMIT
--    alrededor, y el índice de abajo va aparte.
ALTER TYPE consultantscope ADD VALUE IF NOT EXISTS 'answer';


-- 2. El índice que hace viable el alcance.
--
--    La condición es `lower(trim(answer_text)) = 'porce iii'`, que sin índice
--    obliga a recorrer las 124.601 filas de `answers` en CADA consulta del
--    consultor (medido en prod: 120–200 ms por consulta). Un índice normal
--    sobre `answer_text` no sirve: la función lo invalida. Hace falta uno de
--    expresión, con la MISMA expresión que usa el código.
--
--    CONCURRENTLY para no bloquear la tabla mientras se crea; por eso tampoco
--    puede ir dentro de una transacción.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_answers_valor_normalizado
    ON answers (lower(trim(answer_text)));


COMMENT ON INDEX ix_answers_valor_normalizado IS
    'Alcance "por respuesta" de los consultores: busca el valor normalizado.';
