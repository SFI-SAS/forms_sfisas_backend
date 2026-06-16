-- ════════════════════════════════════════════════════════════════════
-- SM-CARGO-01 / SM-CARGO-02 — Habilitar el Cargo 7 (Seguridad) de ArIA
-- Idempotente. Aplicar manual (las migraciones NO autocorren en prod).
-- ════════════════════════════════════════════════════════════════════

-- SM-CARGO-02 · created_at en usuarios (detectar picos de creación de usuarios).
-- Los usuarios existentes quedan con la fecha de esta migración (aceptable; de
-- aquí en adelante es real).
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- SM-CARGO-01 · eventos de autenticación (logins fallidos, accesos, etc.).
CREATE TABLE IF NOT EXISTS auth_events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  VARCHAR(40) NOT NULL,        -- login_failed|login_success|access_denied|unusual_access|overload
    user_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    email       VARCHAR(255),
    ip          VARCHAR(64),
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auth_events_created ON auth_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_events_type    ON auth_events (event_type);
