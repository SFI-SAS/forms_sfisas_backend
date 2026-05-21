-- ============================================================================
-- DIAGNÓSTICO — Verifica qué cambios de la sesión actual están aplicados
-- en la BD donde se ejecute. SOLO LECTURA, no modifica nada.
--
-- Cómo correr:
--   psql -h <HOST> -U <USER> -d <DB> -f _diagnostico_remoto.sql
--
-- Salida: una tabla con una fila por cada cambio esperado y "OK" o "FALTA".
-- ============================================================================

SELECT
    bloque,
    item,
    CASE WHEN existe THEN '✅ OK' ELSE '❌ FALTA' END AS estado
FROM (
    -- ── BLOQUE 1: Firma facial en aprobadores por formato ─────────────────
    SELECT 1 AS orden, 'Bloque 1' AS bloque, 'form_approvals.firm_mode' AS item,
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'form_approvals' AND column_name = 'firm_mode') AS existe
    UNION ALL SELECT 2, 'Bloque 1', 'CHECK form_approvals_firm_mode_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_approvals_firm_mode_check')
    UNION ALL SELECT 3, 'Bloque 1', 'response_approvals.firm_mode',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'response_approvals' AND column_name = 'firm_mode')
    UNION ALL SELECT 4, 'Bloque 1', 'CHECK response_approvals_firm_mode_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'response_approvals_firm_mode_check')
    UNION ALL SELECT 5, 'Bloque 1', 'response_approvals.firm_answer_id',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'response_approvals' AND column_name = 'firm_answer_id')
    UNION ALL SELECT 6, 'Bloque 1', 'Índice idx_response_approvals_firm_answer',
           EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_response_approvals_firm_answer')

    -- ── BLOQUE 2: Pregunta regisfacial fuente en aprobadores por formato ──
    UNION ALL SELECT 10, 'Bloque 2', 'form_approvals.firm_source_question_id',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'form_approvals' AND column_name = 'firm_source_question_id')
    UNION ALL SELECT 11, 'Bloque 2', 'CHECK form_approvals_firm_source_required_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_approvals_firm_source_required_check')
    UNION ALL SELECT 12, 'Bloque 2', 'response_approvals.firm_source_question_id',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'response_approvals' AND column_name = 'firm_source_question_id')
    UNION ALL SELECT 13, 'Bloque 2', 'CHECK response_approvals_firm_source_required_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'response_approvals_firm_source_required_check')
    UNION ALL SELECT 14, 'Bloque 2', 'Índice idx_response_approvals_firm_source',
           EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_response_approvals_firm_source')

    -- ── BLOQUE 3: Firma facial + fuente en aprobadores por categoría ──────
    UNION ALL SELECT 20, 'Bloque 3', 'category_approvals.firm_mode',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'category_approvals' AND column_name = 'firm_mode')
    UNION ALL SELECT 21, 'Bloque 3', 'CHECK category_approvals_firm_mode_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'category_approvals_firm_mode_check')
    UNION ALL SELECT 22, 'Bloque 3', 'category_approvals.firm_source_question_id',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'category_approvals' AND column_name = 'firm_source_question_id')
    UNION ALL SELECT 23, 'Bloque 3', 'CHECK category_approvals_firm_source_required_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'category_approvals_firm_source_required_check')
    UNION ALL SELECT 24, 'Bloque 3', 'Índice idx_category_approvals_firm_source',
           EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_category_approvals_firm_source')

    -- ── BLOQUE 4: Modo de aprobación en categorías ────────────────────────
    UNION ALL SELECT 30, 'Bloque 4', 'form_categories.approval_mode',
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'form_categories' AND column_name = 'approval_mode')
    UNION ALL SELECT 31, 'Bloque 4', 'CHECK form_categories_approval_mode_check',
           EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'form_categories_approval_mode_check')
) t
ORDER BY orden;
