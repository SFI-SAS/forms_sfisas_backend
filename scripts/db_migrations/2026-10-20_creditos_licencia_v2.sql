-- Créditos — licencia v2 de la consola
-- (Andres_201026_Safemetrics_Manual_Maestro_Empaquetado_Venta_AWS_v4.pdf).
--
-- 1. token_account guarda la licencia v2 completa (identidad, canal, plan,
--    módulos, saldo) y las TARIFAS que trae: los créditos por usuario,
--    formato, movimiento y campo se fijan en la consola, no en el código
--    (manual maestro 4.2). Sin licencia rigen 50 / 20 / 20 / 2.
-- 2. Solo ocupa el usuario HABILITADO (users.is_active): dar de baja un
--    usuario libera sus créditos (manual maestro 4.2). El trigger de usuarios
--    ahora también mira el UPDATE de is_active.
--
-- Solo agrega columnas y reemplaza funciones (regla del manual maestro 7).
-- Requiere 2026-10-19_tokens_eventos_y_licencia.sql.
--
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). Producción requiere
-- autorización explícita. Se puede correr dos veces sin daño.

BEGIN;

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

-- Verificación
SELECT tgname, tgrelid::regclass AS tabla, pg_get_triggerdef(oid) LIKE '%UPDATE OF is_active%' AS mira_baja
FROM pg_trigger WHERE tgname LIKE 'token_eventos_%' ORDER BY 1;
