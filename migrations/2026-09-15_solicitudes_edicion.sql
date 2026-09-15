-- ═════════════════════════════════════════════════════════════════════════════
-- Solicitudes de edicion de respuesta (2026-09-15)
--
-- Un usuario esta consultando una respuesta suya, ve un error y quiere
-- corregirlo. Hoy no puede: la pantalla solo deja editar en borrador. Con esto
-- le pide permiso al administrador, eligiendo QUE campos necesita tocar, y el
-- administrador aprueba o rechaza desde su bandeja.
--
-- Al aprobar, el permiso es de UN SOLO USO y acotado a los campos pedidos: el
-- usuario entra, corrige eso y al guardar la solicitud pasa a 'used'. No queda
-- una puerta abierta.
--
-- Decision del usuario (15-sep): una respuesta ya APROBADA se puede pedir y
-- CONSERVA su estado de aprobada. Por eso importa mas que nunca el rastro que
-- deja esta tabla: quien pidio que, quien lo autorizo y cuando se uso. Sin eso
-- no habria forma de saber que algo aprobado cambio despues.
--
-- Nota sobre el estado actual del sistema: `_enforce_edit_permission` en
-- responses.py declara que una respuesta aprobada es inmutable, pero NO se
-- llama desde ningun sitio, y /answers/update-answer-text solo valida que
-- quien edita sea el dueno. O sea que hoy el candado es de pantalla, no de
-- servidor. Esta tabla no abre nada que estuviera cerrado: le pone registro.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS response_edit_requests (
    id                BIGSERIAL PRIMARY KEY,
    response_id       BIGINT NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    form_id           BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    -- Quien pide. Es siempre el dueno de la respuesta: pedir permiso para
    -- editar lo ajeno no tiene sentido.
    requester_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 'all'    → pidio la respuesta completa
    -- 'fields' → pidio campos concretos (los de `fields`)
    scope             VARCHAR(10) NOT NULL DEFAULT 'fields',

    -- Campos pedidos, como arreglo JSON:
    --   [{"element_id": "...", "question_id": 12, "label": "Hora de salida"}]
    --
    -- Se guarda la ETIQUETA junto al id a proposito: si el formato cambia
    -- despues, el administrador tiene que poder leer que fue lo que autorizo,
    -- aunque ese campo ya no exista en el diseno.
    fields            TEXT NULL,

    -- Por que lo pide. Es lo que el administrador lee para decidir.
    requester_message TEXT NULL,

    -- 'pending' | 'approved' | 'rejected' | 'used' | 'cancelled'
    --
    -- 'used' existe aparte de 'approved' porque el permiso es de un solo uso:
    -- sin ese estado no habria forma de distinguir un permiso vigente de uno
    -- ya gastado, y el usuario podria editar indefinidamente.
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',

    reviewed_by       BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at       TIMESTAMPTZ NULL,
    review_message    TEXT NULL,

    used_at           TIMESTAMPTZ NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_response_edit_requests_scope
        CHECK (scope IN ('all', 'fields')),
    CONSTRAINT ck_response_edit_requests_status
        CHECK (status IN ('pending', 'approved', 'rejected', 'used', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_response_edit_requests_response
    ON response_edit_requests (response_id);

-- La bandeja del administrador: lo pendiente, lo mas viejo primero.
CREATE INDEX IF NOT EXISTS ix_response_edit_requests_status
    ON response_edit_requests (status, created_at);

CREATE INDEX IF NOT EXISTS ix_response_edit_requests_requester
    ON response_edit_requests (requester_id, status);

-- Una sola solicitud VIVA por respuesta y usuario. Sin esto, pulsar dos veces
-- el boton le deja al administrador dos solicitudes identicas que atender.
-- Las cerradas (rechazada, usada, cancelada) no chocan, asi que se puede
-- volver a pedir despues.
CREATE UNIQUE INDEX IF NOT EXISTS uq_response_edit_requests_viva
    ON response_edit_requests (response_id, requester_id)
    WHERE status IN ('pending', 'approved');
