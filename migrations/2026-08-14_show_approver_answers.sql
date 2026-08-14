-- ═════════════════════════════════════════════════════════════════════════════
-- Que quien diligencia pueda ver lo que respondieron los aprobadores (2026-08-14)
--
-- Por defecto NO lo ve: su respuesta muestra solo lo suyo, y los campos que
-- llenan aprobadores y recibidores ni siquiera le aparecen. Con esta opción
-- activada, al consultar SU respuesta ve también lo que ellos respondieron,
-- marcado con el nombre de quién lo escribió.
--
-- Se configura por formato, en "Administrar aprobadores".
--
-- FALSE por defecto: los formatos que ya existen se comportan igual que antes.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE forms
    ADD COLUMN IF NOT EXISTS show_approver_answers_to_filler BOOLEAN NOT NULL DEFAULT FALSE;
