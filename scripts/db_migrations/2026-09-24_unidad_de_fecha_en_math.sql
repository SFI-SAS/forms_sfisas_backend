-- ─────────────────────────────────────────────────────────────────────────────
-- Unidad del resultado cuando una fórmula resta dos fechas.
--
-- Una fecha menos otra fecha da DÍAS. Para saber una edad había que escribir a
-- mano `floor(({hoy}-{nacimiento}+0.5)/365.25)`, que no es algo que se le pueda
-- pedir a quien arma un formato. Con esta columna la unidad se elige con un
-- botón en el editor de fórmulas y el sistema hace la cuenta.
--
--   'days'   → como siempre: la diferencia en días (7421)
--   'years'  → años cumplidos, que es la edad (20)
--   'months' → meses cumplidos (243)
--
-- Aplicada en LOCAL el 24-09-2026. PENDIENTE en producción.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE relation_operation_math
    ADD COLUMN IF NOT EXISTS date_unit VARCHAR(10) NOT NULL DEFAULT 'days';

-- Las operaciones que ya existen se quedan en días: es lo que devolvían hasta
-- hoy, y cambiarlas por su cuenta alteraría resultados ya guardados.
