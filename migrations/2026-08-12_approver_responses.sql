-- ═════════════════════════════════════════════════════════════════════════════
-- La participación del aprobador como registro propio (2026-08-12)
--
-- Cuando un aprobador llena SUS campos, la respuesta del diligenciador no se
-- toca: solo se insertan answers nuevas marcadas con answered_by_user_id. Pero
-- esas answers no eran de nadie a efectos de listados — no aparecían en el
-- "Consultar respuestas" del propio aprobador y no había fecha de cuándo las
-- escribió.
--
-- Esta tabla es esa respuesta del aprobador: una fila por (respuesta original,
-- aprobador), con su fecha de envío y de última edición.
--
-- POR QUÉ TABLA APARTE Y NO UNA FILA EN `responses`:
-- unas 80 consultas listan o cuentan `responses` por formato/usuario (listados,
-- exports, movimientos, tableros). Una respuesta hija ahí dentro se contaría
-- como un diligenciamiento más en todas ellas. Aquí no estorba a nadie, y las
-- answers siguen colgando de la respuesta original, así que los ~70 lectores que
-- las leen por response_id siguen funcionando sin cambios.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
--
-- OJO: la tabla answers la comparten el backend web y el móvil. Las dos columnas
-- nuevas son nullable y sin default: los INSERT existentes de ambos siguen
-- válidos y las filas históricas quedan en NULL, que es lo correcto.
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS approver_responses (
    id            BIGSERIAL PRIMARY KEY,
    response_id   BIGINT NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    form_id       BIGINT NOT NULL REFERENCES forms(id),
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NULL,
    CONSTRAINT uq_approver_response UNIQUE (response_id, user_id)
);

-- "Mis respuestas como aprobador", ordenadas por fecha.
CREATE INDEX IF NOT EXISTS ix_approver_responses_user
    ON approver_responses (user_id, submitted_at DESC);

-- A qué participación pertenece cada answer escrita por un aprobador.
ALTER TABLE answers
    ADD COLUMN IF NOT EXISTS approver_response_id BIGINT NULL
    REFERENCES approver_responses(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_answers_approver_response
    ON answers (approver_response_id)
    WHERE approver_response_id IS NOT NULL;

-- Cuándo se escribió el dato. Solo se llena para las answers de aprobador; las
-- del diligenciador siguen fechándose por Response.submitted_at, como siempre.
ALTER TABLE answers
    ADD COLUMN IF NOT EXISTS answered_at TIMESTAMPTZ NULL;
