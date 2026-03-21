from datetime import datetime, timedelta
from fastapi import APIRouter, Cookie, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from typing import Optional
import secrets
import os

from database import async_session_maker, ApiKey, RequestLog
from config import logger

router = APIRouter(tags=["user"])

USER_SESSIONS: dict[str, dict] = {}
USER_SESSION_EXPIRE_HOURS = 24


USER_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>User Login - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center">
    <div class="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 class="text-2xl font-bold text-gray-800 mb-6 text-center">API Key Login</h1>
        
        <form id="login-form" class="space-y-4">
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
                <input type="password" id="api-key" required
                    class="w-full border rounded px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="sk-...">
            </div>
            <div class="flex items-center">
                <input type="checkbox" id="remember" class="mr-2" checked>
                <label for="remember" class="text-sm text-gray-600">Remember API Key</label>
            </div>
            <div id="error-msg" class="text-red-500 text-sm hidden"></div>
            <button type="submit" id="login-btn" class="w-full bg-blue-500 text-white py-2 rounded hover:bg-blue-600">
                Login
            </button>
        </form>
        
        <p class="text-gray-500 text-sm text-center mt-4">
            Enter your API Key to view usage statistics
        </p>
    </div>
    
    <script>
        const STORAGE_KEY = 'user_api_key';
        const errorMsg = document.getElementById('error-msg');
        const loginBtn = document.getElementById('login-btn');
        
        async function tryAutoLogin(apiKey) {
            loginBtn.textContent = 'Logging in...';
            loginBtn.disabled = true;
            try {
                const resp = await fetch('/user/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key: apiKey})
                });
                if (resp.ok) {
                    window.location.href = '/user/dashboard';
                    return true;
                } else {
                    localStorage.removeItem(STORAGE_KEY);
                }
            } catch (err) {
                console.error('Auto login failed:', err);
            }
            loginBtn.textContent = 'Login';
            loginBtn.disabled = false;
            return false;
        }
        
        (async function() {
            const savedKey = localStorage.getItem(STORAGE_KEY);
            if (savedKey) {
                document.getElementById('api-key').value = savedKey;
                await tryAutoLogin(savedKey);
            }
        })();
        
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const apiKey = document.getElementById('api-key').value;
            const remember = document.getElementById('remember').checked;
            errorMsg.classList.add('hidden');
            
            loginBtn.textContent = 'Logging in...';
            loginBtn.disabled = true;
            
            try {
                const resp = await fetch('/user/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key: apiKey})
                });
                const data = await resp.json();
                
                if (resp.ok) {
                    if (remember) {
                        localStorage.setItem(STORAGE_KEY, apiKey);
                    } else {
                        localStorage.removeItem(STORAGE_KEY);
                    }
                    window.location.href = '/user/dashboard';
                } else {
                    errorMsg.textContent = data.error || 'Login failed';
                    errorMsg.classList.remove('hidden');
                    loginBtn.textContent = 'Login';
                    loginBtn.disabled = false;
                }
            } catch (err) {
                errorMsg.textContent = 'Network error';
                errorMsg.classList.remove('hidden');
                loginBtn.textContent = 'Login';
                loginBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""


USER_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Dashboard - {name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .tab-btn.active {{ border-bottom: 2px solid #3b82f6; color: #3b82f6; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        pre {{ background: #1e293b; color: #e2e8f0; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; }}
        code {{ font-family: 'Monaco', 'Menlo', monospace; font-size: 0.875rem; }}
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <div class="flex justify-between items-center mb-6">
            <div>
                <h1 class="text-3xl font-bold text-gray-800">API Key Dashboard</h1>
                <p class="text-gray-500">{name}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="logout()" class="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600">
                    Logout
                </button>
            </div>
        </div>
        
        <div class="bg-white rounded-lg shadow mb-6">
            <div class="flex border-b">
                <button class="tab-btn active px-6 py-3 font-medium" onclick="showTab('stats')">Statistics</button>
                <button class="tab-btn px-6 py-3 font-medium" onclick="showTab('opencode')">OpenCode Config</button>
                <button class="tab-btn px-6 py-3 font-medium" onclick="showTab('usage')">Usage Guide</button>
            </div>
            
            <!-- Stats Tab -->
            <div id="tab-stats" class="tab-content active p-6">
                <div class="flex justify-end mb-4">
                    <select id="period-select" onchange="loadStats()" class="border rounded px-3 py-2 text-sm">
                        <option value="day">Today</option>
                        <option value="week">This Week</option>
                        <option value="month">This Month</option>
                    </select>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Total Requests</div>
                        <div id="total-requests" class="text-2xl font-bold text-blue-600">0</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Total Tokens</div>
                        <div id="total-tokens" class="text-2xl font-bold text-green-600">0</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Errors</div>
                        <div id="total-errors" class="text-2xl font-bold text-red-600">0</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Models Used</div>
                        <div id="model-count" class="text-2xl font-bold text-purple-600">0</div>
                    </div>
                </div>
                
                <div class="mb-6" style="height: 250px;">
                    <canvas id="trend-chart"></canvas>
                </div>
                
                <div>
                    <h3 class="text-lg font-semibold mb-3">Model Usage</h3>
                    <div id="model-stats" class="space-y-2"></div>
                </div>
            </div>
            
            <!-- OpenCode Config Tab -->
            <div id="tab-opencode" class="tab-content p-6">
                <h2 class="text-xl font-bold mb-4">OpenCode Configuration</h2>
                <p class="text-gray-600 mb-4">Generate opencode.json config for this proxy</p>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-2">opencode.json</h3>
                    <div class="relative">
                        <button onclick="copyConfig()" class="absolute top-2 right-2 bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">Copy</button>
                        <pre id="config-output" class="text-sm"></pre>
                    </div>
                </div>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-3">Available Models</h3>
                    <div id="models-list" class="space-y-2 max-h-64 overflow-y-auto"></div>
                </div>
                
                <div class="bg-blue-50 rounded-lg p-4">
                    <h3 class="font-semibold text-blue-800 mb-2">How to use</h3>
                    <ol class="list-decimal list-inside text-sm text-blue-700 space-y-1">
                        <li>Copy the generated <code class="bg-blue-100 px-1 rounded">opencode.json</code></li>
                        <li>Create <code class="bg-blue-100 px-1 rounded">opencode.json</code> in your project root</li>
                        <li>Paste the configuration and save</li>
                        <li>OpenCode will now use this proxy for API requests</li>
                    </ol>
                </div>
            </div>
            
            <!-- Usage Tab -->
            <div id="tab-usage" class="tab-content p-6">
                <h2 class="text-xl font-bold mb-4">How to Configure API Clients</h2>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-3">Basic Information</h3>
                    <div class="space-y-2 text-sm">
                        <div class="flex"><span class="text-gray-500 w-32">Proxy URL:</span><code class="bg-white px-2 py-1 rounded" id="proxy-url"></code></div>
                        <div class="flex"><span class="text-gray-500 w-32">API Endpoint:</span><code class="bg-white px-2 py-1 rounded">/v1/chat/completions</code></div>
                        <div class="flex"><span class="text-gray-500 w-32">Auth Header:</span><code class="bg-white px-2 py-1 rounded">Authorization: Bearer YOUR_API_KEY</code></div>
                    </div>
                </div>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-3">Model Name Format</h3>
                    <p class="text-gray-600 text-sm mb-3">Use <code class="bg-white px-2 py-1 rounded">provider/model</code> format:</p>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="bg-white p-3 rounded"><div class="text-xs text-gray-500 mb-1">With Provider</div><code class="text-sm">zhipu/glm-4</code></div>
                        <div class="bg-white p-3 rounded"><div class="text-xs text-gray-500 mb-1">Without Prefix</div><code class="text-sm">glm-4</code></div>
                    </div>
                </div>
                
                <div class="space-y-4">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <h3 class="font-semibold mb-3 flex items-center">
                            <span class="w-5 h-5 mr-2 bg-green-500 text-white rounded text-xs flex items-center justify-center">Py</span>
                            Python (OpenAI SDK)
                        </h3>
                        <div class="relative">
                            <button onclick="copyCode('python')" class="absolute top-2 right-2 bg-gray-700 text-white px-2 py-1 rounded text-xs">Copy</button>
                            <pre id="code-python"><code>from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY",
    base_url="<span id="base-python"></span>"
)

response = client.chat.completions.create(
    model="zhipu/glm-4",
    messages=[{{"role": "user", "content": "Hello!"}}]
)
print(response.choices[0].message.content)</code></pre>
                        </div>
                    </div>
                    
                    <div class="bg-gray-50 rounded-lg p-4">
                        <h3 class="font-semibold mb-3 flex items-center">
                            <span class="w-5 h-5 mr-2 bg-yellow-500 text-white rounded text-xs flex items-center justify-center">JS</span>
                            JavaScript
                        </h3>
                        <div class="relative">
                            <button onclick="copyCode('js')" class="absolute top-2 right-2 bg-gray-700 text-white px-2 py-1 rounded text-xs">Copy</button>
                            <pre id="code-js"><code>const response = await fetch('<span id="base-js"></span>/chat/completions', {{
  method: 'POST',
  headers: {{
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_API_KEY'
  }},
  body: JSON.stringify({{
    model: 'zhipu/glm-4',
    messages: [{{ role: 'user', content: 'Hello!' }}]
  }})
}});
const data = await response.json();</code></pre>
                        </div>
                    </div>
                    
                    <div class="bg-gray-50 rounded-lg p-4">
                        <h3 class="font-semibold mb-3 flex items-center">
                            <span class="w-5 h-5 mr-2 bg-blue-500 text-white rounded text-xs flex items-center justify-center">$</span>
                            cURL
                        </h3>
                        <div class="relative">
                            <button onclick="copyCode('curl')" class="absolute top-2 right-2 bg-gray-700 text-white px-2 py-1 rounded text-xs">Copy</button>
                            <pre id="code-curl"><code>curl <span id="base-curl"></span>/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{{"model": "zhipu/glm-4", "messages": [{{"role": "user", "content": "Hello!"}}]}}'</code></pre>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const apiKeyId = {api_key_id};
        const baseUrl = window.location.origin + '/v1';
        let trendChart = null;
        
        document.getElementById('proxy-url').textContent = baseUrl;
        document.getElementById('base-python').textContent = baseUrl;
        document.getElementById('base-js').textContent = baseUrl;
        document.getElementById('base-curl').textContent = baseUrl;
        
        function showTab(tab) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
            
            if (tab === 'opencode') loadOpenCodeConfig();
        }}
        
        async function loadStats() {{
            const period = document.getElementById('period-select').value;
            const resp = await fetch('/user/api/stats?period=' + period);
            const data = await resp.json();
            
            if (data.error) {{ window.location.href = '/user/login'; return; }}
            
            document.getElementById('total-requests').textContent = data.total_requests.toLocaleString();
            document.getElementById('total-tokens').textContent = data.total_tokens.toLocaleString();
            document.getElementById('total-errors').textContent = data.total_errors;
            document.getElementById('model-count').textContent = Object.keys(data.models || {{}}).length;
            
            const modelHtml = Object.entries(data.models || {{}}).map(([name, m]) => `
                <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                    <span class="font-medium text-sm">${{name}}</span>
                    <span class="text-sm text-gray-600">${{m.requests}} req / ${{m.tokens.toLocaleString()}} tokens</span>
                </div>
            `).join('');
            document.getElementById('model-stats').innerHTML = modelHtml || '<div class="text-gray-400">No data</div>';
            
            renderTrendChart(data.trend || {{}});
        }}
        
        function renderTrendChart(trendData) {{
            const ctx = document.getElementById('trend-chart').getContext('2d');
            if (trendChart) trendChart.destroy();
            
            const labels = Object.keys(trendData);
            const requests = labels.map(l => trendData[l].requests || 0);
            const tokens = labels.map(l => Math.floor((trendData[l].tokens || 0) / 1000));
            
            trendChart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [
                        {{ label: 'Requests', data: requests, backgroundColor: '#3b82f6', borderRadius: 4 }},
                        {{ label: 'Tokens (K)', data: tokens, backgroundColor: '#10b981', borderRadius: 4 }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{ y: {{ beginAtZero: true }} }},
                    plugins: {{ legend: {{ position: 'top' }} }}
                }}
            }});
        }}
        
        async function loadOpenCodeConfig() {{
            try {{
                const resp = await fetch('/user/api/opencode-config');
                const data = await resp.json();
                
                if (data.error) return;
                
                document.getElementById('config-output').textContent = JSON.stringify(data.config, null, 2);
                
                const modelsHtml = data.models.map(m => `
                    <div class="flex justify-between items-center p-2 bg-white rounded">
                        <span class="font-medium text-sm">${{m.name}}</span>
                        <span class="text-xs text-gray-500">ctx: ${{m.context.toLocaleString()}} | out: ${{m.output.toLocaleString()}}</span>
                    </div>
                `).join('');
                document.getElementById('models-list').innerHTML = modelsHtml || '<div class="text-gray-400">No models</div>';
            }} catch (e) {{
                console.error('Failed to load OpenCode config:', e);
            }}
        }}
        
        function copyConfig() {{
            const config = document.getElementById('config-output').textContent;
            navigator.clipboard.writeText(config).then(() => alert('Copied!'));
        }}
        
        function copyCode(type) {{
            const el = document.getElementById('code-' + type);
            navigator.clipboard.writeText(el.textContent).then(() => alert('Copied!'));
        }}
        
        async function logout() {{
            const clearSaved = confirm('Clear saved API Key?');
            if (clearSaved) localStorage.removeItem('user_api_key');
            await fetch('/user/api/logout', {{method: 'POST'}});
            window.location.href = '/user/login';
        }}
        
        loadStats();
        setInterval(loadStats, 30000);
    </script>
