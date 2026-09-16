-- =============================================================================
-- Tablas que models.py declara y que nunca tuvieron migracion (2026-09-16)
--
-- ntorres agrego ResponseEditRequest, FormExternalSignoff y ResponseExternalTask
-- a app/models.py, pero la unica migracion versionada de esa tanda es
-- 2026-09-15_solicitudes_edicion_snapshot.sql, que hace un ALTER dando por hecho
-- que la tabla ya existe. En las BD donde nadie corrio create_all las tablas no
-- existen y TODO /edit-requests/* y /external/* responde 500:
--   psycopg2.errors.UndefinedTable: relation "response_edit_requests" does not exist
--
-- DDL copiado tal cual de forms_sfisas_dev (207.246.75.205), que si las tiene.
-- Va entero en una transaccion: si la BD ya tenia las tablas, los ADD CONSTRAINT
-- revientan y el BEGIN/COMMIT revierte todo sin dejar nada a medias.
--
-- APLICADO EN (2026-09-16): dairo_safemetrics, andres_safemetrics,
-- daniel_safemetrics, prueba4_safemetrics, prueba5_safemetrics. Las 4 del
-- Hetzner por app efimera (scripts/migra_app.py + scripts/migra_hetzner/),
-- que es la unica via: ese Postgres no publica puerto. Las 3 tablas estaban
-- FALTA en las 4 y quedaron ok. forms_sfisas_dev ya las tenia.
-- forms_sfisas queda fuera a proposito: api-forms-sfi esta congelada en la
-- v142 del 2026-01-30 y no conoce estos modelos.
--
-- Correrla de nuevo sobre una BD que ya las tiene aborta con
-- "relation ... already exists" y revierte entera. Es lo esperado.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.form_external_signoff (
    id bigint NOT NULL,
    form_id bigint NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    repeater_id character varying(100),
    email_element_id character varying(100) NOT NULL,
    name_element_id character varying(100),
    time_element_id character varying(100) NOT NULL,
    location_element_id character varying(100),
    trigger_mode character varying(20) DEFAULT 'on_demand'::character varying NOT NULL,
    expires_hours integer DEFAULT 12 NOT NULL,
    email_subject character varying(255),
    action_label character varying(80) DEFAULT 'Registrar mi salida'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    row_condition_element_id character varying(100),
    row_condition_values text,
    CONSTRAINT ck_form_external_signoff_expires CHECK (((expires_hours > 0) AND (expires_hours <= 720))),
    CONSTRAINT ck_form_external_signoff_trigger CHECK (((trigger_mode)::text = ANY ((ARRAY['on_demand'::character varying, 'on_submit'::character varying])::text[])))
);

CREATE SEQUENCE IF NOT EXISTS public.form_external_signoff_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.form_external_signoff_id_seq OWNED BY public.form_external_signoff.id;

CREATE TABLE IF NOT EXISTS public.response_edit_requests (
    id bigint NOT NULL,
    response_id bigint NOT NULL,
    form_id bigint NOT NULL,
    requester_id bigint NOT NULL,
    scope character varying(10) DEFAULT 'fields'::character varying NOT NULL,
    fields text,
    requester_message text,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    reviewed_by bigint,
    reviewed_at timestamp with time zone,
    review_message text,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    snapshot text,
    CONSTRAINT ck_response_edit_requests_scope CHECK (((scope)::text = ANY ((ARRAY['all'::character varying, 'fields'::character varying])::text[]))),
    CONSTRAINT ck_response_edit_requests_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'used'::character varying, 'cancelled'::character varying])::text[])))
);

CREATE SEQUENCE IF NOT EXISTS public.response_edit_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.response_edit_requests_id_seq OWNED BY public.response_edit_requests.id;

CREATE TABLE IF NOT EXISTS public.response_external_tasks (
    id bigint NOT NULL,
    response_id bigint NOT NULL,
    form_id bigint NOT NULL,
    repeater_id character varying(100),
    repeater_row_index integer,
    recipient_email character varying(255) NOT NULL,
    recipient_name character varying(255),
    time_element_id character varying(100) NOT NULL,
    time_question_id bigint,
    location_element_id character varying(100),
    location_question_id bigint,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    requested_by_user_id bigint,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    email_sent boolean DEFAULT false NOT NULL,
    confirmed_at timestamp with time zone,
    confirmed_time character varying(20),
    confirmed_location character varying(100),
    location_error character varying(30),
    client_ip character varying(64),
    user_agent text,
    CONSTRAINT ck_response_external_tasks_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'done'::character varying, 'expired'::character varying, 'cancelled'::character varying])::text[])))
);

CREATE SEQUENCE IF NOT EXISTS public.response_external_tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.response_external_tasks_id_seq OWNED BY public.response_external_tasks.id;

ALTER TABLE ONLY public.form_external_signoff ALTER COLUMN id SET DEFAULT nextval('public.form_external_signoff_id_seq'::regclass);

ALTER TABLE ONLY public.response_edit_requests ALTER COLUMN id SET DEFAULT nextval('public.response_edit_requests_id_seq'::regclass);

ALTER TABLE ONLY public.response_external_tasks ALTER COLUMN id SET DEFAULT nextval('public.response_external_tasks_id_seq'::regclass);

ALTER TABLE ONLY public.form_external_signoff
    ADD CONSTRAINT form_external_signoff_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.response_edit_requests
    ADD CONSTRAINT response_edit_requests_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.response_external_tasks
    ADD CONSTRAINT response_external_tasks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.form_external_signoff
    ADD CONSTRAINT uq_form_external_signoff UNIQUE (form_id);

CREATE INDEX IF NOT EXISTS ix_response_edit_requests_requester ON public.response_edit_requests USING btree (requester_id, status);

CREATE INDEX IF NOT EXISTS ix_response_edit_requests_response ON public.response_edit_requests USING btree (response_id);

CREATE INDEX IF NOT EXISTS ix_response_edit_requests_status ON public.response_edit_requests USING btree (status, created_at);

CREATE INDEX IF NOT EXISTS ix_response_external_tasks_response ON public.response_external_tasks USING btree (response_id);

CREATE INDEX IF NOT EXISTS ix_response_external_tasks_status ON public.response_external_tasks USING btree (status, expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_response_edit_requests_viva ON public.response_edit_requests USING btree (response_id, requester_id) WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying])::text[]));

CREATE UNIQUE INDEX IF NOT EXISTS uq_response_external_tasks_pending ON public.response_external_tasks USING btree (response_id, COALESCE(repeater_row_index, '-1'::integer), time_element_id) WHERE ((status)::text = 'pending'::text);

ALTER TABLE ONLY public.form_external_signoff
    ADD CONSTRAINT form_external_signoff_form_id_fkey FOREIGN KEY (form_id) REFERENCES public.forms(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.response_edit_requests
    ADD CONSTRAINT response_edit_requests_form_id_fkey FOREIGN KEY (form_id) REFERENCES public.forms(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.response_edit_requests
    ADD CONSTRAINT response_edit_requests_requester_id_fkey FOREIGN KEY (requester_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.response_edit_requests
    ADD CONSTRAINT response_edit_requests_response_id_fkey FOREIGN KEY (response_id) REFERENCES public.responses(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.response_edit_requests
    ADD CONSTRAINT response_edit_requests_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.response_external_tasks
    ADD CONSTRAINT response_external_tasks_form_id_fkey FOREIGN KEY (form_id) REFERENCES public.forms(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.response_external_tasks
    ADD CONSTRAINT response_external_tasks_location_question_id_fkey FOREIGN KEY (location_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.response_external_tasks
    ADD CONSTRAINT response_external_tasks_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.response_external_tasks
    ADD CONSTRAINT response_external_tasks_response_id_fkey FOREIGN KEY (response_id) REFERENCES public.responses(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.response_external_tasks
    ADD CONSTRAINT response_external_tasks_time_question_id_fkey FOREIGN KEY (time_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

COMMIT;
