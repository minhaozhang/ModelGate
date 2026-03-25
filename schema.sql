--
-- PostgreSQL database dump
--

-- Dumped from database version 16.13
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: api_key_daily_stats; Type: TABLE; Schema: public
--

CREATE TABLE public.api_key_daily_stats (
    id integer NOT NULL,
    api_key_id integer NOT NULL,
    date character varying(10) NOT NULL,
    hour integer,
    requests integer,
    tokens integer,
    errors integer
);

--
-- Name: api_key_daily_stats_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.api_key_daily_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.api_key_daily_stats_id_seq OWNED BY public.api_key_daily_stats.id;

--
-- Name: api_key_models; Type: TABLE; Schema: public
--

CREATE TABLE public.api_key_models (
    id integer NOT NULL,
    api_key_id integer NOT NULL,
    provider_model_id integer NOT NULL
);

--
-- Name: api_key_models_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.api_key_models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.api_key_models_id_seq OWNED BY public.api_key_models.id;

--
-- Name: api_keys; Type: TABLE; Schema: public
--

CREATE TABLE public.api_keys (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    key character varying(64) NOT NULL,
    is_active boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);

--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;

--
-- Name: hourly_stats; Type: TABLE; Schema: public
--

CREATE TABLE public.hourly_stats (
    id integer NOT NULL,
    provider_id integer,
    hour_key character varying(20) NOT NULL,
    requests integer,
    tokens integer,
    errors integer
);

--
-- Name: hourly_stats_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.hourly_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.hourly_stats_id_seq OWNED BY public.hourly_stats.id;

--
-- Name: model_daily_stats; Type: TABLE; Schema: public
--

CREATE TABLE public.model_daily_stats (
    id integer NOT NULL,
    model_name character varying(100) NOT NULL,
    provider_name character varying(50),
    date character varying(10) NOT NULL,
    requests integer,
    tokens integer,
    errors integer
);

--
-- Name: model_daily_stats_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.model_daily_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.model_daily_stats_id_seq OWNED BY public.model_daily_stats.id;

--
-- Name: models; Type: TABLE; Schema: public
--

CREATE TABLE public.models (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    display_name character varying(100),
    max_tokens integer,
    context_length integer DEFAULT 131072,
    is_multimodal boolean,
    is_active boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);

--
-- Name: models_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.models_id_seq OWNED BY public.models.id;

--
-- Name: provider_daily_stats; Type: TABLE; Schema: public
--

CREATE TABLE public.provider_daily_stats (
    id integer NOT NULL,
    provider_name character varying(50) NOT NULL,
    date character varying(10) NOT NULL,
    hour integer,
    requests integer,
    tokens integer,
    errors integer
);

--
-- Name: provider_daily_stats_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.provider_daily_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.provider_daily_stats_id_seq OWNED BY public.provider_daily_stats.id;

--
-- Name: provider_models; Type: TABLE; Schema: public
--

CREATE TABLE public.provider_models (
    id integer NOT NULL,
    provider_id integer NOT NULL,
    model_id integer NOT NULL,
    model_name_override character varying(100),
    is_active boolean,
    created_at timestamp without time zone DEFAULT now()
);

--
-- Name: provider_models_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.provider_models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.provider_models_id_seq OWNED BY public.provider_models.id;

--
-- Name: providers; Type: TABLE; Schema: public
--

CREATE TABLE public.providers (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    base_url character varying(255) NOT NULL,
    api_key character varying(255),
    is_active boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    max_concurrent integer DEFAULT 3,
    merge_consecutive_messages boolean DEFAULT false
);

--
-- Name: providers_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.providers_id_seq OWNED BY public.providers.id;

--
-- Name: request_logs; Type: TABLE; Schema: public
--

CREATE TABLE public.request_logs (
    id integer NOT NULL,
    api_key_id integer,
    provider_id integer,
    model character varying(100) NOT NULL,
    response text,
    tokens jsonb,
    latency_ms double precision,
    status character varying(20) NOT NULL,
    error text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);

--
-- Name: request_logs_id_seq; Type: SEQUENCE; Schema: public
--

CREATE SEQUENCE public.request_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.request_logs_id_seq OWNED BY public.request_logs.id;

--
-- DEFAULT VALUES
--

