-- ============================================================================
-- Borrado de diligenciamientos del formato "CONTROL ASISTENCIA DIARIA"
-- Target DB: andres_safemetrics @ 207.246.75.205  (PROD)
-- ----------------------------------------------------------------------------
-- Elimina responses + answers + todas sus tablas hijas con FK.
-- SEGURO POR DEFECTO: abre transacción, muestra conteos y NO hace COMMIT.
-- Revisa los conteos y escribe  COMMIT;  (o  ROLLBACK;  para abortar).
-- ============================================================================

BEGIN;

-- 1) Formato(s) objetivo (match exacto, tolerante a mayúsculas/espacios)
CREATE TEMP TABLE _target_forms ON COMMIT DROP AS
SELECT id, title FROM forms
WHERE btrim(upper(title)) = 'CONTROL ASISTENCIA DIARIA';

CREATE TEMP TABLE _target_responses ON COMMIT DROP AS
SELECT id FROM responses WHERE form_id IN (SELECT id FROM _target_forms);

CREATE TEMP TABLE _target_answers ON COMMIT DROP AS
SELECT id FROM answers WHERE response_id IN (SELECT id FROM _target_responses);

-- 2) PREVISUALIZACIÓN — revisa esto antes de confirmar
\echo '>>> Formato(s) encontrados:'
SELECT * FROM _target_forms;
\echo '>>> Conteos a borrar:'
SELECT (SELECT count(*) FROM _target_responses) AS responses,
       (SELECT count(*) FROM _target_answers)   AS answers;

-- 3) Borrado de tablas hijas (orden FK: hijos -> padres)
DELETE FROM answer_file_serials
 WHERE answer_id IN (SELECT id FROM _target_answers);

DELETE FROM answer_history
 WHERE response_id        IN (SELECT id FROM _target_responses)
    OR previous_answer_id IN (SELECT id FROM _target_answers)
    OR current_answer_id  IN (SELECT id FROM _target_answers);

DELETE FROM response_approvals
 WHERE response_id IN (SELECT id FROM _target_responses);

DELETE FROM response_approval_requirements
 WHERE response_id            IN (SELECT id FROM _target_responses)
    OR fulfilling_response_id IN (SELECT id FROM _target_responses);

DELETE FROM relation_question_rule
 WHERE id_response IN (SELECT id FROM _target_responses);

DELETE FROM response_service_links
 WHERE response_id IN (SELECT id FROM _target_responses);

-- 4) Borrado de answers y responses (padres)
DELETE FROM answers
 WHERE response_id IN (SELECT id FROM _target_responses);

DELETE FROM responses
 WHERE id IN (SELECT id FROM _target_responses);

-- ----------------------------------------------------------------------------
-- Si los conteos eran correctos:   COMMIT;
-- Si algo se ve mal:               ROLLBACK;
-- ----------------------------------------------------------------------------
