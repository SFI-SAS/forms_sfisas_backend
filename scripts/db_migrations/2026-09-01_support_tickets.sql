-- ─────────────────────────────────────────────────────────────────────────────
-- Soporte: tickets y mensajes
--
-- `app/models.py` define SupportTicket y SupportMessage desde hace semanas, hay
-- endpoints publicados (/support/tickets, /support/tickets/{id}/messages) y un
-- poller que consulta la bandeja cada 60 s — pero NINGUNA migración creaba las
-- tablas. En dairo eso deja `GET /support/tickets` en 500 y un traceback
-- constante en el log:
--     psycopg2.errors.UndefinedTable: relation "support_messages" does not exist
--
-- Este archivo reproduce el modelo tal cual está en models.py (2026-09-01):
--   - `context` es TEXT, no JSONB: el tipo AutoJSON tiene `impl = Text` y guarda
--     el JSON serializado (igual que forms.form_design, que en BD es `text`).
--   - el enum se llama `support_ticket_status` porque el modelo lo nombra así.
--
-- Idempotente: se puede correr varias veces sin efecto.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'support_ticket_status') THEN
        CREATE TYPE support_ticket_status AS ENUM ('open', 'answered', 'closed');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS support_tickets (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject              VARCHAR(255) NOT NULL,
    status               support_ticket_status NOT NULL DEFAULT 'open',
    context              TEXT,
    assigned_agent_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    agent_last_seen_at   TIMESTAMPTZ,
    whatsapp_notified_at TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id
    ON support_tickets (user_id);
CREATE INDEX IF NOT EXISTS ix_support_tickets_status
    ON support_tickets (status);
CREATE INDEX IF NOT EXISTS ix_support_tickets_last_message_at
    ON support_tickets (last_message_at);

CREATE TABLE IF NOT EXISTS support_messages (
    id             BIGSERIAL PRIMARY KEY,
    ticket_id      BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    sender_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    -- 'user' o 'agent': se guarda aparte del rol del usuario porque un admin
    -- también puede abrir un ticket como usuario.
    sender_role    VARCHAR(10) NOT NULL,
    -- Nombre congelado al escribir, para que el historial siga legible si el
    -- usuario se borra.
    sender_name    VARCHAR(255) NOT NULL,
    body           TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_support_messages_ticket_id
    ON support_messages (ticket_id);
CREATE INDEX IF NOT EXISTS ix_support_messages_ticket_created
    ON support_messages (ticket_id, created_at);

COMMIT;
