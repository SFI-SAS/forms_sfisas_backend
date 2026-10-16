-- Servicios dentro de una categoría de formatos (una sola por servicio).
-- En los exploradores y en los selectores de categoría el servicio sale dentro
-- de ella. SET NULL: borrar la categoría deja el servicio sin categoría. Idempotente.
ALTER TABLE generic_activities
    ADD COLUMN IF NOT EXISTS category_id BIGINT NULL
    REFERENCES form_categories(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_generic_activities_category_id ON generic_activities(category_id);
