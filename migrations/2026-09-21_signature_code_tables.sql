-- 2026-09-21 — firma por CÓDIGO: signature_code_persons + signature_code_events
--
-- Las dos tablas entraron en models.py con los commits de ntorres del 17 al 21 de
-- septiembre (`bf34cbf`..`084256d`) SIN migración. Las migraciones NO autocorren: la
-- instancia que reciba este backend sin correr esto se cae con UndefinedTable en
-- cuanto alguien toque la firma por código — igual que dairo el 2026-09-16 con
-- `response_edit_requests`.
--
-- Idempotente: se puede correr las veces que haga falta.

CREATE TABLE IF NOT EXISTS signature_code_persons (
    id                         BIGSERIAL PRIMARY KEY,
    person_id                  VARCHAR(64)  NOT NULL UNIQUE,
    full_name                  VARCHAR(255) NOT NULL,
    document                   VARCHAR(50)  NOT NULL,
    email                      VARCHAR(255) NOT NULL,
    code_hash                  VARCHAR(255) NOT NULL,
    code_generated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    code_generated_by_user_id  BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    failed_attempts            INTEGER      NOT NULL DEFAULT 0,
    locked_until               TIMESTAMPTZ,
    last_signed_at             TIMESTAMPTZ,
    is_active                  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by_user_id         BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    created_at                 TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_signature_code_persons_document
    ON signature_code_persons (document);
CREATE INDEX IF NOT EXISTS ix_signature_code_persons_email
    ON signature_code_persons (email);

CREATE TABLE IF NOT EXISTS signature_code_events (
    id                      BIGSERIAL PRIMARY KEY,
    person_id               VARCHAR(64) NOT NULL,
    event                   VARCHAR(30) NOT NULL,   -- code_generated | sign_ok | sign_failed | locked
    response_id             BIGINT      REFERENCES responses(id) ON DELETE SET NULL,
    form_design_element_id  VARCHAR(100),
    repeater_row_index      INTEGER,
    acted_by_user_id        BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    client_ip               VARCHAR(64),
    user_agent              TEXT,
    detail                  TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_signature_code_events_person
    ON signature_code_events (person_id, created_at);
CREATE INDEX IF NOT EXISTS ix_signature_code_events_response
    ON signature_code_events (response_id);
