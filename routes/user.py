from datetime import datetime, timedelta
from fastapi import APIRouter, Cookie, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from typing import Optional
import secrets

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
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <div class="flex justify-between items-center mb-6">
            <div>
                <h1 class="text-3xl font-bold text-gray-800">API Key Dashboard</h1>
                <p class="text-gray-500">{name}</p>
            </div>
            <div class="flex gap-2">
                <select id="period-select" onchange="loadStats()" class="border rounded px-3 py-2 bg-white text-sm">
                    <option value="day">Today</option>
                    <option value="week">This Week</option>
                    <option value="month">This Month</option>
                </select>
                <button onclick="logout()" class="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600">
                    Logout
                </button>
            </div>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-gray-500 text-sm">Total Requests</div>
                <div id="total-requests" class="text-2xl font-bold text-blue-600">0</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-gray-500 text-sm">Total Tokens</div>
                <div id="total-tokens" class="text-2xl font-bold text-green-600">0</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-gray-500 text-sm">Errors</div>
                <div id="total-errors" class="text-2xl font-bold text-red-600">0</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-gray-500 text-sm">Models Used</div>
                <div id="model-count" class="text-2xl font-bold text-purple-600">0</div>
            </div>
        </div>
        
        <div class="bg-white rounded-lg shadow p-4 mb-6">
            <h2 class="text-lg font-semibold mb-3">Request Trend</h2>
            <div style="height: 250px;">
                <canvas id="trend-chart"></canvas>
            </div>
        </div>
        
        <div class="bg-white rounded-lg shadow p-4">
            <h2 class="text-lg font-semibold mb-3">Model Usage</h2>
            <div id="model-stats" class="space-y-2"></div>
        </div>
    </div>
    
    <script>
        let trendChart = null;
        
        async function loadStats() {{
            const period = document.getElementById('period-select').value;
            const resp = await fetch('/user/api/stats?period=' + period);
            const data = await resp.json();
            
            if (data.error) {{
                window.location.href = '/user/login';
                return;
            }}
            
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
        
        async function logout() {{
            const clearSaved = confirm('Clear saved API Key?\\n\\nOK = Clear and logout\\nCancel = Logout only');
            if (clearSaved) {{
                localStorage.removeItem('user_api_key');
            }}
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

        html = USER_DASHBOARD_HTML.format(name=key.name)
        return HTMLResponse(content=html)
