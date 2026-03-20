-- API Proxy Database Schema
-- Generated from PostgreSQL database

-- Providers table
CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    api_key VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Models table
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

-- Provider-Model association table
CREATE TABLE provider_models (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    model_name_override VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT idx_provider_model UNIQUE (provider_id, model_id)
);

-- API Keys table
CREATE TABLE api_keys (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    key VARCHAR(64) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- API Key-Model association table (access control)
CREATE TABLE api_key_models (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    provider_model_id INTEGER NOT NULL REFERENCES provider_models(id) ON DELETE CASCADE,
    CONSTRAINT idx_api_key_model UNIQUE (api_key_id, provider_model_id)
);

-- Request logs table
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

-- Hourly stats table
CREATE TABLE hourly_stats (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER,
    hour_key VARCHAR NOT NULL,
    requests INTEGER,
    tokens INTEGER,
    errors INTEGER
);

-- Provider daily stats table
CREATE TABLE provider_daily_stats (
    id SERIAL PRIMARY KEY,
    provider_name VARCHAR NOT NULL,
    date VARCHAR NOT NULL,
    hour INTEGER,
    requests INTEGER,
    tokens INTEGER,
    errors INTEGER
);

-- API Key daily stats table
CREATE TABLE api_key_daily_stats (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    date VARCHAR NOT NULL,
    hour INTEGER,
    requests INTEGER,
    tokens INTEGER,
    errors INTEGER
);

-- Indexes
CREATE INDEX idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX idx_request_logs_api_key_id ON request_logs(api_key_id);
CREATE INDEX idx_api_key_model_api_key ON api_key_models(api_key_id);
