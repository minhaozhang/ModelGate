from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from core.database import async_session_maker, ApiKey
from core.i18n import render
from routes.user import get_user_session

router = APIRouter(tags=["query"])

QUERY_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>API Key Usage - {name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .fade-in {{ animation: fadeIn 0.3s; }}
        @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-2">API Key Usage</h1>
        <p class="text-gray-500 mb-6">{name}</p>
        
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
            <h2 class="text-lg font-semibold mb-3">Model Usage</h2>
            <div id="model-stats" class="space-y-2"></div>
        </div>
        
        <div class="bg-white rounded-lg shadow p-4">
            <div class="flex justify-between items-center mb-3">
                <h2 class="text-lg font-semibold">Recent Requests</h2>
                <button onclick="loadLogs()" class="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">Refresh</button>
            </div>
            <div id="logs" class="space-y-2 max-h-96 overflow-y-auto"></div>
        </div>
    </div>
    
    <script>
        const keyId = {key_id};

        async function fetchJsonOrRedirect(url, options) {{
            const resp = await fetch(url, options);
            if (resp.status === 401) {{
                window.location.href = '/user/login';
                throw new Error('Unauthorized');
            }}
            return await resp.json();
        }}
        
        async function loadStats() {{
            const data = await fetchJsonOrRedirect('/api-keys/' + keyId + '/stats');
            
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
        }}
        
        async function loadLogs() {{
            const data = await fetchJsonOrRedirect('/api-keys/' + keyId + '/logs?limit=50');
            
            const logsHtml = (data.logs || []).map(log => {{
                const statusClass = log.status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';
                const tokens = log.tokens?.total_tokens || log.tokens?.estimated || 0;
                return `
                <div class="border rounded p-3 fade-in">
                    <div class="flex justify-between items-start">
                        <div class="flex items-center gap-2">
                            <span class="px-2 py-0.5 rounded text-xs ${{statusClass}}">${{log.status}}</span>
                            <span class="font-medium">${{log.model}}</span>
                        </div>
                        <div class="text-right text-sm text-gray-500">
                            ${{log.created_at}} | ${{log.latency_ms}}ms | ${{tokens}} tokens
                        </div>
                    </div>
                </div>`;
            }}).join('');
            document.getElementById('logs').innerHTML = logsHtml || '<div class="text-gray-400 text-center py-4">No logs</div>';
        }}
        
        loadStats();
        loadLogs();
        setInterval(loadStats, 10000);
    </script>
</body>
</html>
"""


@router.get("/api-keys/{key_id}/query", response_class=HTMLResponse)
async def api_key_query_page(
    request: Request, key_id: int, user_api_key_id: int = Depends(get_user_session)
):
    if not user_api_key_id:
        return RedirectResponse(url="/user/login", status_code=302)

    if user_api_key_id != key_id:
        return HTMLResponse(
            "<h1>Access Denied</h1><p>You can only view your own API key stats.</p>",
            status_code=403,
        )

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return HTMLResponse("<h1>API Key not found</h1>", status_code=404)

        html = render(request, "public/query.html", name=key.name, key_id=key_id)
        return HTMLResponse(content=html)
