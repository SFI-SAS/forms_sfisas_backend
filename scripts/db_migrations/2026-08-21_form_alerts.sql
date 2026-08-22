-- Feature #55: Avisos emergentes configurables por el disenador
-- Crea las tablas form_alerts y form_alert_confirmations.

BEGIN;

CREATE TABLE IF NOT EXISTS form_alerts (
    id              BIGSERIAL PRIMARY KEY,
    form_id         BIGINT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    trigger_type    VARCHAR(20) NOT NULL,
    display_type    VARCHAR(25) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    message         TEXT NOT NULL,
    target_field_id VARCHAR(100),
    trigger_value   VARCHAR(500),
    threshold_value VARCHAR(50),
    threshold_operator VARCHAR(5),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_trigger_type CHECK (trigger_type IN ('on_open','on_value','on_threshold','before_submit','on_approve')),
    CONSTRAINT chk_display_type CHECK (display_type IN ('informative','warning','blocking','confirmation_required')),
    CONSTRAINT chk_threshold_op CHECK (threshold_operator IS NULL OR threshold_operator IN ('>','<','>=','<=','==','!='))
);

CREATE INDEX IF NOT EXISTS idx_form_alerts_form_id ON form_alerts(form_id);

CREATE TABLE IF NOT EXISTS form_alert_confirmations (
    id              BIGSERIAL PRIMARY KEY,
    alert_id        BIGINT NOT NULL REFERENCES form_alerts(id) ON DELETE CASCADE,
    response_id     BIGINT REFERENCES responses(id) ON DELETE CASCADE,
    user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    user_name       VARCHAR(255) NOT NULL,
    user_email      VARCHAR(255),
    confirmed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_form_alert_confirmations_alert_id ON form_alert_confirmations(alert_id);
CREATE INDEX IF NOT EXISTS idx_form_alert_confirmations_response_id ON form_alert_confirmations(response_id);

COMMIT;
