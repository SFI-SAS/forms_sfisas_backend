-- Versiones obsoletas de un formato (modelos FormVersion / FormVersionQuestion).
--
-- Al aprobar el administrador un borrador de versión, el formato vigente
-- conserva su id y toma lo nuevo; lo que tenía antes se congela aquí y queda
-- como OBSOLETO: se consulta (Consultar → Obsoletos, Editar formato →
-- Versiones anteriores) pero no se diligencia ni se edita.
-- Idempotente.
BEGIN;

CREATE TABLE IF NOT EXISTS form_versions (
    id BIGSERIAL PRIMARY KEY,
    form_id BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    title VARCHAR(255),
    description TEXT,
    format_type VARCHAR(30),
    approval_mode VARCHAR(20),
    form_design TEXT,
    participants TEXT,
    moderators TEXT,
    close_config TEXT,
    change_note VARCHAR(500),
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ NOT NULL,
    published_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    archived_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    replaced_by_version INTEGER,
    CONSTRAINT uq_form_versions_form_version UNIQUE (form_id, version)
);
CREATE INDEX IF NOT EXISTS ix_form_versions_form ON form_versions(form_id);

CREATE TABLE IF NOT EXISTS form_version_questions (
    id BIGSERIAL PRIMARY KEY,
    form_version_id BIGINT NOT NULL REFERENCES form_versions(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL,
    question_text VARCHAR(255),
    description TEXT,
    question_type VARCHAR(50),
    required BOOLEAN,
    options TEXT,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_form_version_questions_version ON form_version_questions(form_version_id);

COMMIT;

SELECT to_regclass('public.form_versions') AS form_versions,
       to_regclass('public.form_version_questions') AS form_version_questions;