</body>
</html>
"""


class UserLoginRequest(BaseModel):
    api_key: str


def get_user_session(user_session: Optional[str] = Cookie(None)) -> Optional[int]:
    if not user_session:
        return None
    session_data = USER_SESSIONS.get(user_session)
    if not session_data:
        return None
    if datetime.now() > session_data["expires"]:
        del USER_SESSIONS[user_session]
        return None
    return session_data.get("api_key_id")


@router.get("/user/login", response_class=HTMLResponse)
async def user_login_page():
    return HTMLResponse(content=USER_LOGIN_HTML)


@router.post("/user/api/login")
async def user_login(data: UserLoginRequest, response: Response):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == data.api_key, ApiKey.is_active == True)
        )
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)

        import secrets

        session_token = secrets.token_hex(32)
        USER_SESSIONS[session_token] = {
            "api_key_id": key.id,
            "name": key.name,
            "expires": datetime.now() + timedelta(hours=USER_SESSION_EXPIRE_HOURS),
        }

        response.set_cookie(
            key="user_session",
            value=session_token,
            httponly=True,
            max_age=USER_SESSION_EXPIRE_HOURS * 3600,
        )
        logger.info(f"[USER LOGIN] API Key '{key.name}' logged in")
        return {"success": True, "name": key.name}


@router.post("/user/api/logout")
async def user_logout(response: Response, user_session: Optional[str] = Cookie(None)):
    if user_session and user_session in USER_SESSIONS:
        del USER_SESSIONS[user_session]
    response.delete_cookie("user_session")
    return {"success": True}


@router.get("/user/api/stats")
async def get_user_stats(
    api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from datetime import datetime, timedelta

    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [
            ((start + timedelta(hours=i)).strftime("%H:00")) for i in range(24)
        ]
        format_func = lambda d: d.strftime("%H:00")
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [((start + timedelta(days=i)).strftime("%m/%d")) for i in range(7)]
        format_func = lambda d: d.strftime("%m/%d")
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = (
            now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)
        ).day
        intervals = [
            ((start + timedelta(days=i)).strftime("%m/%d"))
            for i in range(days_in_month)
        ]
        format_func = lambda d: d.strftime("%m/%d")

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)

        total_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer())).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.status == "error",
                RequestLog.created_at >= start,
            )
        )
        total_errors = errors_result.scalar() or 0

        model_stats_result = await session.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("count"),
                func.sum(RequestLog.tokens["total_tokens"].as_integer()).label(
                    "tokens"
                ),
            )
            .where(RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start)
            .group_by(RequestLog.model)
        )
        model_stats_rows = model_stats_result.fetchall()
        model_stats = {
            row.model: {"requests": row.count, "tokens": row.tokens or 0}
            for row in model_stats_rows
        }

        trend_query = select(RequestLog).where(
            RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
        )
        trend_result = await session.execute(trend_query)
        trend_logs = trend_result.scalars().all()

        trend_data = {label: {"requests": 0, "tokens": 0} for label in intervals}
        for log in trend_logs:
            label = format_func(log.created_at)
            if label in trend_data:
                trend_data[label]["requests"] += 1
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                trend_data[label]["tokens"] += tokens

        return {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "models": model_stats,
            "trend": trend_data,
        }


@router.get("/user/dashboard", response_class=HTMLResponse)
async def user_dashboard(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return RedirectResponse(url="/user/login")

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return RedirectResponse(url="/user/login")

        html = USER_DASHBOARD_HTML.format(name=key.name, api_key_id=api_key_id)
        return HTMLResponse(content=html)


@router.get("/user/api/opencode-config")
async def get_user_opencode_config(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from database import Provider, Model, ProviderModel

    async with async_session_maker() as session:
        pm_result = await session.execute(
            select(ProviderModel).where(ProviderModel.is_active == True)
        )
        provider_models = pm_result.scalars().all()

        models_data = []
        models_config = {}

        for pm in provider_models:
            provider_result = await session.execute(
                select(Provider).where(Provider.id == pm.provider_id)
            )
            provider = provider_result.scalar_one_or_none()
            if not provider:
                continue

            model_result = await session.execute(
                select(Model).where(Model.id == pm.model_id)
            )
            model = model_result.scalar_one_or_none()
            if not model:
                continue

            model_key = f"{provider.name}/{model.name}"
            display_name = model.display_name or model.name

            max_output = model.max_tokens or 16384
            context_window = max_output * 8

            models_config[model_key] = {
                "name": f"{provider.name}/{display_name}",
                "modalities": {"input": ["text"], "output": ["text"]},
                "options": {"thinking": {"type": "enabled", "budgetTokens": 8192}},
                "limit": {"context": context_window, "output": max_output},
            }

            models_data.append(
                {"name": model_key, "context": context_window, "output": max_output}
            )

        config = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                "proxy-coding-plan": {
                    "name": "API Proxy",
                    "options": {
                        "baseURL": f"{os.getenv('PUBLIC_URL', 'http://127.0.0.1:8765')}/v1",
                        "apiKey": "YOUR-API-KEY",
                    },
                    "models": models_config,
                }
            },
        }

        return {"config": config, "models": models_data}
