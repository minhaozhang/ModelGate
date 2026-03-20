-- API Proxy Database Schema
-- PostgreSQL 初始化脚本

-- Providers 表
CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    api_key VARCHAR(255),
    max_concurrent INTEGER DEFAULT 3,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Models 表
CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    max_tokens INTEGER DEFAULT 16384,
    is_multimodal BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Provider-Model 关联表
CREATE TABLE provider_models (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    model_name_override VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT idx_provider_model UNIQUE (provider_id, model_id)
);

-- API Keys 表
CREATE TABLE api_keys (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    key VARCHAR(64) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- API Key-Model 关联表 (访问控制)
CREATE TABLE api_key_models (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    provider_model_id INTEGER NOT NULL REFERENCES provider_models(id) ON DELETE CASCADE,
    CONSTRAINT idx_api_key_model UNIQUE (api_key_id, provider_model_id)
);

-- Request logs 表
CREATE TABLE request_logs (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER REFERENCES api_keys(id),
    provider_id INTEGER,
    model VARCHAR(100) NOT NULL,
    messages JSONB,
    response TEXT,
    tokens JSONB,
    latency_ms FLOAT,
    status VARCHAR(20) NOT NULL,
    error TEXT,
    headers JSONB,
    request_body JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Provider 每日统计表
CREATE TABLE provider_daily_stats (
    id SERIAL PRIMARY KEY,
    provider_name VARCHAR(50) NOT NULL,
    date VARCHAR(10) NOT NULL,
    hour INTEGER,
    requests INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0
);

-- API Key 每日统计表
CREATE TABLE api_key_daily_stats (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    date VARCHAR(10) NOT NULL,
    hour INTEGER,
    requests INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0
);

-- Model 每日统计表
CREATE TABLE model_daily_stats (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,
    provider_name VARCHAR(50),
    date VARCHAR(10) NOT NULL,
    requests INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    CONSTRAINT idx_model_stats_unique UNIQUE (model_name, provider_name, date)
);

-- 索引
CREATE INDEX idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX idx_request_logs_api_key_id ON request_logs(api_key_id);
CREATE INDEX idx_provider_stats_date ON provider_daily_stats(date);
CREATE INDEX idx_apikey_stats_date ON api_key_daily_stats(date);
CREATE INDEX idx_model_stats_date ON model_daily_stats(date);
