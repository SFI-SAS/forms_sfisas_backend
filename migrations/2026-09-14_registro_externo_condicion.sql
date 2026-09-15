-- ═════════════════════════════════════════════════════════════════════════════
-- Registro externo: condicion de fila (2026-09-14)
--
-- El caso real: la asistencia diaria trae 40 trabajadores y una columna
-- "Requiere quedarse" de Si/No. Solo a los que dicen Si hay que pedirles el
-- registro de salida. Sin esto, el ingeniero tiene que buscar a esos dos en una
-- lista de cuarenta.
--
-- La condicion se guarda contra el CAMPO del diseno, no contra la pregunta: la
-- misma pregunta puede estar dos veces en un formato y son columnas distintas.
--
-- Manda en el SERVIDOR, no en la pantalla: el boton por fila lo pinta el
-- navegador, pero quien decide si una fila puede pedirse es el backend. Si solo
-- viviera en el cliente, bastaria una peticion a mano para saltarselo.
--
-- Aditivo: sin condicion (NULL) se comporta como hasta ahora, todas las filas
-- pueden pedirse.
--
-- APLICADO EN: forms_sfisas @ localhost
-- PENDIENTE EN: prod (forms_sfisas_dev @ 207.246.75.205)
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE form_external_signoff
    ADD COLUMN IF NOT EXISTS row_condition_element_id VARCHAR(100) NULL;

-- Valores que dejan pasar la fila, como arreglo JSON: ["Si"]. Varios valores
-- funcionan como O ("Si" o "Tal vez").
ALTER TABLE form_external_signoff
    ADD COLUMN IF NOT EXISTS row_condition_values TEXT NULL;
