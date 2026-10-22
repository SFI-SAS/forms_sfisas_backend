-- Créditos — vínculos campo↔formato duplicados.
--
-- Había campos vinculados DOS veces al mismo formato (dos filas iguales en
-- form_questions; p. ej. formatos 804 y 805 en local, creados el 10-oct). La
-- pantalla Campos los cuenta una vez y la de créditos dos, y se cobraban 2
-- créditos de más por cada uno. El doble vínculo es un error de guardado, no
-- algo que el cliente tenga montado: se cobra el PAR campo↔formato una vez.
--
-- 1. token_ocupado() cuenta pares distintos (igual que conteos() en tokens.py).
-- 2. El trigger de vínculos no anota la fila repetida: ni al crearla, ni al
--    borrarla mientras quede otra igual.
-- 3. Borra las filas repetidas que ya existen, dejando la primera (la de id
--    menor). Nada guarda el id de form_questions: solo se usa para ordenar.
-- 4. Regla UNIQUE (form_id, question_id): desde aquí la base no deja repetir
--    el par, venga de donde venga (p. ej. doble clic en la alta suelta de
--    crud.py). Los caminos del código ya quitan repetidos (forms.py 21-oct);
--    la regla es la red por si alguno se escapa: falla en vez de duplicar.
--
-- Requiere 2026-10-20_creditos_licencia_v2.sql.
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). Producción requiere
-- autorización explícita. Se puede correr dos veces sin daño.

BEGIN;

-- ── 1. Ocupación con pares distintos ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION token_ocupado() RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    SELECT (SELECT count(*) FROM users WHERE is_active) * token_tarifa('usuario')
         + (SELECT count(*) FROM forms)                 * token_tarifa('formato')
         + (SELECT count(*) FROM forms_movimientos)     * token_tarifa('movimiento')
         + (SELECT count(*) FROM (SELECT DISTINCT form_id, question_id
                                  FROM form_questions) v) * token_tarifa('campo')
$$;

-- ── 2. El trigger ignora la fila repetida ────────────────────────────────────
-- Alta: si ya hay una fila igual con id menor, esta es la repetida. Se mira el
-- id y no solo "si existe otra" porque un INSERT de varias filas dispara los
-- triggers al final y cada fila vería a su gemela.
-- Baja: si queda otra fila igual, el par sigue ocupando. Si se borran las dos
-- en la misma sentencia (guardar un formato borra todo), la segunda ve la
-- liberación que anotó la primera en esta transacción y no la repite.
CREATE OR REPLACE FUNCTION token_trg_vinculo() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_anulado BIGINT;
    v_detalle TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
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

-- ── 3. Limpiar los duplicados que ya existen ─────────────────────────────────
-- Con el trigger nuevo, borrar la repetida no anota nada (queda la original).
DELETE FROM form_questions fq
USING form_questions orig
WHERE orig.form_id = fq.form_id
  AND orig.question_id = fq.question_id
  AND orig.id < fq.id;

-- ── 4. La base no deja repetir el par ────────────────────────────────────────
-- Guardar un formato borra y recrea sus vínculos en la misma transacción: no
-- choca, porque la regla se revisa fila a fila y las viejas ya se borraron.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_questions_par_unico') THEN
        ALTER TABLE form_questions
            ADD CONSTRAINT form_questions_par_unico UNIQUE (form_id, question_id);
    END IF;
END;
$$;

COMMIT;

-- Verificación: 0 pares repetidos, la regla puesta y la ocupación sin ellos.
SELECT 'pares campo-formato repetidos' AS que,
       (SELECT count(*) FROM (SELECT 1 FROM form_questions
                              GROUP BY form_id, question_id HAVING count(*) > 1) d)::text AS valor
UNION ALL
SELECT 'regla form_questions_par_unico',
       CASE WHEN EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_questions_par_unico')
            THEN 'puesta' ELSE 'FALTA' END
UNION ALL
SELECT 'ocupación actual (créditos)', token_ocupado()::text;
