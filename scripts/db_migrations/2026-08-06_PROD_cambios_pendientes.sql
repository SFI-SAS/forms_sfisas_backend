-- ✅ EJECUTADO EN PRODUCCIÓN (forms_sfisas_dev @ 207.246.75.205) el 2026-08-06,
--    con autorización. Respaldo previo:
--    _db_backups/prod_forms_sfisas_dev_ESQUEMA_2026-08-06_antes_tokens.sql
--    Es idempotente: volver a correrlo no hace daño.
--
-- Consolida lo que existe en LOCAL (forms_sfisas @ localhost) y falta en PROD,
-- verificado comparando los dos esquemas el 2026-08-06.
--
-- Todo es IDEMPOTENTE y ADITIVO: no borra ni modifica datos existentes, y se
-- puede volver a ejecutar sin efecto. Prod es PostgreSQL 14; toda la sintaxis
-- usada es compatible.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. Operaciones matemáticas: recorte de resultados negativos
-- ═══════════════════════════════════════════════════════════════════════════
-- Opción por operación: si la fórmula da menos de cero, se presenta y guarda 0.
-- FALSE por defecto = ninguna operación existente cambia de comportamiento.
ALTER TABLE relation_operation_math
    ADD COLUMN IF NOT EXISTS clamp_negativos BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN relation_operation_math.clamp_negativos IS
    'Si es TRUE, un resultado negativo de la operación se convierte en 0.';

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. Tokens — FASE DE MEDICIÓN
-- ═══════════════════════════════════════════════════════════════════════════
-- Estas tablas SOLO MIDEN. `bloqueo_activo` arranca en FALSE: no impiden crear
-- usuarios, formatos ni vínculos. Sirven para conocer el consumo real antes de
-- activar el cobro. Ver DISENO_tokens_licenciamiento.md.

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

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. Índice sobre questions.id_alias
-- ═══════════════════════════════════════════════════════════════════════════
-- El modelo declara index=True en esa columna y hay una FK apuntando a alias.
-- Existe en local y falta en prod: sin él, borrar un alias hace escaneo completo
-- de `questions`.
CREATE INDEX IF NOT EXISTS ix_questions_id_alias ON questions (id_alias);

COMMIT;

-- ═══════════════════════════════════════════════════════════════════════════
-- VERIFICACIÓN — correr después y comprobar que devuelve 4 filas
-- ═══════════════════════════════════════════════════════════════════════════
-- SELECT 'clamp_negativos' AS item,
--        count(*) FILTER (WHERE column_name='clamp_negativos') AS ok
--   FROM information_schema.columns WHERE table_name='relation_operation_math'
-- UNION ALL SELECT 'token_account', count(*) FROM information_schema.tables
--   WHERE table_name='token_account'
-- UNION ALL SELECT 'token_events', count(*) FROM information_schema.tables
--   WHERE table_name='token_events'
-- UNION ALL SELECT 'ix_questions_id_alias', count(*) FROM pg_indexes
--   WHERE indexname='ix_questions_id_alias';


-- ═══════════════════════════════════════════════════════════════════════════
-- LO QUE **NO** ESTÁ AQUÍ, A PROPÓSITO
-- ═══════════════════════════════════════════════════════════════════════════
--
-- a) question_table_relations.logged_user_part
--    YA EXISTE en prod, creada por fuera como VARCHAR sin límite (en local es
--    VARCHAR(30)). Funcionalmente da igual: el modelo declara 30 y una columna
--    sin límite acepta ese valor. No se toca.
--
-- b) Las 4 claves foráneas de firma (form_approvals, category_approvals,
--    response_approvals x2) a las que prod les falta ON DELETE SET NULL.
--    Es un BUG REAL de prod —borrar una pregunta usada como origen de firma
--    falla— pero cambia comportamiento, no estructura. Va aparte, en
--    2026-08-04_PROD_fks_firma_faltantes.sql.
--
-- c) form_templates: en local hay DEFAULT 'private' en `scope` y un CHECK que
--    limita a private|company|public; prod no tiene ninguno de los dos. Es
--    deriva previa, no un cambio nuestro. Añadir el CHECK sobre 5 filas ya
--    existentes podría fallar si alguna tiene otro valor: comprobar primero con
--      SELECT DISTINCT scope FROM form_templates;
--
-- d) question_request_fields.user_id — columna huérfana que solo existe en PROD,
--    no está en el modelo y tiene 0 de 928 filas con valor. Sobra, pero borrar
--    una columna es irreversible: decidirlo aparte.
--
-- e) Los índices de auth_events tienen nombres distintos en cada base
--    (ix_auth_events_* vs idx_auth_events_*) pero cubren lo mismo. Renombrarlos
--    es cosmético y no aporta nada.
