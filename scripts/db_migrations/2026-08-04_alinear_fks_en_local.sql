-- Alinea con PRODUCCIÓN cuatro claves foráneas que en LOCAL se comportaban
-- distinto al borrar. Detectado el 2026-08-04 comparando los dos esquemas.
--
-- Por qué importa: local mentía sobre cómo se comporta producción. Borrar un
-- usuario con plantillas funcionaba en local (CASCADE) y en prod habría fallado.
--
-- APLICADO SOLO EN LOCAL (forms_sfisas @ localhost).

BEGIN;

-- ── 1. questions.id_alias → añadir ON DELETE SET NULL ───────────────────────
-- Prod ya lo tiene (con el nombre fk_questions_alias). Sin esto, borrar un
-- alias usado por alguna pregunta falla en local pero funciona en prod.
ALTER TABLE public.questions
    DROP CONSTRAINT IF EXISTS questions_id_alias_fkey;
ALTER TABLE public.questions
    DROP CONSTRAINT IF EXISTS fk_questions_alias;
ALTER TABLE public.questions
    ADD CONSTRAINT fk_questions_alias
    FOREIGN KEY (id_alias) REFERENCES public.alias(id) ON DELETE SET NULL;

-- ── 2. question_table_relations.related_form_id → ON DELETE SET NULL ────────
-- Igual que arriba: prod lo tiene, local no. Borrar un formato referenciado
-- por una relación de pregunta fallaba solo en local.
ALTER TABLE public.question_table_relations
    DROP CONSTRAINT IF EXISTS question_table_relations_related_form_id_fkey;
ALTER TABLE public.question_table_relations
    ADD CONSTRAINT question_table_relations_related_form_id_fkey
    FOREIGN KEY (related_form_id) REFERENCES public.forms(id) ON DELETE SET NULL;

-- ── 3. form_templates.user_id → quitar el CASCADE ───────────────────────────
-- OJO: esto CAMBIA EL COMPORTAMIENTO EN LOCAL. Hasta ahora, borrar un usuario
-- borraba en silencio todas sus plantillas. Ni el modelo ni producción hacen
-- eso: en prod ese borrado falla. Se alinea local con ambos.
ALTER TABLE public.form_templates
    DROP CONSTRAINT IF EXISTS form_templates_user_id_fkey;
ALTER TABLE public.form_templates
    ADD CONSTRAINT form_templates_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES public.users(id);

-- ── 4. form_templates.id_category → quitar el SET NULL ──────────────────────
ALTER TABLE public.form_templates
    DROP CONSTRAINT IF EXISTS form_templates_id_category_fkey;
ALTER TABLE public.form_templates
    ADD CONSTRAINT form_templates_id_category_fkey
    FOREIGN KEY (id_category) REFERENCES public.form_categories(id);

COMMIT;

-- NO SE TOCAN aquí las cuatro FK de firma (form_approvals, category_approvals,
-- response_approvals x2). En esas LOCAL ya coincide con el modelo y es
-- PRODUCCIÓN la que está mal: le falta el ON DELETE SET NULL que el modelo
-- declara, así que allá borrar una pregunta o respuesta referenciada por una
-- aprobación revienta. Ese arreglo va en un script aparte, para prod, y
-- requiere autorización explícita.
