-- Créditos — un formato ocupa solo si alguna vez se activó.
--
-- Respuesta de Andrés a la pregunta 7 (22-oct): «el formato en borrador ocupa
-- espacio solo si en algún momento se activó; si se desactiva, sigue
-- ocupando». Hasta ahora contaba todo lo que había en `forms`, así que:
--   - un borrador nuevo ocupaba desde que se guardaba, antes de aprobarse;
--   - uno rechazado seguía ocupando para siempre;
--   - el borrador de una versión nueva duplica los vínculos del publicado, y
--     ese formato se cobraba dos veces mientras se aprobaba.
--
-- «Alguna vez activo» = no estar en borrador ni enviado. Un publicado nunca
-- vuelve a borrador: lo que se edita va a un borrador APARTE (draft_class
-- version) que al aprobarse se vuelca sobre el mismo id y se borra.
--
-- 1. token_formato_cuenta(id): la regla, en un solo sitio.
-- 2. token_ocupado() cuenta solo formatos activados y sus vínculos (igual que
--    conteos() en tokens.py, FORMATO_CUENTA).
-- 3. El trigger de formatos anota al PUBLICAR (no al crear el borrador): el
--    formato y cada campo que ya tenía. Al borrar uno activado, lo libera.
-- 4. El trigger de vínculos no anota nada de un borrador.
--
-- Los eventos viejos de borradores se quedan en token_events: son historial.
-- La ocupación se calcula siempre en vivo, así que baja sola.
--
-- Requiere 2026-10-21_vinculos_duplicados.sql.
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). Producción requiere
-- autorización explícita. Se puede correr dos veces sin daño.

BEGIN;

-- ── 1. La regla ──────────────────────────────────────────────────────────────
-- Si el formato no existe (ya se borró), no cuenta.
CREATE OR REPLACE FUNCTION token_formato_cuenta(p_form_id BIGINT) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        (SELECT form_status::text NOT IN ('borrador', 'enviado') FROM forms WHERE id = p_form_id),
        false
    )
$$;

-- ── 2. Ocupación ─────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION token_ocupado() RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    SELECT (SELECT count(*) FROM users WHERE is_active) * token_tarifa('usuario')
         + (SELECT count(*) FROM forms
            WHERE form_status::text NOT IN ('borrador', 'enviado')) * token_tarifa('formato')
         + (SELECT count(*) FROM forms_movimientos) * token_tarifa('movimiento')
         + (SELECT count(*) FROM (SELECT DISTINCT fq.form_id, fq.question_id
                                  FROM form_questions fq
                                  JOIN forms f ON f.id = fq.form_id
                                  WHERE f.form_status::text NOT IN ('borrador', 'enviado')) v)
           * token_tarifa('campo')
$$;

-- ── 3. Formatos: se anota al activarse ───────────────────────────────────────
CREATE OR REPLACE FUNCTION token_trg_formato() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_antes BOOLEAN := false;
    v_ahora BOOLEAN := false;
    v_id    BIGINT;
    v_q     BIGINT;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        v_antes := OLD.form_status::text NOT IN ('borrador', 'enviado');
        v_id := OLD.id;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        v_ahora := NEW.form_status::text NOT IN ('borrador', 'enviado');
        v_id := NEW.id;
    END IF;
    IF v_antes = v_ahora THEN
        RETURN NULL;
    END IF;

    PERFORM token_registrar('formato', v_id, CASE WHEN v_ahora THEN 'ocupa' ELSE 'libera' END,
                            token_tarifa('formato'), NULL);

    -- Al publicarse, los campos que ya tenía empiezan a ocupar. En un INSERT
    -- todavía no hay ninguno, y antes de un DELETE ya se borraron (la llave
    -- de form_questions no borra en cascada), cada uno con su evento.
    IF TG_OP = 'UPDATE' THEN
        FOR v_q IN SELECT DISTINCT question_id FROM form_questions WHERE form_id = v_id LOOP
            PERFORM token_registrar('vinculo', v_id, CASE WHEN v_ahora THEN 'ocupa' ELSE 'libera' END,
                                    token_tarifa('campo'), 'pregunta=' || v_q);
        END LOOP;
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS token_eventos_formato ON forms;
CREATE TRIGGER token_eventos_formato AFTER INSERT OR DELETE OR UPDATE OF form_status ON forms
    FOR EACH ROW EXECUTE FUNCTION token_trg_formato();

-- ── 4. Vínculos: los de un borrador no se anotan ─────────────────────────────
-- Igual que en 2026-10-21 (fila repetida y anulación por txid), con el filtro
-- del borrador delante.
CREATE OR REPLACE FUNCTION token_trg_vinculo() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_anulado BIGINT;
    v_detalle TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT token_formato_cuenta(NEW.form_id) THEN
            RETURN NULL;
        END IF;
        IF EXISTS (SELECT 1 FROM form_questions
                   WHERE form_id = NEW.form_id AND question_id = NEW.question_id AND id < NEW.id) THEN
            RETURN NULL;
        END IF;
        v_detalle := 'pregunta=' || NEW.question_id;
        DELETE FROM token_events
        WHERE id = (
            SELECT id FROM token_events
            WHERE txid = txid_current() AND entidad_tipo = 'vinculo' AND accion = 'libera'
              AND entidad_id = NEW.form_id AND detalle = v_detalle
            LIMIT 1
        )
        RETURNING id INTO v_anulado;
        IF v_anulado IS NULL THEN
            PERFORM token_registrar('vinculo', NEW.form_id, 'ocupa', token_tarifa('campo'), v_detalle);
        END IF;
    ELSE
        IF NOT token_formato_cuenta(OLD.form_id) THEN
            RETURN NULL;
        END IF;
        v_detalle := 'pregunta=' || OLD.question_id;
        IF EXISTS (SELECT 1 FROM form_questions
                   WHERE form_id = OLD.form_id AND question_id = OLD.question_id)
           OR EXISTS (SELECT 1 FROM token_events
                      WHERE txid = txid_current() AND entidad_tipo = 'vinculo' AND accion = 'libera'
                        AND entidad_id = OLD.form_id AND detalle = v_detalle) THEN
            RETURN NULL;
        END IF;
        PERFORM token_registrar('vinculo', OLD.form_id, 'libera', token_tarifa('campo'), v_detalle);
    END IF;
    RETURN NULL;
END;
$$;

COMMIT;

-- Verificación: el trigger de formatos mira el estado, cuántos borradores
-- dejan de cobrarse y la ocupación con la regla nueva.
SELECT 'trigger de formatos mira form_status' AS que,
       (SELECT pg_get_triggerdef(oid) LIKE '%UPDATE OF form_status%'
        FROM pg_trigger WHERE tgname = 'token_eventos_formato')::text AS valor
UNION ALL
SELECT 'borradores que ya no ocupan',
       (SELECT count(*) FROM forms WHERE form_status::text IN ('borrador', 'enviado'))::text
UNION ALL
SELECT 'ocupación actual (créditos)', token_ocupado()::text;
