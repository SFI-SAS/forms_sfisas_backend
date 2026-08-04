-- Campo lista alimentado por el USUARIO LOGUEADO.
--
-- Cuando una pregunta tipo lista se relaciona con la tabla `users`, hasta ahora
-- solo podía listar el campo elegido de TODOS los usuarios. Con esta columna la
-- relación puede marcarse como "usuario logueado": el campo no despliega nada,
-- se rellena con el dato de quien está diligenciando.
--
-- Valores admitidos (NULL = comportamiento de siempre, listar a todos):
--   full_name        nombre completo, tal cual está en users.name
--   first_names      solo el/los nombres de pila
--   first_surname    solo el primer apellido
--   second_surname   solo el segundo apellido
--   num_document     documento
--   email            correo
--
-- El nombre se guarda entero en users.name, así que la separación en nombres y
-- apellidos se hace partiendo por espacios en el frontend. Con 3 palabras se
-- asume 1 nombre + 2 apellidos (decisión del usuario, 2026-08-04).
--
-- APLICADA SOLO EN LOCAL (forms_sfisas @ localhost). Para producción hace falta
-- autorización explícita y correrla a mano.

ALTER TABLE question_table_relations
    ADD COLUMN IF NOT EXISTS logged_user_part VARCHAR(30);

COMMENT ON COLUMN question_table_relations.logged_user_part IS
    'Si no es NULL, el campo se rellena con este dato del usuario logueado en vez de listar a todos los usuarios.';
