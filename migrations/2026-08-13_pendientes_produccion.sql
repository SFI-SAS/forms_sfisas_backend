-- ═════════════════════════════════════════════════════════════════════════════
-- LO QUE LE FALTA A PRODUCCIÓN (comparado el 2026-08-13)
--
-- Consolida las migraciones de la feature "campos por aprobador" en el orden
-- correcto y sin pasos muertos: el intento intermedio con la tabla
-- `approver_responses` se descartó el mismo día, así que aquí no se crea.
--
-- Diferencias detectadas contra forms_sfisas @ localhost (PG18) vs
-- forms_sfisas_dev @ 207.246.75.205 (PG14):
--   · falta la tabla  form_approval_field_access
--   · faltan columnas answers.answered_by_user_id, answers.answered_at
--   · falta columna   responses.parent_response_id
--   · faltan índices  ix_answers_answered_by, ix_responses_parent,
--                     uq_responses_parent_user
--
-- Todo es ADITIVO: columnas nullable sin default e índices. No reescribe ni
-- borra datos, y las filas existentes quedan con NULL, que es lo correcto
-- (NULL = lo escribió quien diligenció el formato / no es respuesta de aprobador).
--
-- APLICADO EN PRODUCCIÓN el 2026-08-13, con autorización explícita del usuario.
-- Respaldo previo:
--   _db_backups/prod_forms_sfisas_dev_COMPLETO_2026-08-13_1410_antes_campos_aprobador.sql
-- Verificado después: local y prod tienen el mismo esquema (tablas, columnas e
-- índices). Los índices de auth_events del final también se aplicaron.
--
-- Para deshacer (solo si hiciera falta):
--   DROP INDEX IF EXISTS uq_responses_parent_user;
--   DROP INDEX IF EXISTS ix_responses_parent;
--   ALTER TABLE responses DROP COLUMN IF EXISTS parent_response_id;
--   DROP INDEX IF EXISTS ix_answers_answered_by;
--   ALTER TABLE answers DROP COLUMN IF EXISTS answered_at;
--   ALTER TABLE answers DROP COLUMN IF EXISTS answered_by_user_id;
--   DROP TABLE IF EXISTS form_approval_field_access;
--
-- OJO: la tabla `answers` la comparten el backend web y el móvil; las columnas
-- nuevas son nullable, así que los INSERT de ambos siguen siendo válidos.
-- ═════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Qué campos ve/llena cada aprobador, y qué filas le llegan ────────────
-- `config` va como TEXT, igual que en local: el tipo AutoJSON del backend
-- serializa el JSON a texto (no usa el tipo json de Postgres).
CREATE TABLE IF NOT EXISTS form_approval_field_access (
    id          BIGSERIAL PRIMARY KEY,
    form_id     BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NULL,
    CONSTRAINT uq_form_approval_field_access UNIQUE (form_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_form_approval_field_access_form
    ON form_approval_field_access (form_id);

-- ── 2. Autoría y fecha de cada respuesta ────────────────────────────────────
-- NULL = lo escribió quien diligenció el formato (Response.user_id).
ALTER TABLE answers
    ADD COLUMN IF NOT EXISTS answered_by_user_id BIGINT NULL
    REFERENCES users(id) ON DELETE SET NULL;

-- Solo se llena en las respuestas de aprobador; las del diligenciador se
-- fechan por responses.submitted_at, como siempre.
ALTER TABLE answers
    ADD COLUMN IF NOT EXISTS answered_at TIMESTAMPTZ NULL;

-- Índice parcial: se consulta siempre acotado a una respuesta y evita cargar
-- el 99% de filas en NULL.
CREATE INDEX IF NOT EXISTS ix_answers_answered_by
    ON answers (response_id, answered_by_user_id)
    WHERE answered_by_user_id IS NOT NULL;

-- ── 3. La respuesta del aprobador cuelga de la del diligenciador ────────────
-- NULL = diligenciamiento normal. Toda consulta que liste o cuente respuestas
-- por formato debe excluir las hijas (lo hace el filtro global de
-- app/core/response_scope.py).
ALTER TABLE responses
    ADD COLUMN IF NOT EXISTS parent_response_id BIGINT NULL
    REFERENCES responses(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_responses_parent
    ON responses (parent_response_id)
    WHERE parent_response_id IS NOT NULL;

-- Un aprobador tiene UNA sola respuesta por cada respuesta que revisa.
CREATE UNIQUE INDEX IF NOT EXISTS uq_responses_parent_user
    ON responses (parent_response_id, user_id)
    WHERE parent_response_id IS NOT NULL;

COMMIT;

-- ── Aparte: índices de auth_events ──────────────────────────────────────────
-- No son de esta feature; vienen de 2026-06-13_sm_cargo_auth_events y nunca se
-- aplicaron en prod. Solo afectan al rendimiento de las consultas de auditoría.
-- CREATE INDEX IF NOT EXISTS ix_auth_events_created_at ON auth_events (created_at);
-- CREATE INDEX IF NOT EXISTS ix_auth_events_event_type ON auth_events (event_type);
