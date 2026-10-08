-- ═══════════════════════════════════════════════════════════════════════════════
-- Guía v3: modelos completos — versionamiento, foto, campo provisional,
-- paquetes, bitácora, autoridades.
-- Migración ADITIVA. Idempotente (IF NOT EXISTS / IF NOT).
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── 1. Enums ─────────────────────────────────────────────────────────────────

DO $$ BEGIN CREATE TYPE formstatus AS ENUM ('publicado','borrador','obsoleto','desactivado'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE draftclass AS ENUM ('nuevo','version'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── 2. Columnas en forms ─────────────────────────────────────────────────────

ALTER TABLE forms ADD COLUMN IF NOT EXISTS form_status formstatus NOT NULL DEFAULT 'publicado';
ALTER TABLE forms ADD COLUMN IF NOT EXISTS draft_class draftclass;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS lineage_id BIGINT REFERENCES forms(id);
ALTER TABLE forms ADD COLUMN IF NOT EXISTS responsible_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS published_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS change_note VARCHAR(500);
ALTER TABLE forms ADD COLUMN IF NOT EXISTS replaced_by_id BIGINT REFERENCES forms(id);
ALTER TABLE forms ADD COLUMN IF NOT EXISTS transferred_from_id BIGINT REFERENCES users(id) ON DELETE SET NULL;

-- Defaults para formatos existentes: ya publicados, v1, responsable = creador
UPDATE forms SET lineage_id = id WHERE lineage_id IS NULL;
UPDATE forms SET responsible_id = user_id WHERE responsible_id IS NULL;
UPDATE forms SET published_by = user_id WHERE published_by IS NULL;
UPDATE forms SET published_at = created_at WHERE published_at IS NULL;
UPDATE forms SET valid_from = created_at WHERE valid_from IS NULL;
UPDATE forms SET form_status = 'desactivado' WHERE is_enabled = false AND form_status = 'publicado';

-- ── 3. Columnas en questions ─────────────────────────────────────────────────

ALTER TABLE questions ADD COLUMN IF NOT EXISTS field_status VARCHAR(25) NOT NULL DEFAULT 'vigente';
ALTER TABLE questions ADD COLUMN IF NOT EXISTS provisional_since TIMESTAMPTZ;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS curated_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS curated_at TIMESTAMPTZ;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS field_restriction VARCHAR(20) NOT NULL DEFAULT 'ninguna';

-- ── 4. Foto de 3 capas ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS form_snapshots (
    id BIGSERIAL PRIMARY KEY,
    trigger_form_id BIGINT REFERENCES forms(id) ON DELETE SET NULL,
    trigger_event VARCHAR(50) NOT NULL DEFAULT 'publication',
    raw_config JSONB NOT NULL,
    raw_config_hash VARCHAR(64) NOT NULL,
    structure JSONB NOT NULL,
    graph JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by BIGINT REFERENCES users(id) ON DELETE SET NULL
);

-- ── 5. Relaciones persistidas ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS form_relations (
    id BIGSERIAL PRIMARY KEY,
    from_form_id BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    to_form_id BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    relation_class VARCHAR(20) NOT NULL DEFAULT 'dato',
    fields JSONB DEFAULT '[]',
    source VARCHAR(50) NOT NULL,
    is_draft BOOLEAN NOT NULL DEFAULT false,
    snapshot_id BIGINT REFERENCES form_snapshots(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 6. snapshot_id en responses ──────────────────────────────────────────────

ALTER TABLE responses ADD COLUMN IF NOT EXISTS snapshot_id BIGINT REFERENCES form_snapshots(id) ON DELETE SET NULL;

-- ── 7. Procedencia en answers ────────────────────────────────────────────────

ALTER TABLE answers ADD COLUMN IF NOT EXISTS source_form_id BIGINT REFERENCES forms(id) ON DELETE SET NULL;
ALTER TABLE answers ADD COLUMN IF NOT EXISTS source_response_id BIGINT REFERENCES responses(id) ON DELETE SET NULL;
ALTER TABLE answers ADD COLUMN IF NOT EXISTS source_question_id BIGINT REFERENCES questions(id) ON DELETE SET NULL;
ALTER TABLE answers ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

-- ── 8. Paquete de borradores ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS draft_packages (
    id BIGSERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'borrador',
    author_id BIGINT NOT NULL REFERENCES users(id),
    requires_approval BOOLEAN NOT NULL DEFAULT false,
    submitted_at TIMESTAMPTZ,
    reviewed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS draft_package_members (
    id BIGSERIAL PRIMARY KEY,
    package_id BIGINT NOT NULL REFERENCES draft_packages(id) ON DELETE CASCADE,
    form_id BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    provisional_ok BOOLEAN NOT NULL DEFAULT false,
    returned BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT uq_draft_pkg_member UNIQUE (package_id, form_id)
);

-- ── 9. Observaciones ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS draft_observations (
    id BIGSERIAL PRIMARY KEY,
    package_id BIGINT NOT NULL REFERENCES draft_packages(id) ON DELETE CASCADE,
    form_id BIGINT REFERENCES forms(id) ON DELETE SET NULL,
    question_id BIGINT REFERENCES questions(id) ON DELETE SET NULL,
    author_id BIGINT NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'abierta',
    response_text TEXT,
    response_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 10. Bitácora solo-adición ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id BIGINT,
    actor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    payload JSONB,
    decision VARCHAR(50),
    observations_snapshot JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'La bitácora es solo-adición: no se puede modificar ni borrar.'; RETURN NULL; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log;
CREATE TRIGGER trg_audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

-- ── 11. Matriz de autoridades ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS folder_approvers (
    id BIGSERIAL PRIMARY KEY,
    category_id BIGINT NOT NULL REFERENCES form_categories(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'titular',
    is_active BOOLEAN NOT NULL DEFAULT true,
    designated_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    designated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT uq_folder_approver UNIQUE (category_id, user_id)
);

-- ── 12. Diseñadores ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS form_designers (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    granted_by BIGINT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    revoked_at TIMESTAMPTZ
);

-- ── 13. Índices ──────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_forms_form_status ON forms(form_status);
CREATE INDEX IF NOT EXISTS ix_forms_lineage ON forms(lineage_id);
CREATE INDEX IF NOT EXISTS ix_questions_field_status ON questions(field_status) WHERE field_status != 'vigente';
CREATE INDEX IF NOT EXISTS ix_draft_packages_status ON draft_packages(status);
CREATE INDEX IF NOT EXISTS ix_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS ix_folder_approvers_category ON folder_approvers(category_id);
