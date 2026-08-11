-- =============================================================================
-- 2026-08-10 — Alinear TODAS las instancias con el esquema de producción.
--
-- Consolida lo que ntorres aplicó a mano en forms_sfisas_dev (prod) el
-- 2026-08-06 y que NUNCA se aplicó a las demás instancias. Sin esto, el backend
-- mergeado el 2026-08-10 revienta en andres/dairo al tocar RUT, tokens o las
-- operaciones matemáticas con recorte de negativos.
--
-- 100% IDEMPOTENTE y ADITIVO: no borra ni modifica datos. Se puede correr
-- las veces que haga falta y sobre una base ya al día (no hace nada).
--
-- CORRER EN: andres_safemetrics, dairo_safemetrics, daniel_safemetrics,
--            prueba4_safemetrics, prueba5_safemetrics.
--            (forms_sfisas_dev ya lo tiene todo desde el 2026-08-06.)
--
-- OJO: las tablas de RUT (form_rut_configs, rut_submissions) existen en prod
-- pero NINGUNA migración las creaba — ntorres las hizo a mano. El DDL de abajo
-- se derivó del esquema real de prod + app/models.py.
-- =============================================================================

BEGIN;

-- ── 1. Operaciones matemáticas: recorte de negativos ─────────────────────────
ALTER TABLE relation_operation_math
    ADD COLUMN IF NOT EXISTS clamp_negativos BOOLEAN NOT NULL DEFAULT FALSE;

-- ── 2. Autollenado con datos del usuario logueado ────────────────────────────
ALTER TABLE question_table_relations
    ADD COLUMN IF NOT EXISTS logged_user_part VARCHAR(30);

-- ── 3. Tokens — fase de medición (bloqueo_activo=FALSE: sólo mide) ───────────
CREATE TABLE IF NOT EXISTS token_account (
    id                  SMALLINT PRIMARY KEY DEFAULT 1,
    tokens_totales      BIGINT      NOT NULL DEFAULT 0,
    licencia_firma      TEXT,
    licencia_emitida_en TIMESTAMPTZ,
    licencia_expira_en  TIMESTAMPTZ,
    verificado_en       TIMESTAMPTZ,
    bloqueo_activo      BOOLEAN     NOT NULL DEFAULT FALSE,
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT token_account_fila_unica CHECK (id = 1)
);

-- La fila única que el código espera encontrar. Sin ella, /tokens devuelve vacío.
INSERT INTO token_account (id, tokens_totales)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS token_events (
    id               BIGSERIAL PRIMARY KEY,
    ocurrido_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_user_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    entidad_tipo     VARCHAR(20)  NOT NULL,
    entidad_id       BIGINT,
    accion           VARCHAR(10)  NOT NULL,
    tokens           INTEGER      NOT NULL,
    ocupado_despues  BIGINT,
    origen           VARCHAR(20),
    detalle          TEXT,
    CONSTRAINT token_events_accion_valida
        CHECK (accion IN ('ocupa','libera')),
    CONSTRAINT token_events_entidad_valida
        CHECK (entidad_tipo IN ('usuario','formato','movimiento','vinculo'))
);

CREATE INDEX IF NOT EXISTS idx_token_events_ocurrido ON token_events (ocurrido_en DESC);
CREATE INDEX IF NOT EXISTS idx_token_events_entidad  ON token_events (entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_token_events_actor    ON token_events (actor_user_id);

-- ── 4. Índice que el modelo declara (index=True) y faltaba ───────────────────
CREATE INDEX IF NOT EXISTS ix_questions_id_alias ON questions (id_alias);

-- ── 5. Solicitud de RUT por formato ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS form_rut_configs (
    id         BIGSERIAL PRIMARY KEY,
    form_id    BIGINT       NOT NULL UNIQUE REFERENCES forms(id) ON DELETE CASCADE,
    email      VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rut_submissions (
    id                BIGSERIAL PRIMARY KEY,
    form_id           BIGINT       NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    user_id           BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_path         VARCHAR(500) NOT NULL,
    original_filename VARCHAR(500),
    email_sent_to     VARCHAR(255),
    email_sent        BOOLEAN      NOT NULL DEFAULT FALSE,
    submitted_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rut_submissions_form ON rut_submissions (form_id);
CREATE INDEX IF NOT EXISTS idx_rut_submissions_user ON rut_submissions (user_id);

-- ── 6. FKs de firma facial con ON DELETE SET NULL ────────────────────────────
-- El modelo las declara así; sin esto, borrar una pregunta usada como origen de
-- firma (o un answer usado como evidencia) falla por integridad referencial.
ALTER TABLE form_approvals
    DROP CONSTRAINT IF EXISTS form_approvals_firm_source_question_id_fkey;
ALTER TABLE form_approvals
    ADD CONSTRAINT form_approvals_firm_source_question_id_fkey
    FOREIGN KEY (firm_source_question_id) REFERENCES questions(id) ON DELETE SET NULL;

ALTER TABLE category_approvals
    DROP CONSTRAINT IF EXISTS category_approvals_firm_source_question_id_fkey;
ALTER TABLE category_approvals
    ADD CONSTRAINT category_approvals_firm_source_question_id_fkey
    FOREIGN KEY (firm_source_question_id) REFERENCES questions(id) ON DELETE SET NULL;

ALTER TABLE response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_source_question_id_fkey;
ALTER TABLE response_approvals
    ADD CONSTRAINT response_approvals_firm_source_question_id_fkey
    FOREIGN KEY (firm_source_question_id) REFERENCES questions(id) ON DELETE SET NULL;

ALTER TABLE response_approvals
    DROP CONSTRAINT IF EXISTS response_approvals_firm_answer_id_fkey;
ALTER TABLE response_approvals
    ADD CONSTRAINT response_approvals_firm_answer_id_fkey
    FOREIGN KEY (firm_answer_id) REFERENCES answers(id) ON DELETE SET NULL;

COMMIT;

-- =============================================================================
-- VERIFICACIÓN — debe devolver 7 filas, todas con ok=1
-- =============================================================================
--   SELECT 'clamp_negativos' AS item, count(*) AS ok FROM information_schema.columns
--     WHERE table_name='relation_operation_math' AND column_name='clamp_negativos'
--   UNION ALL SELECT 'logged_user_part', count(*) FROM information_schema.columns
--     WHERE table_name='question_table_relations' AND column_name='logged_user_part'
--   UNION ALL SELECT 'token_account',   count(*) FROM information_schema.tables WHERE table_name='token_account'
--   UNION ALL SELECT 'token_account_row', count(*) FROM token_account
--   UNION ALL SELECT 'token_events',    count(*) FROM information_schema.tables WHERE table_name='token_events'
--   UNION ALL SELECT 'form_rut_configs',count(*) FROM information_schema.tables WHERE table_name='form_rut_configs'
--   UNION ALL SELECT 'rut_submissions', count(*) FROM information_schema.tables WHERE table_name='rut_submissions';
--
-- NO INCLUIDO A PROPÓSITO: el DROP de question_request_fields.user_id (columna
-- huérfana que sobrevive en andres/dairo). Es irreversible y es inofensiva:
-- no está en el modelo y está 100% en NULL. Se decide aparte.