ALTER TABLE ONLY public.api_key_daily_stats ALTER COLUMN id SET DEFAULT nextval('public.api_key_daily_stats_id_seq'::regclass);
ALTER TABLE ONLY public.api_key_models ALTER COLUMN id SET DEFAULT nextval('public.api_key_models_id_seq'::regclass);
ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);
ALTER TABLE ONLY public.hourly_stats ALTER COLUMN id SET DEFAULT nextval('public.hourly_stats_id_seq'::regclass);
ALTER TABLE ONLY public.model_daily_stats ALTER COLUMN id SET DEFAULT nextval('public.model_daily_stats_id_seq'::regclass);
ALTER TABLE ONLY public.models ALTER COLUMN id SET DEFAULT nextval('public.models_id_seq'::regclass);
ALTER TABLE ONLY public.provider_daily_stats ALTER COLUMN id SET DEFAULT nextval('public.provider_daily_stats_id_seq'::regclass);
ALTER TABLE ONLY public.provider_models ALTER COLUMN id SET DEFAULT nextval('public.provider_models_id_seq'::regclass);
ALTER TABLE ONLY public.providers ALTER COLUMN id SET DEFAULT nextval('public.providers_id_seq'::regclass);
ALTER TABLE ONLY public.request_logs ALTER COLUMN id SET DEFAULT nextval('public.request_logs_id_seq'::regclass);

--
-- PRIMARY KEYS
--

ALTER TABLE ONLY public.api_key_daily_stats ADD CONSTRAINT api_key_daily_stats_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.api_key_models ADD CONSTRAINT api_key_models_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.api_keys ADD CONSTRAINT api_keys_key_key UNIQUE (key);
ALTER TABLE ONLY public.api_keys ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.hourly_stats ADD CONSTRAINT hourly_stats_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.model_daily_stats ADD CONSTRAINT model_daily_stats_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.models ADD CONSTRAINT models_name_key UNIQUE (name);
ALTER TABLE ONLY public.models ADD CONSTRAINT models_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.provider_daily_stats ADD CONSTRAINT provider_daily_stats_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.provider_models ADD CONSTRAINT provider_models_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.providers ADD CONSTRAINT providers_name_key UNIQUE (name);
ALTER TABLE ONLY public.providers ADD CONSTRAINT providers_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.request_logs ADD CONSTRAINT request_logs_pkey PRIMARY KEY (id);

--
-- INDEXES
--

CREATE UNIQUE INDEX idx_api_key_model ON public.api_key_models USING btree (api_key_id, provider_model_id);
CREATE INDEX idx_apikey_stats_date ON public.api_key_daily_stats USING btree (date);
CREATE INDEX idx_model_stats_date ON public.model_daily_stats USING btree (date);
CREATE UNIQUE INDEX idx_model_stats_unique ON public.model_daily_stats USING btree (model_name, provider_name, date);
CREATE UNIQUE INDEX idx_provider_model ON public.provider_models USING btree (provider_id, model_id);
CREATE INDEX idx_provider_stats_date ON public.provider_daily_stats USING btree (date);
CREATE INDEX idx_request_logs_api_key_id ON public.request_logs USING btree (api_key_id);
CREATE INDEX idx_request_logs_created_at ON public.request_logs USING btree (created_at);
CREATE INDEX idx_request_logs_provider_id ON public.request_logs USING btree (provider_id);
CREATE INDEX idx_request_logs_status ON public.request_logs USING btree (status);
CREATE INDEX ix_request_logs_created_at ON public.request_logs USING btree (created_at);

--
-- FOREIGN KEYS
--

ALTER TABLE ONLY public.api_key_daily_stats ADD CONSTRAINT api_key_daily_stats_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id);
ALTER TABLE ONLY public.api_key_models ADD CONSTRAINT api_key_models_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id);
ALTER TABLE ONLY public.api_key_models ADD CONSTRAINT api_key_models_provider_model_id_fkey FOREIGN KEY (provider_model_id) REFERENCES public.provider_models(id);
ALTER TABLE ONLY public.provider_models ADD CONSTRAINT provider_models_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.models(id);
ALTER TABLE ONLY public.provider_models ADD CONSTRAINT provider_models_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id);
ALTER TABLE ONLY public.request_logs ADD CONSTRAINT request_logs_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id);

--
-- PostgreSQL database dump complete
--
