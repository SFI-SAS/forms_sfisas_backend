-- Tokens — paso 2 de la consola de administración
-- (Neider_161026_Safemetrics_Manual_Consola_Administracion_v2.pdf, numeral 8).
--
-- 1. token_account guarda lo que trae la licencia firmada por la consola.
-- 2. token_events se llena SOLO, con triggers sobre las cuatro tablas que
--    ocupan capacidad (users, forms, forms_movimientos, form_questions).
--
-- Por qué triggers y no enganches en cada endpoint: hay más de diez rutas que
-- crean o borran estas filas (algunas en zonas intocables) y varias lo hacen
-- con SQL directo. El trigger las ve todas, incluidos los borrados en cascada.
--
-- Quién lo hizo: el backend pone en cada transacción
--   set_config('safemetrics.actor_email', <email del token>, true)
--   set_config('safemetrics.origen', 'ui' | 'api', true)
-- (app/services/token_actor.py). Sin eso (scripts, tareas) quedan en NULL.
--
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). Producción requiere
-- autorización explícita. Se puede correr dos veces sin daño.

BEGIN;

-- ── 1. Licencia ──────────────────────────────────────────────────────────────
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS licencia_secuencia INTEGER;
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS licencia_estado    VARCHAR(20);
-- Último intento de reportar a la consola, salga bien o mal (manual 6.1 paso 4:
-- "verificar que la instalación reporta").
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS reporte_intentado_en TIMESTAMPTZ;
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS reporte_error        TEXT;

-- ── 2. Eventos ───────────────────────────────────────────────────────────────
-- txid: para anular una baja y un alta del MISMO vínculo dentro de la misma
-- transacción. Guardar un formato borra y recrea todos sus vínculos
-- (forms.py update_form_questions, _form_versions_endpoint.py); sin esto cada
-- guardado parecería una ola de bajas y altas y engañaría a la detección de
-- fraude.
ALTER TABLE token_events ADD COLUMN IF NOT EXISTS txid BIGINT;
CREATE INDEX IF NOT EXISTS idx_token_events_txid ON token_events (txid) WHERE txid IS NOT NULL;

-- Mismo cálculo que _ocupacion() en app/api/endpoints/tokens.py.
CREATE OR REPLACE FUNCTION token_ocupado() RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    SELECT (SELECT count(*) FROM users)             * 50
         + (SELECT count(*) FROM forms)             * 20
         + (SELECT count(*) FROM forms_movimientos) * 20
         + (SELECT count(*) FROM form_questions)    * 2
$$;

CREATE OR REPLACE FUNCTION token_registrar(
    p_tipo VARCHAR, p_id BIGINT, p_accion VARCHAR, p_tokens INTEGER, p_detalle TEXT
) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE
    v_email TEXT := NULLIF(current_setting('safemetrics.actor_email', true), '');
BEGIN
    INSERT INTO token_events (actor_user_id, entidad_tipo, entidad_id, accion, tokens, origen, detalle, txid)
    VALUES (
        (SELECT id FROM users WHERE email = v_email),
        p_tipo, p_id, p_accion, p_tokens,
        NULLIF(current_setting('safemetrics.origen', true), ''),
        p_detalle, txid_current()
    );
END;
$$;

CREATE OR REPLACE FUNCTION token_trg_usuario() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM token_registrar('usuario', NEW.id, 'ocupa', 50, NEW.email);
    ELSE
        PERFORM token_registrar('usuario', OLD.id, 'libera', 50, OLD.email);
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION token_trg_formato() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM token_registrar('formato', NEW.id, 'ocupa', 20, NULL);
    ELSE
        PERFORM token_registrar('formato', OLD.id, 'libera', 20, NULL);
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION token_trg_movimiento() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM token_registrar('movimiento', NEW.id, 'ocupa', 20, NULL);
    ELSE
        PERFORM token_registrar('movimiento', OLD.id, 'libera', 20, NULL);
    END IF;
    RETURN NULL;
END;
$$;

-- Vínculo campo↔formato: entidad_id = formato, detalle = 'pregunta=<id>'.
-- Un alta que repone una baja de la misma transacción la anula y no deja nada.
CREATE OR REPLACE FUNCTION token_trg_vinculo() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_anulado BIGINT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        DELETE FROM token_events
        WHERE id = (
            SELECT id FROM token_events
            WHERE txid = txid_current() AND entidad_tipo = 'vinculo' AND accion = 'libera'
              AND entidad_id = NEW.form_id AND detalle = 'pregunta=' || NEW.question_id
            LIMIT 1
        )
        RETURNING id INTO v_anulado;
        IF v_anulado IS NULL THEN
            PERFORM token_registrar('vinculo', NEW.form_id, 'ocupa', 2, 'pregunta=' || NEW.question_id);
        END IF;
    ELSE
        PERFORM token_registrar('vinculo', OLD.form_id, 'libera', 2, 'pregunta=' || OLD.question_id);
    END IF;
    RETURN NULL;
END;
$$;

-- ocupado_despues se calcula AL CONFIRMAR la transacción (trigger diferido):
-- a mitad de un guardado el conteo está a medias, y así cada fila cuesta un
-- solo conteo en vez de uno por vínculo.
CREATE OR REPLACE FUNCTION token_trg_foto_ocupado() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE token_events SET ocupado_despues = token_ocupado() WHERE id = NEW.id;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS token_eventos_usuario    ON users;
DROP TRIGGER IF EXISTS token_eventos_formato    ON forms;
DROP TRIGGER IF EXISTS token_eventos_movimiento ON forms_movimientos;
DROP TRIGGER IF EXISTS token_eventos_vinculo    ON form_questions;
DROP TRIGGER IF EXISTS token_eventos_foto       ON token_events;

CREATE TRIGGER token_eventos_usuario    AFTER INSERT OR DELETE ON users
    FOR EACH ROW EXECUTE FUNCTION token_trg_usuario();
CREATE TRIGGER token_eventos_formato    AFTER INSERT OR DELETE ON forms
    FOR EACH ROW EXECUTE FUNCTION token_trg_formato();
CREATE TRIGGER token_eventos_movimiento AFTER INSERT OR DELETE ON forms_movimientos
    FOR EACH ROW EXECUTE FUNCTION token_trg_movimiento();
CREATE TRIGGER token_eventos_vinculo    AFTER INSERT OR DELETE ON form_questions
    FOR EACH ROW EXECUTE FUNCTION token_trg_vinculo();
CREATE CONSTRAINT TRIGGER token_eventos_foto AFTER INSERT ON token_events
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION token_trg_foto_ocupado();

COMMIT;

-- Verificación
SELECT tgname, tgrelid::regclass AS tabla
FROM pg_trigger WHERE tgname LIKE 'token_eventos_%' ORDER BY 1;
