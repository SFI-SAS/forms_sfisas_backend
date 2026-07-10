-- Migración: crear tabla uploaded_files
-- Fix: H-BM-002 (IDOR en download-file)
-- Fecha: 2026-05-19
-- Aplicar en: backend móvil + web (BD compartida). Idempotente.
-- Nota: tabla ya usada por SafeMetricsMobileBack; el web la comparte.

CREATE TABLE IF NOT EXISTS uploaded_files (
    uuid              VARCHAR(64) PRIMARY KEY,
    owner_user_id     BIGINT      NOT NULL REFERENCES users(id),
    original_filename VARCHAR(500),
    mime              VARCHAR(120),
    size_bytes        BIGINT,
    uploaded_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_owner
    ON uploaded_files(owner_user_id);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_at
    ON uploaded_files(uploaded_at);
