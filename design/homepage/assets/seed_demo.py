import asyncio
import os
import random
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app")
random.seed(20260823)

from sqlalchemy import select, func, delete

from app.core.db_engine import Base, engine
from app.core.db_models import (
    ApiKey, ApiKeyDailyStat, ApiKeyModelAccess, Model, ModelDailyStat,
    Provider, ProviderDailyStat, ProviderModel, RequestLog, User,
)

TZ = None
NOW = datetime.now().replace(microsecond=0)

PROVIDERS = [
    ("deepseek",     "https://api.deepseek.com/v1"),
    ("moonshot",     "https://api.moonshot.cn/v1"),
    ("zhipu",        "https://open.bigmodel.cn/api/paas/v4"),
    ("minimax",      "https://api.minimax.chat/v1"),
    ("qwen",         "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("siliconflow",  "https://api.siliconflow.cn/v1"),
]

MODELS = [
    ("deepseek-chat",         "DeepSeek-V3.2",       "deepseek",     "chat",     False),
    ("deepseek-reasoner",     "DeepSeek-R1",         "deepseek",     "reasoning", False),
    ("kimi-k2-turbo-preview", "Kimi K2 Turbo",       "moonshot",     "chat",     False),
    ("kimi-k2-thinking",      "Kimi K2 Thinking",    "moonshot",     "reasoning", False),
    ("glm-4.7",               "GLM-4.7",             "zhipu",        "chat",     False),
    ("glm-4.7-flash",         "GLM-4.7 Flash",       "zhipu",        "chat",     False),
    ("minimax-m2",            "MiniMax-M2",          "minimax",      "reasoning", False),
    ("qwen3-max",             "Qwen3-Max",           "qwen",         "chat",     True),
    ("qwen3-coder-plus",      "Qwen3 Coder Plus",    "qwen",         "code",     False),
    ("qwen3-vl-plus",         "Qwen3-VL Plus",       "qwen",         "chat",     True),
    ("deepseek-v3.1",         "DeepSeek-V3.1",       "siliconflow",  "chat",     False),
    ("glm-4.6",               "GLM-4.6",             "siliconflow",  "chat",     False),
]

API_KEYS = [
    ("opencode-main",   "dev@leturx.cc"),
    ("opencode-test",   "qa@leturx.cc"),
    ("cherry-studio",   "lin@leturx.cc"),
    ("lobechat",        "wang@leturx.cc"),
    ("cursor-dev",      "zhao@leturx.cc"),
    ("ci-agent",        "ci@leturx.cc"),
    ("mobile-assistant", "chen@leturx.cc"),
    ("report-writer",   "sun@leturx.cc"),
]

USERS = [
    ("dev",  "开发主账号"), ("qa01", "测试账号"), ("linwei", "林巍"),
    ("wangfang", "王芳"), ("zhaolei", "赵磊"), ("chenjia", "陈佳"),
    ("sunliang", "孙亮"), ("liuyun", "刘芸"), ("zhouhao", "周昊"),
]

INTENTS = ["code", "chat", "translate", "summarize", "reasoning", "write", "tool_call"]
USER_AGENTS = [
    "opencode/0.14", "opencode/0.15", "ClaudeCode/1.0", "cherry-studio/2.4",
    "LobeChat/1.60", "cursor/0.52", "python-httpx/0.27", "curl/8.9",
]
CLIENT_IPS = ["10.100.2.21", "10.100.2.33", "10.100.3.14", "192.168.1.23", "172.16.8.45", "10.100.2.148"]


def hour_weight(h):
    w = [2, 1, 1, 1, 1, 2, 4, 7, 10, 12, 13, 12, 10, 11, 12, 13, 12, 10, 8, 7, 6, 5, 4, 3]
    return w[h]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.core.db_engine import async_session_maker as SessionLocal
    async with SessionLocal() as s:
        prov_result = await s.execute(select(Provider))
        providers = {p.name: p for p in prov_result.scalars()}
        for name, base_url in PROVIDERS:
            if name not in providers:
                p = Provider(name=name, base_url=base_url, protocol="openai", is_active=True)
                s.add(p)
                providers[name] = p
        await s.flush()

        model_result = await s.execute(select(Model))
        models = {m.name: m for m in model_result.scalars()}
        for name, display, prov, kind, multimodal in MODELS:
            if name not in models:
                m = Model(
                    name=name, display_name=display,
                    is_multimodal=multimodal, is_active=True,
                    context_length=random.choice([131072, 204800, 262144]),
                    max_tokens=131072, thinking_enabled=(kind == "reasoning"),
                )
                s.add(m)
                models[name] = m
        await s.flush()

        pm_result = await s.execute(select(ProviderModel))
        pms = {(pm.provider_id, pm.model_id): pm for pm in pm_result.scalars()}
        for name, display, prov, kind, multimodal in MODELS:
            pid, mid = providers[prov].id, models[name].id
            if (pid, mid) not in pms:
                pm = ProviderModel(provider_id=pid, model_id=mid, priority=10, is_active=True)
                s.add(pm)
                pms[(pid, mid)] = pm
        await s.flush()

        key_result = await s.execute(select(ApiKey))
        api_keys = list(key_result.scalars())
        existing_key_names = {k.name for k in api_keys}
        for name, email in API_KEYS:
            if name not in existing_key_names:
                k = ApiKey(
                    name=name,
                    key="sk-demo-" + name.replace("-", "") + str(random.randint(10**20, 10**21 - 1)),
                    email=email, is_active=True,
                    last_used_at=NOW - timedelta(minutes=random.randint(1, 120)),
                )
                s.add(k)
                api_keys.append(k)
        await s.flush()
        for k in api_keys:
            for name, display, prov, kind, multimodal in MODELS:
                if random.random() < 0.7:
                    s.merge(ApiKeyModelAccess(api_key_id=k.id, model_id=models[name].id))
        await s.flush()

        user_result = await s.execute(select(User))
        existing_users = {u.username for u in user_result.scalars()}
        for username, fullname in USERS:
            if username not in existing_users:
                u = User(
                    username=username, password_hash="$2b$12$demohashnotloginable0000000000000000000000000000",
                    email=username + "@leturx.cc", full_name=fullname,
                    is_active=True, is_superuser=False,
                    last_login=NOW - timedelta(hours=random.randint(1, 72)) if random.random() < 0.8 else None,
                )
                s.add(u)
        await s.flush()

        for tbl in (ProviderDailyStat, ModelDailyStat, ApiKeyDailyStat):
            await s.execute(delete(tbl))

        DAYS = 60
        today = NOW.replace(hour=0, minute=0, second=0, microsecond=0)

        growth = []
        for d in range(DAYS):
            base = 60 + d * 6
            growth.append(base * random.uniform(0.82, 1.18))

        prov_daily_rows, model_daily_rows, key_daily_rows = [], [], []
        for d in range(DAYS):
            day = today - timedelta(days=DAYS - 1 - d)
            date_str = day.strftime("%Y-%m-%d")

            hourly = {}
            for name, display, prov, kind, multimodal in MODELS:
                share = random.uniform(0.5, 2.2)
                day_tot = dict(requests=0, prompt=0, completion=0, errs=0, rls=0, tos=0)
                for h in range(24):
                    if day.date() == today.date() and h > NOW.hour:
                        break
                    reqs = int(growth[d] * hour_weight(h) * share * random.uniform(0.7, 1.3) / 12)
                    if reqs <= 0:
                        continue
                    prompt = reqs * random.randint(900, 2600)
                    completion = reqs * random.randint(300, 1100)
                    errs = max(0, int(reqs * random.uniform(0.002, 0.03)))
                    rls = max(0, int(reqs * random.uniform(0.001, 0.02)))
                    timeouts = max(0, int(reqs * random.uniform(0.0005, 0.008)))
                    day_tot["requests"] += reqs
                    day_tot["prompt"] += prompt
                    day_tot["completion"] += completion
                    day_tot["errs"] += errs
                    day_tot["rls"] += rls
                    day_tot["tos"] += timeouts
                    slot = hourly.setdefault((prov, h), dict(requests=0, prompt=0, completion=0, errs=0, rls=0, tos=0))
                    slot["requests"] += reqs
                    slot["prompt"] += prompt
                    slot["completion"] += completion
                    slot["errs"] += errs
                    slot["rls"] += rls
                    slot["tos"] += timeouts
                if day_tot["requests"] > 0:
                    model_daily_rows.append(ModelDailyStat(
                        model_name=name, provider_name=prov, date=date_str,
                        requests=day_tot["requests"], tokens=day_tot["prompt"] + day_tot["completion"],
                        prompt_tokens=day_tot["prompt"], completion_tokens=day_tot["completion"],
                        errors=day_tot["errs"], rate_limited=day_tot["rls"], timeouts=day_tot["tos"],
                    ))

            for (pname, h), v in hourly.items():
                prov_daily_rows.append(ProviderDailyStat(
                    provider_name=pname, date=date_str, hour=h,
                    requests=v["requests"], tokens=v["prompt"] + v["completion"],
                    prompt_tokens=v["prompt"], completion_tokens=v["completion"],
                    errors=v["errs"], rate_limited=v["rls"], timeouts=v["tos"],
                ))

            total_day = sum(v["requests"] for (p, h), v in hourly.items() if p == p)
            total_day = sum(v["requests"] for (p, h), v in hourly.items())
            weights = [random.uniform(0.3, 3) for _ in api_keys]
            wsum = sum(weights)
            for k, w in zip(api_keys, weights):
                kreqs = int(total_day * w / wsum)
                if kreqs <= 0:
                    continue
                kp = kreqs * random.randint(900, 2600)
                kc = kreqs * random.randint(300, 1100)
                key_daily_rows.append(ApiKeyDailyStat(
                    api_key_id=k.id, date=date_str, hour=None,
                    requests=kreqs, tokens=kp + kc, prompt_tokens=kp,
                    completion_tokens=kc,
                    errors=max(0, int(kreqs * random.uniform(0.002, 0.03))),
                    rate_limited=max(0, int(kreqs * random.uniform(0.001, 0.02))),
                    timeouts=max(0, int(kreqs * random.uniform(0.0005, 0.008))),
                ))

        s.add_all(prov_daily_rows)
        s.add_all(model_daily_rows)
        s.add_all(key_daily_rows)

        await s.execute(delete(RequestLog).where(RequestLog.created_at >= today.replace(hour=0, minute=0)))

        log_rows = []
        log_id_base = 900000
        n_today = 0
        for h in range(NOW.hour + 1):
            count = int(hour_weight(h) * random.uniform(1.6, 3.2))
            if h == NOW.hour:
                count = random.randint(12, 20)
            for _ in range(count):
                name, display, prov, kind, multimodal = random.choice(MODELS)
                k = random.choice(api_keys)
                minute = random.randint(0, 59) if h < NOW.hour else random.randint(0, max(0, NOW.minute))
                ts = today.replace(hour=h, minute=minute,
                                   second=random.randint(0, 59),
                                   microsecond=random.randint(0, 999999))
                if ts > NOW:
                    ts = NOW - timedelta(seconds=random.randint(5, 300))
                roll = random.random()
                if roll < 0.955:
                    status = "completed"
                    up = down = 200
                    err = None
                elif roll < 0.975:
                    status = "error"
                    up = random.choice([401, 403, 429, 500, 502, 503])
                    down = 502
                    err = random.choice([
                        "Upstream authentication failed",
                        "Upstream rate limited",
                        "Upstream timeout after 30s",
                        "Upstream 5xx: model overloaded",
                    ])
                elif roll < 0.99:
                    status = "rate_limited"
                    up, down = 429, 429
                    err = "Concurrency queue saturated"
                else:
                    status = "timeout"
                    up, down = None, 504
                    err = "Upstream timeout"

                ok = status == "completed"
                pt = random.randint(400, 9000) if ok else 0
                ct = random.randint(100, 4000) if ok else 0
                cached = int(pt * random.uniform(0.1, 0.6)) if ok and random.random() < 0.6 else 0
                routing = {"strategy": random.choice(["health", "priority", "cost"]),
                           "candidates": random.randint(1, 4)} if ok else None
                log_rows.append(RequestLog(
                    id=log_id_base + n_today,
                    api_key_id=k.id,
                    provider_id=providers[prov].id,
                    model=name,
                    requested_model=name if random.random() < 0.8 else "auto",
                    actual_model=name if not ok or random.random() < 0.85 else random.choice(MODELS)[0],
                    response="ok" if ok else None,
                    tokens={"prompt_tokens": pt, "completion_tokens": ct, "cached_tokens": cached} if ok else None,
                    latency_ms=round(random.uniform(420, 18000 if kind == "reasoning" else 9000), 1) if ok else round(random.uniform(9000, 32000), 1),
                    request_context_tokens=pt if ok else None,
                    status=status, upstream_status_code=up, downstream_status_code=down,
                    client_ip=random.choice(CLIENT_IPS),
                    user_agent=random.choice(USER_AGENTS),
                    inbound_protocol=random.choice(["openai", "openai", "openai", "anthropic"]),
                    intent=random.choice(INTENTS) if ok else None,
                    provider_key_label=f"{prov}-key{random.randint(1,3)}",
                    routing_decision=routing,
                    created_at=ts,
                ))
                n_today += 1

        s.add_all(log_rows)
        await s.commit()

        counts = {
            "request_logs_today": len(log_rows),
            "provider_daily_stats": len(prov_daily_rows),
            "model_daily_stats": len(model_daily_rows),
            "api_key_daily_stats": len(key_daily_rows),
            "providers": len(providers),
            "models": len(models),
            "api_keys": len(api_keys),
        }
        print("SEEDED:", counts)


asyncio.run(main())
