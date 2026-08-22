-- ═════════════════════════════════════════════════════════════════════════════
-- El creador comparte el MODELO DEL FORMATO con su solicitud de campos
-- 2026-08-22
--
-- Al pedir campos nuevos, el administrador no tenía forma de saber para qué los
-- quieren: veía el texto y el tipo, pero no dónde iban a ir. Ahora el creador
-- puede enviar con la solicitud el diseño del formato en el que está trabajando,
-- para que el administrador lo revise antes de crear los campos.
--
-- Es OPCIONAL y va por invitación del creador: sin `design_shared`, el
-- administrador no ve el diseño. Por eso es una marca en la solicitud y no un
-- permiso general sobre el formato.
--
-- El "borrador" del formato NO necesita columna: es `forms.is_enabled = false`,
-- que ya existe y ya significa que nadie lo puede diligenciar.
--
-- Idempotente y aditivo.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PROD (forms_sfisas_dev): NO aplicado.
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE question_requests
    ADD COLUMN IF NOT EXISTS design_shared BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE question_requests
    ADD COLUMN IF NOT EXISTS design_shared_at TIMESTAMP WITH TIME ZONE NULL;

COMMENT ON COLUMN question_requests.design_shared IS
    'El creador envió el modelo del formato junto con la solicitud, para que el '
    'administrador vea dónde se van a usar los campos. FALSE = no lo envió y el '
    'administrador no puede ver el diseño desde aquí.';

COMMENT ON COLUMN question_requests.design_shared_at IS
    'Cuándo se envió el modelo. NULL si nunca se envió.';
