-- ============================================================================
-- DIAGNÓSTICO COMPLETO — Verifica qué cambios recientes están aplicados.
-- Fecha: 2026-05-21
-- 100% SOLO LECTURA. No modifica nada.
--
-- Cómo correr:
--   - pgAdmin / DBeaver: abre este archivo y ejecuta toda la consulta (F5).
--   - psql: \i 2026-05-21_diagnostico_completo.sql
--
-- Salida: tabla con una fila por cada cambio esperado, con estado
--   ✅ OK     → ya está en la BD
--   ❌ FALTA  → todavía no está aplicado, hay que correr la migración
-- ============================================================================

SELECT
    bloque,
    item,
    CASE WHEN existe THEN '✅ OK' ELSE '❌ FALTA' END AS estado,
    migracion
FROM (

    -- ── BLOQUE 1: Firma facial en aprobadores por formato (response_approvals) ──
    -- Migración: firma_facial_aprobaciones_FINAL.sql (2026-05-14)
                 SELECT 1 AS orden, 'Bloque 1: Firma facial en aprobadores' AS bloque,
                        'form_approvals.firm_mode' AS item,
                        EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'form_approvals' AND column_name = 'firm_mode') AS existe,
                        'firma_facial_aprobaciones_FINAL.sql' AS migracion
    UNION ALL SELECT 2, 'Bloque 1: Firma facial en aprobadores',
                     'CHECK form_approvals_firm_mode_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_approvals_firm_mode_check'),
                     'firma_facial_aprobaciones_FINAL.sql'
    UNION ALL SELECT 3, 'Bloque 1: Firma facial en aprobadores',
                     'response_approvals.firm_mode',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'response_approvals' AND column_name = 'firm_mode'),
                     'firma_facial_aprobaciones_FINAL.sql'
    UNION ALL SELECT 4, 'Bloque 1: Firma facial en aprobadores',
                     'CHECK response_approvals_firm_mode_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'response_approvals_firm_mode_check'),
                     'firma_facial_aprobaciones_FINAL.sql'
    UNION ALL SELECT 5, 'Bloque 1: Firma facial en aprobadores',
                     'response_approvals.firm_answer_id',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'response_approvals' AND column_name = 'firm_answer_id'),
                     'firma_facial_aprobaciones_FINAL.sql'
    UNION ALL SELECT 6, 'Bloque 1: Firma facial en aprobadores',
                     'Índice idx_response_approvals_firm_answer',
                     EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_response_approvals_firm_answer'),
                     'firma_facial_aprobaciones_FINAL.sql'

    -- ── BLOQUE 2: Pregunta regisfacial fuente en aprobadores ──────────────
    -- Migración: firma_facial_source_question.sql (2026-05-14)
    UNION ALL SELECT 10, 'Bloque 2: Pregunta regisfacial fuente',
                     'form_approvals.firm_source_question_id',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'form_approvals' AND column_name = 'firm_source_question_id'),
                     'firma_facial_source_question.sql'
    UNION ALL SELECT 11, 'Bloque 2: Pregunta regisfacial fuente',
                     'CHECK form_approvals_firm_source_required_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_approvals_firm_source_required_check'),
                     'firma_facial_source_question.sql'
    UNION ALL SELECT 12, 'Bloque 2: Pregunta regisfacial fuente',
                     'response_approvals.firm_source_question_id',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'response_approvals' AND column_name = 'firm_source_question_id'),
                     'firma_facial_source_question.sql'
    UNION ALL SELECT 13, 'Bloque 2: Pregunta regisfacial fuente',
                     'CHECK response_approvals_firm_source_required_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'response_approvals_firm_source_required_check'),
                     'firma_facial_source_question.sql'
    UNION ALL SELECT 14, 'Bloque 2: Pregunta regisfacial fuente',
                     'Índice idx_response_approvals_firm_source',
                     EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_response_approvals_firm_source'),
                     'firma_facial_source_question.sql'

    -- ── BLOQUE 3: Firma facial + fuente en aprobadores por categoría ──────
    -- Migración: firma_facial_categoria.sql (2026-05-15)
    UNION ALL SELECT 20, 'Bloque 3: Firma facial en aprobadores por categoría',
                     'category_approvals.firm_mode',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'category_approvals' AND column_name = 'firm_mode'),
                     'firma_facial_categoria.sql'
    UNION ALL SELECT 21, 'Bloque 3: Firma facial en aprobadores por categoría',
                     'CHECK category_approvals_firm_mode_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'category_approvals_firm_mode_check'),
                     'firma_facial_categoria.sql'
    UNION ALL SELECT 22, 'Bloque 3: Firma facial en aprobadores por categoría',
                     'category_approvals.firm_source_question_id',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'category_approvals' AND column_name = 'firm_source_question_id'),
                     'firma_facial_categoria.sql'
    UNION ALL SELECT 23, 'Bloque 3: Firma facial en aprobadores por categoría',
                     'CHECK category_approvals_firm_source_required_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'category_approvals_firm_source_required_check'),
                     'firma_facial_categoria.sql'
    UNION ALL SELECT 24, 'Bloque 3: Firma facial en aprobadores por categoría',
                     'Índice idx_category_approvals_firm_source',
                     EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_category_approvals_firm_source'),
                     'firma_facial_categoria.sql'

    -- ── BLOQUE 4: Modo de aprobación en categorías ────────────────────────
    -- Migración: approval_mode_categoria.sql (2026-05-15)
    UNION ALL SELECT 30, 'Bloque 4: Modo de aprobación en categorías',
                     'form_categories.approval_mode',
                     EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'form_categories' AND column_name = 'approval_mode'),
                     'approval_mode_categoria.sql'
    UNION ALL SELECT 31, 'Bloque 4: Modo de aprobación en categorías',
                     'CHECK form_categories_approval_mode_check',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_categories_approval_mode_check'),
                     'approval_mode_categoria.sql'

    -- ── BLOQUE 5: Integraciones de formatos ────────────────────────────────
    -- Migración: 2026-05-20_integrator_format_access.sql (2026-05-20)
    UNION ALL SELECT 40, 'Bloque 5: Integraciones de formatos',
                     'Tabla integrator_format_access',
                     EXISTS (SELECT 1 FROM information_schema.tables
                             WHERE table_name = 'integrator_format_access'),
                     '2026-05-20_integrator_format_access.sql'
    UNION ALL SELECT 41, 'Bloque 5: Integraciones de formatos',
                     'UNIQUE uq_integrator_format',
                     EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_integrator_format'),
                     '2026-05-20_integrator_format_access.sql'
    UNION ALL SELECT 42, 'Bloque 5: Integraciones de formatos',
                     'Índice ix_integrator_format_access_user_id',
                     EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_integrator_format_access_user_id'),
                     '2026-05-20_integrator_format_access.sql'
    UNION ALL SELECT 43, 'Bloque 5: Integraciones de formatos',
                     'Índice ix_integrator_format_access_format_id',
                     EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_integrator_format_access_format_id'),
                     '2026-05-20_integrator_format_access.sql'

) t
ORDER BY orden;
