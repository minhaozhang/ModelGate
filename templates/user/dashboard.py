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
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="text-lg font-semibold">Active Sessions (Last 1 Minute)</h3>
                        <span id="active-count" class="text-sm text-gray-500">0 active</span>
                    </div>
                    <div id="active-sessions" class="space-y-2"><div class="text-gray-400 text-center py-2">No active sessions</div></div>
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
                
                const config = data.config;
                config.provider['model-token-plan'].options.baseURL = window.location.origin + '/v1';
                
                const prompt = "# 请帮我将以下provider配置添加到 ~/.opencode/opencode.json 中。保留现有的providers和其他设置，只添加或更新 'model-token-plan' 这个provider。\\n\\n";
                document.getElementById('config-output').textContent = prompt + JSON.stringify(config, null, 2);
                
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
        
        async function loadActiveSessions() {{
            const resp = await fetch('/user/api/active');
            const data = await resp.json();
            
            document.getElementById('active-count').textContent = data.active_count + ' active';
            
            if (data.active_count === 0) {{
                document.getElementById('active-sessions').innerHTML = '<div class="text-gray-400 text-center py-2">No active sessions</div>';
                return;
            }}
            
            const html = Object.entries(data.sessions).map(([model, session]) => `
                <div class="flex justify-between items-center p-2 bg-white rounded">
                    <span class="font-medium text-sm">${{model}}</span>
                    <span class="text-sm text-gray-600">${{session.requests}} req</span>
                </div>
            `).join('');
            document.getElementById('active-sessions').innerHTML = html;
        }}
        
        loadStats();
        loadActiveSessions();
        setInterval(loadStats, 30000);
        setInterval(loadActiveSessions, 60000);
    </script>
</body>
</html>
"""
