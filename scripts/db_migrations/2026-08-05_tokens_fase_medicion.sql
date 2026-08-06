-- Modelo de tokens — FASE DE MEDICIÓN.
--
-- Esta fase NO BLOQUEA NADA. Solo cuenta y registra, para poder calibrar los
-- precios con datos reales antes de que un cliente los vea. Ver el diseño
-- completo en DISENO_tokens_licenciamiento.md (raíz de SAFEMETRICS).
--
-- Recordatorio del modelo: los tokens son CAPACIDAD OCUPADA, no consumo.
-- Lo que existe ocupa; lo que se borra libera.
--
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). Producción requiere
-- autorización explícita.

-- ── Saldo de la instalación ──────────────────────────────────────────────────
-- Una sola fila (id = 1). Cada cliente instala SafeMetrics en su propio hosting
-- y tiene su propio saldo.
--
-- En la fase de medición `tokens_totales` es solo informativo: sirve para
-- mostrar "te quedan X", pero nadie se queda sin poder trabajar.
--
-- MÁS ADELANTE este valor no se editará a mano: llegará en una licencia FIRMADA
-- por la landing. Firmada, no encriptada — el cliente hospeda el sistema, así
-- que cualquier clave de descifrado estaría en su servidor. Con firma puede
-- leer su saldo pero no fabricar uno nuevo.
CREATE TABLE IF NOT EXISTS token_account (
    id                  SMALLINT PRIMARY KEY DEFAULT 1,
    tokens_totales      BIGINT      NOT NULL DEFAULT 0,
    -- Datos de la licencia (se llenan cuando exista el flujo de la landing)
    licencia_firma      TEXT,
    licencia_emitida_en TIMESTAMPTZ,
    licencia_expira_en  TIMESTAMPTZ,
    verificado_en       TIMESTAMPTZ,
    -- Interruptor de la fase 2. Mientras esté en FALSE no se bloquea nada.
    bloqueo_activo      BOOLEAN     NOT NULL DEFAULT FALSE,
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT token_account_fila_unica CHECK (id = 1)
);

INSERT INTO token_account (id, tokens_totales)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- ── Registro de altas y bajas de capacidad ───────────────────────────────────
-- Sirve para dos cosas: alimentar la detección de fraude (activar/desactivar
-- repetidamente para no pagar) y poder responderle a un cliente que reclame.
-- Sin este registro no hay forma de justificar un cobro.
CREATE TABLE IF NOT EXISTS token_events (
    id               BIGSERIAL PRIMARY KEY,
    ocurrido_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_user_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    entidad_tipo     VARCHAR(20)  NOT NULL,   -- usuario | formato | movimiento | vinculo
    entidad_id       BIGINT,
    accion           VARCHAR(10)  NOT NULL,   -- ocupa | libera
    tokens           INTEGER      NOT NULL,
    ocupado_despues  BIGINT,                  -- foto del ocupado tras el evento
    origen           VARCHAR(20),             -- ui | api | importacion | migracion
    detalle          TEXT,
    CONSTRAINT token_events_accion_valida
        CHECK (accion IN ('ocupa','libera')),
    CONSTRAINT token_events_entidad_valida
        CHECK (entidad_tipo IN ('usuario','formato','movimiento','vinculo'))
);

CREATE INDEX IF NOT EXISTS idx_token_events_ocurrido
    ON token_events (ocurrido_en DESC);
CREATE INDEX IF NOT EXISTS idx_token_events_entidad
    ON token_events (entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_token_events_actor
    ON token_events (actor_user_id);
