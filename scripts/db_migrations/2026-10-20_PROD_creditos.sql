-- Producción (forms_sfisas_dev): créditos y licencia de la consola.
-- Junta 2026-10-19_tokens_eventos_y_licencia.sql y 2026-10-20_creditos_licencia_v2.sql.
-- Solo agrega columnas, funciones y triggers. Se puede correr dos veces sin daño.
-- APLICADA EN PRODUCCIÓN el 2026-10-20 (verificación: 5 triggers, 9 de 9 columnas, ocupación 18.158).
BEGIN;

-- ════════ 2026-10-19: eventos y licencia ════════
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

-- ════════ 2026-10-20: créditos, licencia v2 y usuarios activos ════════
-- ── 1. Licencia v2 ───────────────────────────────────────────────────────────
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS licencia_contenido JSONB;
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS tarifas JSONB NOT NULL
    DEFAULT '{"usuario": 50, "formato": 20, "movimiento": 20, "campo": 2}'::jsonb;
-- Hoy igual a lo comprado; cuando la consola haga el corte mensual, menos lo cortado.
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS creditos_saldo BIGINT;
-- El logotipo de la empresa, tal como lo entrega la consola (GET /instalaciones/logo).
-- La licencia trae su huella; se vuelve a bajar solo si cambia.
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS empresa_logo      BYTEA;
ALTER TABLE token_account ADD COLUMN IF NOT EXISTS empresa_logo_tipo VARCHAR(30);

-- Tarifa vigente de un concepto. Si no hay fila o falta la clave, la inicial.
CREATE OR REPLACE FUNCTION token_tarifa(p_concepto TEXT) RETURNS INTEGER
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        (SELECT (tarifas ->> p_concepto)::int FROM token_account WHERE id = 1),
        CASE p_concepto WHEN 'usuario' THEN 50 WHEN 'formato' THEN 20
                        WHEN 'movimiento' THEN 20 WHEN 'campo' THEN 2 ELSE 0 END
    )
$$;

-- Mismo cálculo que _ocupacion() en app/api/endpoints/tokens.py.
CREATE OR REPLACE FUNCTION token_ocupado() RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    SELECT (SELECT count(*) FROM users WHERE is_active) * token_tarifa('usuario')
         + (SELECT count(*) FROM forms)                 * token_tarifa('formato')
         + (SELECT count(*) FROM forms_movimientos)     * token_tarifa('movimiento')
         + (SELECT count(*) FROM form_questions)        * token_tarifa('campo')
$$;

-- ── 2. Eventos con la tarifa vigente ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION token_trg_usuario() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.is_active THEN
            PERFORM token_registrar('usuario', NEW.id, 'ocupa', token_tarifa('usuario'), NEW.email);
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.is_active THEN
            PERFORM token_registrar('usuario', OLD.id, 'libera', token_tarifa('usuario'), OLD.email);
        END IF;
    ELSIF NEW.is_active IS DISTINCT FROM OLD.is_active THEN
        -- Dar de baja o reactivar: es la palanca del cliente para su consumo.
        PERFORM token_registrar('usuario', NEW.id,
                                CASE WHEN NEW.is_active THEN 'ocupa' ELSE 'libera' END,
                                token_tarifa('usuario'), NEW.email);
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION token_trg_formato() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM token_registrar('formato', NEW.id, 'ocupa', token_tarifa('formato'), NULL);
    ELSE
        PERFORM token_registrar('formato', OLD.id, 'libera', token_tarifa('formato'), NULL);
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION token_trg_movimiento() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM token_registrar('movimiento', NEW.id, 'ocupa', token_tarifa('movimiento'), NULL);
    ELSE
        PERFORM token_registrar('movimiento', OLD.id, 'libera', token_tarifa('movimiento'), NULL);
    END IF;
    RETURN NULL;
END;
$$;

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
            PERFORM token_registrar('vinculo', NEW.form_id, 'ocupa', token_tarifa('campo'),
                                    'pregunta=' || NEW.question_id);
        END IF;
    ELSE
        PERFORM token_registrar('vinculo', OLD.form_id, 'libera', token_tarifa('campo'),
                                'pregunta=' || OLD.question_id);
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS token_eventos_usuario ON users;
CREATE TRIGGER token_eventos_usuario AFTER INSERT OR DELETE OR UPDATE OF is_active ON users
    FOR EACH ROW EXECUTE FUNCTION token_trg_usuario();

COMMIT;

-- Verificación: 5 triggers, el de usuarios mira la baja, y las columnas nuevas.
SELECT tgname AS que, tgrelid::regclass::text AS detalle,
       (tgname <> 'token_eventos_usuario' OR pg_get_triggerdef(oid) LIKE '%UPDATE OF is_active%') AS ok
FROM pg_trigger WHERE tgname LIKE 'token_eventos_%'
UNION ALL
SELECT 'columnas nuevas en token_account', count(*)::text || ' de 9', count(*) = 9
FROM information_schema.columns WHERE table_name = 'token_account' AND column_name IN
  ('licencia_secuencia','licencia_estado','reporte_intentado_en','reporte_error',
   'licencia_contenido','tarifas','creditos_saldo','empresa_logo','empresa_logo_tipo')
UNION ALL
SELECT 'ocupación actual (créditos)', token_ocupado()::text, true
ORDER BY 1;
