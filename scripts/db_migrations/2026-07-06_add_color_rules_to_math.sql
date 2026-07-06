-- 2026-07-06 — Reglas de color condicional en campos de fórmula matemática.
-- Agrega la columna color_rules (JSON como TEXT, igual que id_questions vía AutoJSON)
-- a la tabla compartida relation_operation_math.
--
-- ⚠️ APLICAR SOLO EN LOCAL (forms_sfisas @ localhost). PROD no se toca sin autorización.
ALTER TABLE relation_operation_math
    ADD COLUMN IF NOT EXISTS color_rules TEXT;
