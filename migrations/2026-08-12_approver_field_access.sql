-- ═════════════════════════════════════════════════════════════════════════════
-- Campos y filas por aprobador (2026-08-12)
--
-- Guarda, por (formato, usuario aprobador), qué campos ve / llena / no ve y qué
-- filas del repetidor le llegan. Se administra desde "Administrar aprobadores"
-- → "Configurar campos".
--
-- Aditivo: un formato sin filas aquí se comporta exactamente como antes
-- (el aprobador ve todo el formato en solo lectura).
--
-- Forma de `config`:
--   {
--     "rules": [ {"element_id": "...", "question_id": 12, "mode": "edit"} ],
--     "row_filters": [ {"repeater_id": "...", "element_id": "...",
--                       "question_id": 34, "values": ["Contado"]} ]
--   }
-- modes: 'hidden' | 'read' | 'edit'  (solo se persiste lo distinto de 'read')
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS form_approval_field_access (
    id          BIGSERIAL PRIMARY KEY,
    form_id     BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config      TEXT   NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NULL,
    CONSTRAINT uq_form_approval_field_access UNIQUE (form_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_form_approval_field_access_form
    ON form_approval_field_access (form_id);
