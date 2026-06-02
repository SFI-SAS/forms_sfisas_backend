-- ============================================================================
-- Migración: answer_editors (editores de respuestas en formatos cerrados)
-- Fecha: 2026-06-02
-- Idempotente.
--
-- Soporta la feature de ntorres (commit d6a956c) reconciliada a main/aria-rama
-- el 2026-06-02. Modela quién puede editar SUS PROPIAS respuestas en formatos
-- CERRADOS. Una respuesta ya aprobada queda inmutable en todos los casos.
--
--   Form.answer_editors_mode:
--     'none' → nadie edita respuestas existentes (default).
--     'all'  → cualquier diligenciador asignado al formato edita las suyas.
--     'list' → solo los user_id en form_answer_editors editan las suyas.
--   En formatos abierto/semi_abierto se ignora (comportamiento legacy).
--
-- Mapea exactamente a app/models.py:
--   Form.answer_editors_mode = Column(String(10), nullable=False, default='none')
--   class FormAnswerEditor (__tablename__='form_answer_editors')
-- ============================================================================

BEGIN;

-- 1) Columna de modo en forms ------------------------------------------------
ALTER TABLE forms
    ADD COLUMN IF NOT EXISTS answer_editors_mode VARCHAR(10) NOT NULL DEFAULT 'none';

-- 2) Tabla de editores autorizados (modo 'list') -----------------------------
CREATE TABLE IF NOT EXISTS form_answer_editors (
    id           BIGSERIAL PRIMARY KEY,
    form_id      BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_form_answer_editor UNIQUE (form_id, user_id)
);

-- Índices declarados en el modelo (index=True en form_id y user_id).
CREATE INDEX IF NOT EXISTS ix_form_answer_editors_form_id
    ON form_answer_editors (form_id);

CREATE INDEX IF NOT EXISTS ix_form_answer_editors_user_id
    ON form_answer_editors (user_id);

COMMIT;

-- ============================================================================
-- OPCIONAL (no está en el modelo ORM; descomentar si se quiere integridad a
-- nivel BD del dominio de answer_editors_mode). Idempotente vía guardia.
-- ============================================================================
-- DO $$
-- BEGIN
--     IF NOT EXISTS (
--         SELECT 1 FROM pg_constraint WHERE conname = 'ck_forms_answer_editors_mode'
--     ) THEN
--         ALTER TABLE forms
--             ADD CONSTRAINT ck_forms_answer_editors_mode
--             CHECK (answer_editors_mode IN ('none', 'all', 'list'));
--     END IF;
-- END $$;

-- VERIFICACIÓN:
-- SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns
--  WHERE table_name = 'forms' AND column_name = 'answer_editors_mode';
-- \d form_answer_editors
-- SELECT form_id, user_id, assigned_at FROM form_answer_editors ORDER BY assigned_at DESC LIMIT 10;
