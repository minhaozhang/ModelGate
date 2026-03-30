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
    thinking_enabled boolean DEFAULT true,
    thinking_budget integer DEFAULT 8192,
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
-- COMMENTS
--

-- 提供商表
COMMENT ON TABLE public.providers IS 'API提供商';
COMMENT ON COLUMN public.providers.id IS '主键ID';
COMMENT ON COLUMN public.providers.name IS '提供商名称，如zhipu、deepseek';
COMMENT ON COLUMN public.providers.base_url IS 'API基础URL';
COMMENT ON COLUMN public.providers.api_key IS '提供商API密钥';
COMMENT ON COLUMN public.providers.is_active IS '是否启用';
COMMENT ON COLUMN public.providers.created_at IS '创建时间';
COMMENT ON COLUMN public.providers.updated_at IS '更新时间';
COMMENT ON COLUMN public.providers.max_concurrent IS '最大并发数，默认3';
COMMENT ON COLUMN public.providers.merge_consecutive_messages IS '是否合并连续相同角色的消息';

-- 模型表
COMMENT ON TABLE public.models IS '模型信息';
COMMENT ON COLUMN public.models.id IS '主键ID';
COMMENT ON COLUMN public.models.name IS '模型标识，如glm-4';
COMMENT ON COLUMN public.models.display_name IS '显示名称';
COMMENT ON COLUMN public.models.max_tokens IS '最大输出token数';
COMMENT ON COLUMN public.models.context_length IS '上下文窗口长度';
COMMENT ON COLUMN public.models.thinking_enabled IS '是否支持思考模式';
COMMENT ON COLUMN public.models.thinking_budget IS '思考模式预算token数';
COMMENT ON COLUMN public.models.is_multimodal IS '是否支持多模态（图片）';
COMMENT ON COLUMN public.models.is_active IS '是否启用';
COMMENT ON COLUMN public.models.created_at IS '创建时间';
COMMENT ON COLUMN public.models.updated_at IS '更新时间';

-- 提供商-模型关联表
COMMENT ON TABLE public.provider_models IS '提供商与模型的关联关系';
COMMENT ON COLUMN public.provider_models.id IS '主键ID';
COMMENT ON COLUMN public.provider_models.provider_id IS '提供商ID';
COMMENT ON COLUMN public.provider_models.model_id IS '模型ID';
COMMENT ON COLUMN public.provider_models.model_name_override IS '模型名称覆盖，用于指定提供商特定的模型名';
COMMENT ON COLUMN public.provider_models.is_active IS '是否启用';
COMMENT ON COLUMN public.provider_models.created_at IS '创建时间';

-- API密钥表
COMMENT ON TABLE public.api_keys IS 'API密钥';
COMMENT ON COLUMN public.api_keys.id IS '主键ID';
COMMENT ON COLUMN public.api_keys.name IS '密钥名称';
COMMENT ON COLUMN public.api_keys.key IS '密钥值，sk-开头';
COMMENT ON COLUMN public.api_keys.is_active IS '是否启用';
COMMENT ON COLUMN public.api_keys.created_at IS '创建时间';
COMMENT ON COLUMN public.api_keys.updated_at IS '更新时间';

-- API密钥-模型关联表
COMMENT ON TABLE public.api_key_models IS 'API密钥可访问的模型';
COMMENT ON COLUMN public.api_key_models.id IS '主键ID';
COMMENT ON COLUMN public.api_key_models.api_key_id IS 'API密钥ID';
COMMENT ON COLUMN public.api_key_models.provider_model_id IS '提供商-模型关联ID';

-- 请求日志表
COMMENT ON TABLE public.request_logs IS '请求日志';
COMMENT ON COLUMN public.request_logs.id IS '主键ID';
COMMENT ON COLUMN public.request_logs.api_key_id IS 'API密钥ID';
COMMENT ON COLUMN public.request_logs.provider_id IS '提供商ID';
COMMENT ON COLUMN public.request_logs.model IS '模型名称';
COMMENT ON COLUMN public.request_logs.response IS '响应内容（非流式）';
COMMENT ON COLUMN public.request_logs.tokens IS 'token统计，JSON格式：{input, output}';
COMMENT ON COLUMN public.request_logs.latency_ms IS '响应延迟（毫秒）';
COMMENT ON COLUMN public.request_logs.status IS '状态：pending/success/error/timeout';
COMMENT ON COLUMN public.request_logs.error IS '错误信息';
COMMENT ON COLUMN public.request_logs.created_at IS '创建时间';
COMMENT ON COLUMN public.request_logs.updated_at IS '更新时间';

-- 提供商每日统计表
COMMENT ON TABLE public.provider_daily_stats IS '提供商每日/每小时统计';
COMMENT ON COLUMN public.provider_daily_stats.id IS '主键ID';
COMMENT ON COLUMN public.provider_daily_stats.provider_name IS '提供商名称';
COMMENT ON COLUMN public.provider_daily_stats.date IS '日期，格式YYYY-MM-DD';
COMMENT ON COLUMN public.provider_daily_stats.hour IS '小时（0-23），为空表示全天汇总';
COMMENT ON COLUMN public.provider_daily_stats.requests IS '请求数';
COMMENT ON COLUMN public.provider_daily_stats.tokens IS 'token数';
COMMENT ON COLUMN public.provider_daily_stats.errors IS '错误数';

-- 模型每日统计表
COMMENT ON TABLE public.model_daily_stats IS '模型每日统计';
COMMENT ON COLUMN public.model_daily_stats.id IS '主键ID';
COMMENT ON COLUMN public.model_daily_stats.model_name IS '模型名称';
COMMENT ON COLUMN public.model_daily_stats.provider_name IS '提供商名称';
COMMENT ON COLUMN public.model_daily_stats.date IS '日期，格式YYYY-MM-DD';
COMMENT ON COLUMN public.model_daily_stats.requests IS '请求数';
COMMENT ON COLUMN public.model_daily_stats.tokens IS 'token数';
COMMENT ON COLUMN public.model_daily_stats.errors IS '错误数';

-- API密钥每日统计表
COMMENT ON TABLE public.api_key_daily_stats IS 'API密钥每日/每小时统计';
COMMENT ON COLUMN public.api_key_daily_stats.id IS '主键ID';
COMMENT ON COLUMN public.api_key_daily_stats.api_key_id IS 'API密钥ID';
COMMENT ON COLUMN public.api_key_daily_stats.date IS '日期，格式YYYY-MM-DD';
COMMENT ON COLUMN public.api_key_daily_stats.hour IS '小时（0-23），为空表示全天汇总';
COMMENT ON COLUMN public.api_key_daily_stats.requests IS '请求数';
COMMENT ON COLUMN public.api_key_daily_stats.tokens IS 'token数';
COMMENT ON COLUMN public.api_key_daily_stats.errors IS '错误数';

-- 小时统计表（旧版）
COMMENT ON TABLE public.hourly_stats IS '小时统计（旧版，逐步废弃）';
COMMENT ON COLUMN public.hourly_stats.id IS '主键ID';
COMMENT ON COLUMN public.hourly_stats.provider_id IS '提供商ID';
COMMENT ON COLUMN public.hourly_stats.hour_key IS '小时标识，格式YYYY-MM-DD-HH';
COMMENT ON COLUMN public.hourly_stats.requests IS '请求数';
COMMENT ON COLUMN public.hourly_stats.tokens IS 'token数';
COMMENT ON COLUMN public.hourly_stats.errors IS '错误数';

--
-- PostgreSQL database dump complete
--
