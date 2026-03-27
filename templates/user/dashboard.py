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

                <div class="grid grid-cols-1 xl:grid-cols-2 gap-6 mt-6">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-3">
                            <h3 class="text-lg font-semibold">Active Sessions (Last 1 Minute)</h3>
                            <span id="active-count" class="text-sm text-gray-500">0 active</span>
                        </div>
                        <div id="active-sessions" class="grid grid-cols-1 2xl:grid-cols-2 gap-3"><div class="text-gray-400 text-center py-2 2xl:col-span-2">No active sessions</div></div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-3">
                            <h3 class="text-lg font-semibold">System Active Requests (Last 1 Minute)</h3>
                            <span id="system-active-count" class="text-sm text-gray-500">0 active</span>
                        </div>
                        <div class="text-xs text-gray-400 mb-3">Anonymized across all API keys. Your own traffic is labeled as Yourself.</div>
                        <div id="system-active-sessions" class="grid grid-cols-1 2xl:grid-cols-2 gap-3"><div class="text-gray-400 text-center py-2 2xl:col-span-2">No active sessions</div></div>
                    </div>
                </div>

                <div class="bg-gray-50 rounded-lg p-4 my-6">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="text-lg font-semibold">Request Trend</h3>
                        <span id="trend-meta" class="text-xs text-gray-500">Requests / Tokens / Errors</span>
                    </div>
                    <div style="height: 250px;">
                        <canvas id="trend-chart"></canvas>
                    </div>
                </div>

                <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-3">
                            <h3 class="text-lg font-semibold">Model Usage</h3>
                            <span id="model-usage-meta" class="text-xs text-gray-500">Your API key</span>
                        </div>
                        <div class="h-64"><canvas id="model-usage-chart"></canvas></div>
                        <div id="model-stats" class="mt-4 grid grid-cols-1 2xl:grid-cols-2 gap-3 max-h-64 overflow-y-auto"></div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-3">
                            <h3 class="text-lg font-semibold">System Model Usage</h3>
                            <span id="system-model-meta" class="text-xs text-gray-500">All API keys</span>
                        </div>
                        <div class="h-64"><canvas id="system-model-chart"></canvas></div>
                        <div id="system-model-legend" class="mt-4 grid grid-cols-1 2xl:grid-cols-2 gap-3 max-h-64 overflow-y-auto"></div>
                    </div>
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
        const baseUrl = window.location.origin + '/v1';
        let trendChart = null;
        let modelUsageChart = null;
        let systemModelChart = null;
        const ownModelPalette = ['#2563eb', '#0f766e', '#0891b2', '#1d4ed8', '#059669', '#0ea5e9', '#14b8a6', '#0284c7'];
        const systemModelPalette = ['#f59e0b', '#ef4444', '#f97316', '#dc2626', '#eab308', '#fb7185', '#ea580c', '#f43f5e'];
        
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

        function formatCompactTokens(tokens) {{
            const value = Number(tokens || 0);
            if (value >= 1000000) return (value / 1000000).toFixed(1).replace(/\\.0$/, '') + 'M';
            if (value >= 1000) return (value / 1000).toFixed(1).replace(/\\.0$/, '') + 'K';
            if (Number.isInteger(value)) return value.toLocaleString();
            return value.toFixed(1).replace(/\\.0$/, '');
        }}

        function getTokenChartScale(requestValues, tokenValues) {{
            const maxRequests = Math.max(...requestValues, 1);
            const maxTokens = Math.max(...tokenValues, 1);
            const scales = [
                {{ divisor: 1, suffix: '' }},
                {{ divisor: 1000, suffix: 'K' }},
                {{ divisor: 1000000, suffix: 'M' }},
                {{ divisor: 1000000000, suffix: 'B' }}
            ];
            let scale = scales.find(s => maxTokens / s.divisor <= maxRequests * 5) || scales[scales.length - 1];
            if (maxTokens / scale.divisor >= 1000) {{
                scale = scales[scales.indexOf(scale) + 1] || scale;
            }}
            return scale;
        }}

        function buildDonutSeries(data, palette, metric = 'requests', limit = 5) {{
            const entries = Object.entries(data || {{}})
                .sort((a, b) => (b[1][metric] || 0) - (a[1][metric] || 0))
                .filter(([, stats]) => (stats[metric] || 0) > 0);
            const topEntries = entries.slice(0, limit);
            const otherValue = entries.slice(limit).reduce((sum, [, stats]) => sum + (stats[metric] || 0), 0);
            const labels = topEntries.map(([name]) => name);
            const values = topEntries.map(([, stats]) => stats[metric] || 0);
            const colors = topEntries.map((_, index) => palette[index % palette.length]);
            if (otherValue > 0) {{
                labels.push('Others');
                values.push(otherValue);
                colors.push('#cbd5e1');
            }}
            return {{ entries, labels, values, colors }};
        }}

        function renderModelUsageChart(chartId, legendId, metaId, models, chartRef, palette, metaLabel = 'All API keys') {{
            const series = buildDonutSeries(models, palette, 'requests', 6);
            const ctx = document.getElementById(chartId).getContext('2d');
            if (chartRef.current) chartRef.current.destroy();

            chartRef.current = new Chart(ctx, {{
                type: 'doughnut',
                data: {{
                    labels: series.labels,
                    datasets: [{{
                        data: series.values,
                        backgroundColor: series.colors,
                        borderWidth: 0,
                        hoverOffset: 8
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const total = series.values.reduce((sum, value) => sum + value, 0) || 1;
                                    const pct = context.raw / total;
                                    return `${{context.label}}: ${{(context.raw || 0).toLocaleString()}} req (${{(pct * 100).toFixed(1)}}%)`;
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            const totalRequests = series.entries.reduce((sum, [, stats]) => sum + (stats.requests || 0), 0) || 1;
            const legendHtml = series.entries.slice(0, 6).map(([name, stats], index) => `
                <div class="rounded bg-white p-3 shadow-sm">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="inline-block h-2.5 w-2.5 rounded-full" style="background:${{palette[index % palette.length]}}"></span>
                        <span class="truncate text-sm font-medium" title="${{name}}">${{name}}</span>
                    </div>
                    <div class="mt-2 text-xs text-gray-500">${{stats.requests.toLocaleString()}} req / ${{formatCompactTokens(stats.tokens || 0)}}</div>
                    ${{typeof stats.errors === 'number' ? `<div class="mt-1 text-xs text-gray-400">err ${{stats.errors}}</div>` : ''}}
                </div>
            `).join('');
            document.getElementById(legendId).innerHTML = legendHtml || '<div class="text-gray-400 text-center py-2 2xl:col-span-2">No data</div>';
            document.getElementById(metaId).textContent = `${{metaLabel}} / ${{Object.keys(models || {{}}).length}} models / top share ${{
                series.entries[0] ? (((series.entries[0][1].requests || 0) / totalRequests) * 100).toFixed(1) + '%' : '0%'
            }}`;
        }}

        function renderOwnModelChart(models) {{
            renderModelUsageChart(
                'model-usage-chart',
                'model-stats',
                'model-usage-meta',
                models,
                {{
                    get current() {{ return modelUsageChart; }},
                    set current(value) {{ modelUsageChart = value; }}
                }},
                ownModelPalette,
                'Your API key'
            );
        }}

        function renderSystemModelChart(models) {{
            renderModelUsageChart(
                'system-model-chart',
                'system-model-legend',
                'system-model-meta',
                models,
                {{
                    get current() {{ return systemModelChart; }},
                    set current(value) {{ systemModelChart = value; }}
                }},
                systemModelPalette,
                'All API keys'
            );
        }}

        function renderSystemActiveSessions(data) {{
            document.getElementById('system-active-count').textContent = `${{data.active_count || 0}} active / ${{(data.request_count || 0).toLocaleString()}} req`;
            if (!data.active_count) {{
                document.getElementById('system-active-sessions').innerHTML = '<div class="text-gray-400 text-center py-2 2xl:col-span-2">No active sessions</div>';
                return;
            }}

            const html = (data.sessions || []).map(session => {{
                const labelClass = session.is_self ? 'bg-blue-100 text-blue-700' : 'bg-gray-200 text-gray-700';
                const modelsHtml = Object.entries(session.models || {{}})
                    .sort((a, b) => b[1] - a[1])
                    .map(([model, count]) => `<span class="bg-white text-gray-600 text-xs px-2 py-1 rounded">${{model}} (${{count}})</span>`)
                    .join(' ');
                return `
                    <div class="rounded bg-white p-3 shadow-sm">
                        <div class="flex justify-between items-start gap-3">
                            <div class="min-w-0">
                                <span class="inline-flex px-2 py-0.5 rounded text-xs font-medium ${{labelClass}}">${{session.name}}</span>
                                <div class="mt-2 text-xs text-gray-500">${{modelsHtml || 'No models'}}</div>
                            </div>
                            <div class="text-sm font-medium text-gray-700 shrink-0">${{session.requests}} req</div>
                        </div>
                    </div>
                `;
            }}).join('');
            document.getElementById('system-active-sessions').innerHTML = html;
        }}
         
        async function loadStats() {{
            const period = document.getElementById('period-select').value;
            const [statsResp, systemModelsResp] = await Promise.all([
                fetch('/user/api/stats?period=' + period),
                fetch('/user/api/system-models?period=' + period)
            ]);
            const data = await statsResp.json();
            const systemModels = await systemModelsResp.json();
             
            if (data.error) {{ window.location.href = '/user/login'; return; }}
             
            document.getElementById('total-requests').textContent = data.total_requests.toLocaleString();
            document.getElementById('total-tokens').textContent = formatCompactTokens(data.total_tokens || 0);
            document.getElementById('total-errors').textContent = data.total_errors;
            document.getElementById('model-count').textContent = Object.keys(data.models || {{}}).length;
             
            renderTrendChart(data.trend || {{}});
            renderOwnModelChart(data.models || {{}});
            renderSystemModelChart(systemModels.models || {{}});
        }}
         
        function renderTrendChart(trendData) {{
            const ctx = document.getElementById('trend-chart').getContext('2d');
            if (trendChart) trendChart.destroy();
             
            const labels = Object.keys(trendData);
            const requests = labels.map(l => trendData[l].requests || 0);
            const rawTokens = labels.map(l => trendData[l].tokens || 0);
            const errors = labels.map(l => trendData[l].errors || 0);
            const tokenScale = getTokenChartScale(requests, rawTokens);
            const tokens = rawTokens.map(v => Number((v / tokenScale.divisor).toFixed(2)));
            const tokenLabel = tokenScale.suffix ? `Tokens (${{tokenScale.suffix}})` : 'Tokens';
            document.getElementById('trend-meta').textContent = `${{tokenLabel}} on right axis`;
             
            trendChart = new Chart(ctx, {{
                data: {{
                    labels: labels,
                    datasets: [
                        {{
                            type: 'bar',
                            label: 'Requests',
                            data: requests,
                            backgroundColor: 'rgba(59, 130, 246, 0.35)',
                            borderColor: 'rgba(59, 130, 246, 0.85)',
                            borderWidth: 1,
                            borderRadius: 4,
                            yAxisID: 'yRequests'
                        }},
                        {{
                            type: 'line',
                            label: tokenLabel,
                            data: tokens,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.12)',
                            pointBackgroundColor: '#10b981',
                            pointRadius: 3,
                            pointHoverRadius: 4,
                            borderWidth: 2,
                            tension: 0.25,
                            fill: true,
                            yAxisID: 'yTokens'
                        }},
                        {{
                            type: 'line',
                            label: 'Errors',
                            data: errors,
                            borderColor: '#ef4444',
                            backgroundColor: 'rgba(239, 68, 68, 0.08)',
                            pointBackgroundColor: '#ef4444',
                            pointRadius: 2,
                            pointHoverRadius: 4,
                            borderWidth: 2,
                            tension: 0.2,
                            borderDash: [6, 4],
                            fill: false,
                            yAxisID: 'yRequests'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{ mode: 'index', intersect: false }},
                    scales: {{
                        x: {{
                            ticks: {{
                                autoSkip: true,
                                maxRotation: 0,
                                minRotation: 0,
                                maxTicksLimit: labels.length > 20 ? 10 : 12
                            }}
                        }},
                        yRequests: {{
                            beginAtZero: true,
                            position: 'left',
                            title: {{ display: true, text: 'Requests / Errors' }}
                        }},
                        yTokens: {{
                            beginAtZero: true,
                            position: 'right',
                            grid: {{ drawOnChartArea: false }},
                            title: {{ display: true, text: tokenLabel }}
                        }}
                    }},
                    plugins: {{
                        legend: {{ position: 'top' }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    if (context.dataset.yAxisID === 'yTokens') {{
                                        const rawValue = rawTokens[context.dataIndex] || 0;
                                        return `${{tokenLabel}}: ${{formatCompactTokens(rawValue)}} (${{rawValue.toLocaleString()}})`;
                                    }}
                                    return `${{context.dataset.label}}: ${{(context.parsed.y || 0).toLocaleString()}}`;
                                }}
                            }}
                        }}
                    }}
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
                document.getElementById('active-sessions').innerHTML = '<div class="text-gray-400 text-center py-2 2xl:col-span-2">No active sessions</div>';
                return;
            }}
            
            const html = Object.entries(data.sessions).map(([model, session]) => `
                <div class="rounded bg-white p-3 shadow-sm">
                    <div class="flex justify-between items-start gap-3">
                        <span class="font-medium text-sm min-w-0">${{model}}</span>
                        <span class="text-sm text-gray-600 shrink-0">${{session.requests}} req</span>
                    </div>
                </div>
            `).join('');
            document.getElementById('active-sessions').innerHTML = html;
        }}

        async function loadSystemActiveSessions() {{
            const resp = await fetch('/user/api/system-active');
            const data = await resp.json();
            if (data.error) return;
            renderSystemActiveSessions(data);
        }}
         
        loadStats();
        loadActiveSessions();
        loadSystemActiveSessions();
        setInterval(loadStats, 30000);
        setInterval(loadActiveSessions, 60000);
        setInterval(loadSystemActiveSessions, 30000);
    </script>
</body>
</html>
"""
