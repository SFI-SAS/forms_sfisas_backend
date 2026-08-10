-- Operaciones matemáticas: opción de convertir a 0 los resultados negativos.
--
-- Configurable por operación desde la pantalla de Operaciones Matemáticas.
-- FALSE (por defecto) = comportamiento de siempre, el negativo se muestra tal cual.
-- TRUE = si la fórmula da menos de cero, se presenta y se guarda como 0.
--
-- Se añade junto a color_rules, sobre la misma tabla compartida.
--
-- ⚠️ APLICAR SOLO EN LOCAL (forms_sfisas @ localhost). PROD no se toca sin
-- autorización.

ALTER TABLE relation_operation_math
    ADD COLUMN IF NOT EXISTS clamp_negativos BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN relation_operation_math.clamp_negativos IS
    'Si es TRUE, un resultado negativo de la operación se convierte en 0.';
