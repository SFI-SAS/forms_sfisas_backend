-- ═════════════════════════════════════════════════════════════════════════════
-- Registro externo por enlace (2026-09-14)
--
-- El caso: el ingeniero de obra diligencia "Asistencia diaria" y se va, pero un
-- trabajador se queda. Ese trabajador NO tiene usuario en Safemetrics y nunca lo
-- va a tener. Se le manda un correo con un botón; al tocarlo se abre una página
-- pública que captura la hora del servidor y el GPS del navegador, y eso queda
-- escrito en SU fila del repetidor.
--
-- Dos tablas:
--   form_external_signoff   → la configuración del formato (qué columna tiene el
--                             correo, cuáles reciben hora y ubicación, cuándo se
--                             dispara). Una fila por formato.
--   response_external_tasks → cada solicitud concreta: a quién, de qué fila, con
--                             qué estado. Es también la evidencia de quién
--                             registró qué y desde dónde.
--
-- El dato se escribe como un Answer NORMAL en la respuesta del ingeniero. Así
-- sale gratis en PDF, Excel, "Consultar respuestas", aprobaciones y móvil, sin
-- tocar ninguna de esas cinco superficies. La autoría queda en la tabla de
-- tareas, no en el Answer.
--
-- Aditivo: un formato sin fila en form_external_signoff se comporta exactamente
-- como hoy.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

-- ── Configuración por formato ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS form_external_signoff (
    id                    BIGSERIAL PRIMARY KEY,
    form_id               BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    is_enabled            BOOLEAN NOT NULL DEFAULT TRUE,

    -- Repetidor dueño de las filas. NULL = los campos son sueltos (no están en
    -- un repetidor) y la solicitud aplica a la respuesta entera.
    repeater_id           VARCHAR(100) NULL,

    -- Columna que trae el correo de la persona a la que se le pide el registro.
    email_element_id      VARCHAR(100) NOT NULL,
    -- Columna con su nombre, solo para saludarla en el correo. Opcional.
    name_element_id       VARCHAR(100) NULL,

    -- Columnas que se ESCRIBEN al confirmar.
    time_element_id       VARCHAR(100) NOT NULL,
    location_element_id   VARCHAR(100) NULL,

    -- 'on_demand' → el ingeniero pide el registro fila por fila (default)
    -- 'on_submit' → al enviar la respuesta se le manda a todo el que tenga la
    --               columna de hora vacía
    trigger_mode          VARCHAR(20) NOT NULL DEFAULT 'on_demand',

    -- Vida del enlace. Vencido no escribe nada y hay que volver a pedirlo.
    expires_hours         INTEGER NOT NULL DEFAULT 12,

    -- Texto que encabeza el correo ("OBRA TORRE 5 — registra tu salida").
    email_subject         VARCHAR(255) NULL,
    -- Qué dice el botón de la página pública.
    action_label          VARCHAR(80) NOT NULL DEFAULT 'Registrar mi salida',

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NULL,

    CONSTRAINT uq_form_external_signoff UNIQUE (form_id),
    CONSTRAINT ck_form_external_signoff_trigger
        CHECK (trigger_mode IN ('on_demand', 'on_submit')),
    CONSTRAINT ck_form_external_signoff_expires
        CHECK (expires_hours > 0 AND expires_hours <= 720)
);

-- ── Una solicitud concreta ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS response_external_tasks (
    id                    BIGSERIAL PRIMARY KEY,
    response_id           BIGINT NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    form_id               BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,

    -- Fila del repetidor a la que pertenece. La fila la manda SIEMPRE
    -- repeater_row_index, nunca la posición visual (ver alineación de filas).
    repeater_id           VARCHAR(100) NULL,
    repeater_row_index    INTEGER NULL,

    recipient_email       VARCHAR(255) NOT NULL,
    recipient_name        VARCHAR(255) NULL,

    -- Se congelan al crear la tarea: si alguien reconfigura el formato después,
    -- esta solicitud sigue escribiendo donde se pactó.
    time_element_id       VARCHAR(100) NOT NULL,
    time_question_id      BIGINT NULL REFERENCES questions(id) ON DELETE SET NULL,
    location_element_id   VARCHAR(100) NULL,
    location_question_id  BIGINT NULL REFERENCES questions(id) ON DELETE SET NULL,

    -- 'pending' | 'done' | 'expired' | 'cancelled'
    status                VARCHAR(20) NOT NULL DEFAULT 'pending',

    requested_by_user_id  BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
    requested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at            TIMESTAMPTZ NOT NULL,
    email_sent            BOOLEAN NOT NULL DEFAULT FALSE,

    -- Lo que quedó grabado, duplicado aquí como evidencia. El dato que se ve en
    -- el formato es el Answer; esto es el registro de que lo puso el trabajador.
    confirmed_at          TIMESTAMPTZ NULL,
    confirmed_time        VARCHAR(20) NULL,
    confirmed_location    VARCHAR(100) NULL,
    -- Por qué no hubo coordenadas: 'denied' | 'unavailable' | 'timeout' | 'unsupported'.
    -- La hora se guarda igual: perderla porque el GPS falló sería peor.
    location_error        VARCHAR(30) NULL,

    client_ip             VARCHAR(64) NULL,
    user_agent            TEXT NULL,

    CONSTRAINT ck_response_external_tasks_status
        CHECK (status IN ('pending', 'done', 'expired', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_response_external_tasks_response
    ON response_external_tasks (response_id);
CREATE INDEX IF NOT EXISTS ix_response_external_tasks_status
    ON response_external_tasks (status, expires_at);

-- Una sola solicitud VIVA por (respuesta, fila, campo de hora). Reenviar no
-- crea una segunda: reusa la misma. Las cerradas no chocan, así que se puede
-- volver a pedir después de un vencimiento.
-- COALESCE porque dos NULL nunca chocan en un UNIQUE: sin eso, los formatos
-- sin repetidor (repeater_row_index NULL) admitirían solicitudes duplicadas.
CREATE UNIQUE INDEX IF NOT EXISTS uq_response_external_tasks_pending
    ON response_external_tasks (
        response_id, COALESCE(repeater_row_index, -1), time_element_id
    )
    WHERE status = 'pending';
