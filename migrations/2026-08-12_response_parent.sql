-- ═════════════════════════════════════════════════════════════════════════════
-- La respuesta del aprobador es una RESPUESTA APARTE (2026-08-12)
--
-- Reemplaza el intento anterior (`approver_responses`, de esta misma fecha): en
-- vez de una tabla satélite, lo que responde el aprobador va a un Response
-- propio, suyo, colgado del de quien diligenció.
--
--   responses (diligenciador)  ← parent_response_id ─  responses (aprobador)
--        └─ answers del diligenciador                       └─ answers del aprobador
--
-- Así la respuesta original queda EXACTAMENTE como la mandó su autor, y el
-- aprobador ve la suya en "Consultar mis respuestas". Al mostrar el formato se
-- unen las dos y cada dato lleva su autor (answered_by_user_id / answered_at).
--
-- OJO: las respuestas hijas NO son diligenciamientos. Todo listado o conteo de
-- respuestas por formato debe excluirlas con `parent_response_id IS NULL`.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE responses
    ADD COLUMN IF NOT EXISTS parent_response_id BIGINT NULL
    REFERENCES responses(id) ON DELETE CASCADE;

-- Casi todas las responses son de diligenciamiento (columna NULL): índice
-- parcial para buscar las hijas de una respuesta sin cargar el resto.
CREATE INDEX IF NOT EXISTS ix_responses_parent
    ON responses (parent_response_id)
    WHERE parent_response_id IS NOT NULL;

-- Un aprobador tiene UNA sola respuesta por cada respuesta que revisa.
CREATE UNIQUE INDEX IF NOT EXISTS uq_responses_parent_user
    ON responses (parent_response_id, user_id)
    WHERE parent_response_id IS NOT NULL;

-- La tabla satélite anterior queda sin uso: su papel lo cumple la respuesta
-- hija. Se creó hoy mismo y nunca tuvo filas.
ALTER TABLE answers DROP COLUMN IF EXISTS approver_response_id;
DROP TABLE IF EXISTS approver_responses;
