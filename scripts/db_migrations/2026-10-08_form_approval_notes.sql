-- form_approval_notes (modelo FormApprovalNote, Guía v3): estaba en models.py sin migración.
-- La usan /forms/approval-notes y el borrado de formatos (crud.delete_form la limpia): sin la tabla,
-- borrar CUALQUIER formato da 500 (UndefinedTable). Idempotente.
CREATE TABLE IF NOT EXISTS form_approval_notes (
    id BIGSERIAL PRIMARY KEY,
    form_id BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    note_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_form_approval_notes_form ON form_approval_notes(form_id);
