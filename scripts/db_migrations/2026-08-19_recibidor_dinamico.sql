-- ─────────────────────────────────────────────────────────────────────────────
-- Recibidor dinámico ("recibidor aleatorio")
--
-- Un campo tipo lista del formato puede marcarse como "este campo elige al
-- recibidor". Quien lo llena —normalmente un participante de la cadena, no quien
-- diligencia— escoge una persona, y al enviar SU paso esa persona entra en la
-- cadena como recibidor, justo detrás de él.
--
-- Como el usuario no se conoce al diseñar el formato, hacen falta dos cosas:
--
--   1. Poder guardar la configuración de campos ("qué ve / qué llena / qué no
--      ve") de un participante que todavía no es un usuario concreto. Se
--      identifica por el elemento del diseño que lo define (`dynamic_key`).
--
--   2. Recordar, en la respuesta, que ese recibidor salió de un campo, para
--      poder aplicarle esa configuración cuando se le sirva el formato: por
--      user_id no la encontraría, porque no tiene una suya.
--
-- Cada campo marcado es un participante independiente: un formato puede tener
-- varios saltos, cada uno con su propio campo y su propia configuración.
--
-- ⚠️ APLICAR SOLO EN LOCAL (forms_sfisas @ localhost). PROD no se toca sin
--    autorización explícita.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── 1. form_approval_field_access: config de un participante dinámico ────────

ALTER TABLE form_approval_field_access
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE form_approval_field_access
    ADD COLUMN IF NOT EXISTS dynamic_key VARCHAR(100);

COMMENT ON COLUMN form_approval_field_access.dynamic_key IS
    'Participante dinámico al que pertenece esta config: id del elemento del '
    'form_design marcado como selector de recibidor. NULL = config de un '
    'usuario concreto (user_id).';

-- Exactamente uno de los dos: o es de un usuario, o es de un campo.
ALTER TABLE form_approval_field_access
    DROP CONSTRAINT IF EXISTS ck_form_approval_field_access_owner;
ALTER TABLE form_approval_field_access
    ADD CONSTRAINT ck_form_approval_field_access_owner CHECK (
        (user_id IS NOT NULL AND dynamic_key IS NULL)
        OR (user_id IS NULL AND dynamic_key IS NOT NULL)
    );

-- El UNIQUE (form_id, user_id) ya no sirve: con user_id nulo dejaría pasar
-- duplicados, porque en Postgres dos NULL nunca chocan. Se parte en dos índices
-- únicos parciales, uno por cada clase de dueño.
ALTER TABLE form_approval_field_access
    DROP CONSTRAINT IF EXISTS uq_form_approval_field_access;

CREATE UNIQUE INDEX IF NOT EXISTS uq_form_approval_field_access_user
    ON form_approval_field_access (form_id, user_id)
    WHERE dynamic_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_form_approval_field_access_dynamic
    ON form_approval_field_access (form_id, dynamic_key)
    WHERE dynamic_key IS NOT NULL;

-- ── 2. response_approvals: de qué campo salió este recibidor ─────────────────

ALTER TABLE response_approvals
    ADD COLUMN IF NOT EXISTS dynamic_source_element_id VARCHAR(100);

COMMENT ON COLUMN response_approvals.dynamic_source_element_id IS
    'Si este participante lo eligió alguien en un campo selector, id de ese '
    'elemento del form_design. Sirve para aplicarle la config de campos del '
    'participante dinámico. NULL = participante fijo del formato.';

-- Buscar "¿ya se creó el recibidor de este campo en esta respuesta?" es la
-- consulta que evita duplicarlo si el paso se guarda dos veces.
CREATE INDEX IF NOT EXISTS ix_response_approvals_dynamic_source
    ON response_approvals (response_id, dynamic_source_element_id)
    WHERE dynamic_source_element_id IS NOT NULL;

COMMIT;
