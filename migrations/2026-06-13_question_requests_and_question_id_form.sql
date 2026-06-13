-- ════════════════════════════════════════════════════════════════════
-- Question Requests (solicitudes de preguntas) + questions.id_form
-- ════════════════════════════════════════════════════════════════════
-- Origen: cambios de ntorres (modelos QuestionRequest / QuestionRequestField
-- y columna Question.id_form en app/models.py, router /question-requests).
-- NO traían migración SQL y create_all está DESACTIVADO en prod (main.py).
-- Las BD vivas (andres_safemetrics, forms_sfisas_dev) ya tienen estas
-- estructuras creadas a mano; esta migración las deja como fuente de verdad
-- reproducible para entornos nuevos. Idempotente y segura sobre las BD que
-- ya las tienen (IF NOT EXISTS no altera estructuras existentes).
--
-- Nota: el modelo declara TIMESTAMP(timezone=True); las BD actuales tienen
-- esas columnas como "timestamp without time zone" (drift preexistente que
-- NO se corrige aquí para no tocar datos vivos). Un entorno nuevo creado con
-- esta migración usará TIMESTAMPTZ, que es la intención del modelo.
-- Aplicar manual: las migraciones NO autocorren en prod.
-- ════════════════════════════════════════════════════════════════════

-- ── questions.id_form ────────────────────────────────────────────────
-- Columna nueva en tabla EXISTENTE: create_all jamás la habría agregado;
-- sin ella, toda consulta ORM sobre `questions` falla (columna inexistente).
ALTER TABLE questions ADD COLUMN IF NOT EXISTS id_form BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_questions_id_form'
    ) THEN
        ALTER TABLE questions
            ADD CONSTRAINT fk_questions_id_form
            FOREIGN KEY (id_form) REFERENCES forms(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_questions_id_form ON questions (id_form);

-- ── question_requests ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS question_requests (
    id                  BIGSERIAL PRIMARY KEY,
    requester_id        BIGINT       NOT NULL REFERENCES users(id)               ON DELETE CASCADE,
    form_id             BIGINT       NOT NULL REFERENCES forms(id)               ON DELETE CASCADE,
    question_text       VARCHAR(255) NOT NULL,
    question_type       VARCHAR(50)  NOT NULL DEFAULT 'text',
    description         TEXT,
    required            BOOLEAN      NOT NULL DEFAULT TRUE,
    id_category         BIGINT       REFERENCES question_categories(id)          ON DELETE SET NULL,
    id_alias            BIGINT       REFERENCES alias(id)                         ON DELETE SET NULL,
    requester_message   TEXT,
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_question_id BIGINT       REFERENCES questions(id)                     ON DELETE SET NULL,
    reviewed_by         BIGINT       REFERENCES users(id)                         ON DELETE SET NULL,
    reviewed_at         TIMESTAMPTZ,
    rejection_reason    TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Índices declarados con index=True en el modelo (faltan en las BD vivas).
CREATE INDEX IF NOT EXISTS idx_question_requests_requester ON question_requests (requester_id);
CREATE INDEX IF NOT EXISTS idx_question_requests_form      ON question_requests (form_id);
CREATE INDEX IF NOT EXISTS idx_question_requests_status    ON question_requests (status);

-- ── question_request_fields ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS question_request_fields (
    id                  BIGSERIAL PRIMARY KEY,
    request_id          BIGINT       NOT NULL REFERENCES question_requests(id)    ON DELETE CASCADE,
    question_text       VARCHAR(255) NOT NULL,
    question_type       VARCHAR(50)  NOT NULL DEFAULT 'text',
    description         TEXT,
    required            BOOLEAN      NOT NULL DEFAULT TRUE,
    id_category         BIGINT       REFERENCES question_categories(id)          ON DELETE SET NULL,
    id_alias            BIGINT       REFERENCES alias(id)                         ON DELETE SET NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_question_id BIGINT       REFERENCES questions(id)                     ON DELETE SET NULL,
    reviewed_by         BIGINT       REFERENCES users(id)                         ON DELETE SET NULL,
    reviewed_at         TIMESTAMPTZ,
    rejection_reason    TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_question_request_fields_request ON question_request_fields (request_id);
CREATE INDEX IF NOT EXISTS idx_question_request_fields_status  ON question_request_fields (status);
