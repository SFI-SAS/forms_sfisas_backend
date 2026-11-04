-- 2026-11-04 — forms.sent_at: cuándo se envió el formato a aprobación.
--
-- La bandeja "Aprobar formatos", Mis borradores y el correo diario de pendientes
-- vencidos contaban la antigüedad desde created_at: un formato creado hace un mes
-- y enviado ayer salía como "vencido" y se escalaba al admin. Ahora se cuenta
-- desde sent_at (se reinicia en cada reenvío); si está vacío, desde created_at.
--
-- Rellena los que ya están en la bandeja con su último reenvío registrado
-- (nota «[ENVIADO] …»), cuando lo hay. Idempotente.

BEGIN;

ALTER TABLE forms ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ NULL;

UPDATE forms f
SET sent_at = n.ultimo
FROM (
    SELECT form_id, MAX(created_at) AS ultimo
    FROM form_approval_notes
    WHERE note_text LIKE '[ENVIADO]%'
    GROUP BY form_id
) n
WHERE n.form_id = f.id
  AND f.form_status = 'enviado'
  AND f.sent_at IS NULL;

COMMIT;

SELECT id, title, created_at, sent_at
FROM forms
WHERE form_status = 'enviado'
ORDER BY id;
