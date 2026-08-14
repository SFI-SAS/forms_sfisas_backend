-- ═════════════════════════════════════════════════════════════════════════════
-- El recibidor cuelga de un aprobador (2026-08-14)
--
-- Un recibidor no está suelto en la cadena: recibe lo que aprobó ALGUIEN en
-- concreto. Por eso se asigna desde la tarjeta de su aprobador ("¿Deseas
-- agregar un recibidor?"), igual que los formatos requeridos.
--
--   #1 NEIDER (aprobador)
--        └─ YESID (recibidor de NEIDER)
--        └─ CRISTIAN (recibidor de NEIDER)
--
-- `receives_from_user_id` guarda de quién recibe. Se apunta al USUARIO y no a
-- la fila de form_approvals porque esa fila se recrea al editar (el bulk-update
-- desactiva la vieja y crea una nueva), y el vínculo se perdería.
--
-- NULL = no cuelga de nadie: los aprobadores siempre, y los recibidores
-- anteriores a este cambio (que quedan al final de la cadena, como estaban).
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE form_approvals
    ADD COLUMN IF NOT EXISTS receives_from_user_id BIGINT NULL
    REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS receives_from_user_id BIGINT NULL
    REFERENCES users(id) ON DELETE SET NULL;

-- Para armar "los recibidores de este aprobador" sin recorrer toda la tabla.
CREATE INDEX IF NOT EXISTS ix_form_approvals_receives_from
    ON form_approvals (form_id, receives_from_user_id)
    WHERE receives_from_user_id IS NOT NULL;
