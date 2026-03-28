MOBILE_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Login - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #312e81 100%);
            min-height: 100vh;
        }
        .login-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .input-field {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #e2e8f0;
            transition: border-color 0.2s;
        }
        .input-field:focus {
            outline: none;
            border-color: rgba(99, 102, 241, 0.6);
            background: rgba(255, 255, 255, 0.12);
        }
        .input-field::placeholder { color: #64748b; }
        .btn-login {
            background: linear-gradient(135deg, #6366f1, #4f46e5);
            transition: opacity 0.2s, transform 0.1s;
        }
        .btn-login:active { transform: scale(0.98); }
        .btn-login:disabled { opacity: 0.5; }
    </style>
</head>
<body>
    <div class="flex items-center justify-center min-h-screen px-6">
        <div class="login-card rounded-2xl p-8 w-full max-w-sm">
            <div class="text-center mb-8">
                <div class="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-indigo-500/20 mb-4">
                    <svg class="w-7 h-7 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                    </svg>
                </div>
                <h1 class="text-2xl font-bold text-white">API Proxy</h1>
                <p class="text-sm text-slate-400 mt-1">Admin Dashboard</p>
            </div>
            <form id="login-form" class="space-y-4">
                <div>
                    <input type="text" id="username" class="input-field w-full rounded-xl px-4 py-3 text-sm" placeholder="Username" autocomplete="username" required>
                </div>
                <div>
                    <input type="password" id="password" class="input-field w-full rounded-xl px-4 py-3 text-sm" placeholder="Password" autocomplete="current-password" required>
                </div>
                <div id="error-msg" class="text-red-400 text-xs text-center hidden"></div>
                <button type="submit" id="login-btn" class="btn-login w-full text-white font-medium py-3 rounded-xl text-sm">
                    Sign In
                </button>
            </form>
        </div>
    </div>
    <script>
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('login-btn');
            const errEl = document.getElementById('error-msg');
            btn.disabled = true;
            btn.textContent = 'Signing in...';
            errEl.classList.add('hidden');
            try {
                const resp = await fetch('/admin/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: document.getElementById('username').value,
                        password: document.getElementById('password').value
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    window.location.href = '/admin/m';
                } else {
                    errEl.textContent = data.error || data.detail || 'Login failed';
                    errEl.classList.remove('hidden');
                }
            } catch (err) {
                errEl.textContent = 'Network error';
                errEl.classList.remove('hidden');
            }
            btn.disabled = false;
            btn.textContent = 'Sign In';
        });
    </script>
</body>
</html>
"""

MOBILE_HOME_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Dashboard - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { -webkit-tap-highlight-color: transparent; }
        .stat-card { transition: transform 0.15s; }
        .stat-card:active { transform: scale(0.97); }
        .collapsible-header { -webkit-tap-highlight-color: transparent; }
        .collapsible-content { max-height: 0; overflow: hidden; transition: max-height 0.3s ease; }
        .collapsible-content.open { max-height: 2000px; }
        .chevron { transition: transform 0.3s; }
        .chevron.open { transform: rotate(180deg); }
        ::-webkit-scrollbar { display: none; }
    </style>
</head>
<body class="bg-gray-50 min-h-screen pb-20">
    <nav class="bg-white shadow-sm sticky top-0 z-50">
        <div class="flex items-center justify-between px-4 py-3">
            <div>
                <h1 class="text-lg font-bold text-gray-800">API Proxy</h1>
                <div class="text-xs text-gray-400">Admin Dashboard</div>
            </div>
            <div class="flex items-center gap-2">
                <select id="period-select" class="text-xs border rounded-lg px-2 py-1.5 bg-gray-50" onchange="loadData()">
                    <option value="day">Today</option>
                    <option value="week">Week</option>
                    <option value="month">Month</option>
                    <option value="year">Year</option>
                </select>
                <button onclick="logout()" class="p-2 text-gray-400 hover:text-red-500 rounded-lg">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
                    </svg>
                </button>
            </div>
        </div>
    </nav>

    <div class="px-4 pt-4 space-y-4">
        <div class="grid grid-cols-3 gap-3">
            <div class="stat-card bg-white rounded-xl p-3 shadow-sm">
                <div class="text-[10px] text-gray-400 uppercase tracking-wider">Requests</div>
                <div id="total-requests" class="text-lg font-bold text-blue-600 mt-1">0</div>
            </div>
            <div class="stat-card bg-white rounded-xl p-3 shadow-sm">
                <div class="text-[10px] text-gray-400 uppercase tracking-wider">Tokens</div>
                <div id="total-tokens" class="text-lg font-bold text-green-600 mt-1">0</div>
            </div>
            <div class="stat-card bg-white rounded-xl p-3 shadow-sm">
                <div class="text-[10px] text-gray-400 uppercase tracking-wider">Errors</div>
                <div id="total-errors" class="text-lg font-bold text-red-500 mt-1">0</div>
            </div>
        </div>
        <div class="grid grid-cols-3 gap-3">
            <div class="stat-card bg-white rounded-xl p-3 shadow-sm">
                <div class="text-[10px] text-gray-400 uppercase tracking-wider">RPS</div>
                <div id="rps" class="text-lg font-bold text-orange-500 mt-1">0</div>
            </div>
            <div class="stat-card bg-white rounded-xl p-3 shadow-sm">
                <div class="text-[10px] text-gray-400 uppercase tracking-wider">TPS</div>
                <div id="tps" class="text-lg font-bold text-teal-600 mt-1">0</div>
            </div>
            <div class="stat-card bg-white rounded-xl p-3 shadow-sm">
                <div class="text-[10px] text-gray-400 uppercase tracking-wider">Err Rate</div>
                <div id="error-rate" class="text-lg font-bold text-purple-600 mt-1">0%</div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm overflow-hidden">
            <div class="collapsible-header flex items-center justify-between p-4" onclick="toggleSection('active')">
                <div class="flex items-center gap-2">
                    <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                    <span class="font-medium text-sm text-gray-800">Active Sessions</span>
                    <span id="active-count" class="text-xs text-gray-400">0</span>
                </div>
                <svg id="chevron-active" class="chevron w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
            </div>
            <div id="active-content" class="collapsible-content">
                <div id="active-sessions" class="px-4 pb-4 space-y-2"></div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm overflow-hidden">
            <div class="collapsible-header flex items-center justify-between p-4" onclick="toggleSection('slow')">
                <div class="flex items-center gap-2">
                    <svg class="w-4 h-4 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                    <span class="font-medium text-sm text-gray-800">Slow Requests</span>
                    <span id="slow-count" class="text-xs text-gray-400">0</span>
                </div>
                <svg id="chevron-slow" class="chevron w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
            </div>
            <div id="slow-content" class="collapsible-content">
                <div id="slow-requests" class="px-4 pb-4 space-y-2"></div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm overflow-hidden">
            <div class="collapsible-header flex items-center justify-between p-4" onclick="toggleSection('providers')">
                <div class="flex items-center gap-2">
                    <svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/>
                    </svg>
                    <span class="font-medium text-sm text-gray-800">Provider Usage</span>
                </div>
                <svg id="chevron-providers" class="chevron w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
            </div>
            <div id="providers-content" class="collapsible-content">
                <div id="provider-bars" class="px-4 pb-4 space-y-3"></div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm overflow-hidden">
            <div class="collapsible-header flex items-center justify-between p-4" onclick="toggleSection('apikeys')">
                <div class="flex items-center gap-2">
                    <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"/>
                    </svg>
                    <span class="font-medium text-sm text-gray-800">API Key Usage</span>
                </div>
                <svg id="chevron-apikeys" class="chevron w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
            </div>
            <div id="apikeys-content" class="collapsible-content">
                <div id="apikey-bars" class="px-4 pb-4 space-y-3"></div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm p-4">
            <div class="flex items-center justify-between mb-3">
                <span class="font-medium text-sm text-gray-800">Request Trend</span>
                <span id="trend-meta" class="text-[10px] text-gray-400">Requests / Tokens / Errors</span>
            </div>
            <div style="height: 220px;">
                <canvas id="trendChart"></canvas>
            </div>
        </div>
    </div>

    <script>
        let currentPeriod = 'day';
        let trendChart = null;

        function formatCompactTokens(tokens) {
            const value = Number(tokens || 0);
            if (value >= 1000000) return (value / 1000000).toFixed(1).replace(/\\.0$/, '') + 'M';
            if (value >= 1000) return (value / 1000).toFixed(1).replace(/\\.0$/, '') + 'K';
            if (Number.isInteger(value)) return value.toLocaleString();
            return value.toFixed(1).replace(/\\.0$/, '');
        }

        function getTokenChartScale(requestValues, tokenValues) {
            const maxRequests = Math.max(...requestValues, 1);
            const maxTokens = Math.max(...tokenValues, 1);
            const scales = [
                { divisor: 1, suffix: '' },
                { divisor: 1000, suffix: 'K' },
                { divisor: 1000000, suffix: 'M' },
                { divisor: 1000000000, suffix: 'B' }
            ];
            let scale = scales.find(s => maxTokens / s.divisor <= maxRequests * 5) || scales[scales.length - 1];
            if (maxTokens / scale.divisor >= 1000) {
                scale = scales[scales.indexOf(scale) + 1] || scale;
            }
            return scale;
        }

        function toggleSection(name) {
            const content = document.getElementById(name + '-content');
            const chevron = document.getElementById('chevron-' + name);
            content.classList.toggle('open');
            chevron.classList.toggle('open');
        }

        function renderModelList(models) {
            const items = Object.entries(models || {})
                .filter(([, m]) => (m.requests || 0) > 0)
                .sort((a, b) => (b[1].tokens || 0) - (a[1].tokens || 0))
                .map(([model, m]) => `<div class="flex justify-between text-[11px] text-gray-500"><span class="truncate">${model}</span><span class="shrink-0 ml-2">${m.requests} / ${formatCompactTokens(m.tokens || 0)}</span></div>`)
                .join('');
            return items ? `<div class="mt-2 space-y-1 border-l-2 border-gray-100 pl-2">${items}</div>` : '';
        }

        function renderProviderBars(providers) {
            const entries = Object.entries(providers)
                .sort((a, b) => (b[1].tokens || 0) - (a[1].tokens || 0));
            const maxTokens = Math.max(...entries.map(([, p]) => p.tokens || 0), 1);
            const html = entries.map(([name, p]) => {
                const pct = ((p.tokens || 0) / maxTokens) * 100;
                const modelsHtml = renderModelList(p.models);
                return `<div class="bg-gray-50 rounded-lg p-3">
                    <div class="flex justify-between text-xs gap-2"><span class="font-medium truncate">${name}</span><span class="text-gray-500 shrink-0">${p.requests} req / ${formatCompactTokens(p.tokens || 0)}</span></div>
                    <div class="w-full bg-gray-200 rounded-full h-1.5 mt-2"><div class="bg-blue-500 h-1.5 rounded-full" style="width: ${pct}%"></div></div>
                    ${modelsHtml}
                </div>`;
            }).join('');
            document.getElementById('provider-bars').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No data</div>';
        }

        function renderApiKeyBars(apiKeys) {
            const entries = Object.entries(apiKeys)
                .sort((a, b) => (b[1].tokens || 0) - (a[1].tokens || 0));
            const maxTokens = Math.max(...entries.map(([, k]) => k.tokens || 0), 1);
            const html = entries.map(([name, k]) => {
                const pct = ((k.tokens || 0) / maxTokens) * 100;
                const modelsHtml = renderModelList(k.models);
                return `<div class="bg-gray-50 rounded-lg p-3">
                    <div class="flex justify-between text-xs gap-2"><span class="font-medium truncate">${name}</span><span class="text-gray-500 shrink-0">${k.requests} req / ${formatCompactTokens(k.tokens || 0)}</span></div>
                    <div class="w-full bg-gray-200 rounded-full h-1.5 mt-2"><div class="bg-emerald-500 h-1.5 rounded-full" style="width: ${pct}%"></div></div>
                    ${modelsHtml}
                </div>`;
            }).join('');
            document.getElementById('apikey-bars').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No data</div>';
        }

        function renderTrendChart(chartData) {
            const ctx = document.getElementById('trendChart').getContext('2d');
            if (trendChart) trendChart.destroy();
            const labels = chartData.intervals || [];
            const requests = labels.map(i => chartData.data?.[i]?.requests || 0);
            const rawTokens = labels.map(i => chartData.data?.[i]?.tokens || 0);
            const tokenScale = getTokenChartScale(requests, rawTokens);
            const tokens = rawTokens.map(v => Number((v / tokenScale.divisor).toFixed(2)));
            const tokenLabel = tokenScale.suffix ? `Tokens (${tokenScale.suffix})` : 'Tokens';
            document.getElementById('trend-meta').textContent = `${tokenLabel} on right axis`;

            trendChart = new Chart(ctx, {
                data: {
                    labels: labels,
                    datasets: [
                        {
                            type: 'bar',
                            label: 'Requests',
                            data: requests,
                            backgroundColor: 'rgba(59, 130, 246, 0.35)',
                            borderColor: 'rgba(59, 130, 246, 0.85)',
                            borderWidth: 1,
                            borderRadius: 3,
                            yAxisID: 'yRequests'
                        },
                        {
                            type: 'line',
                            label: tokenLabel,
                            data: tokens,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                            pointBackgroundColor: '#10b981',
                            pointRadius: 2,
                            pointHoverRadius: 3,
                            borderWidth: 2,
                            tension: 0.25,
                            fill: true,
                            yAxisID: 'yTokens'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: {
                            ticks: { autoSkip: true, maxRotation: 0, minRotation: 0, maxTicksLimit: 6, font: { size: 10 } }
                        },
                        yRequests: {
                            beginAtZero: true,
                            position: 'left',
                            title: { display: true, text: 'Requests', font: { size: 10 } },
                            ticks: { font: { size: 10 } }
                        },
                        yTokens: {
                            beginAtZero: true,
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: tokenLabel, font: { size: 10 } },
                            ticks: { font: { size: 10 } }
                        }
                    },
                    plugins: {
                        legend: { position: 'top', labels: { boxWidth: 10, font: { size: 10 } } },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    if (context.dataset.yAxisID === 'yTokens') {
                                        const raw = rawTokens[context.dataIndex] || 0;
                                        return `${tokenLabel}: ${formatCompactTokens(raw)}`;
                                    }
                                    return `Requests: ${(context.parsed.y || 0).toLocaleString()}`;
                                }
                            }
                        }
                    }
                }
            });
        }

        async function loadData() {
            const period = document.getElementById('period-select').value;
            try {
                const [statsResp, chartResp] = await Promise.all([
                    fetchJsonOrRedirect('/admin/api/stats/period?period=' + period),
                    fetchJsonOrRedirect('/admin/api/stats/chart?period=' + period)
                ]);
                const data = statsResp;
                const chartData = chartResp;

                document.getElementById('total-requests').textContent = (data.total_requests || 0).toLocaleString();
                document.getElementById('total-tokens').textContent = formatCompactTokens(data.total_tokens || 0);
                document.getElementById('total-errors').textContent = data.total_errors || 0;
                const errorRate = data.total_requests > 0 ? ((data.total_errors / data.total_requests) * 100).toFixed(1) : 0;
                document.getElementById('error-rate').textContent = errorRate + '%';

                renderProviderBars(data.providers || {});
                renderApiKeyBars(data.api_keys || {});
                renderTrendChart(chartData);
            } catch (e) {
                console.error('Failed to load data:', e);
            }
        }

        async function loadRealtimeStats() {
            try {
                const data = await fetchJsonOrRedirect('/admin/api/stats/realtime');
                document.getElementById('rps').textContent = data.requests_per_second || 0;
                document.getElementById('tps').textContent = formatCompactTokens(data.tokens_per_second || 0);
            } catch (e) {}
        }

        async function loadActiveSessions() {
            try {
                const data = await fetchJsonOrRedirect('/admin/api/stats/active');
                const sessions = data.sessions || {};
                const count = Object.keys(sessions).length;
                document.getElementById('active-count').textContent = count;
                if (count === 0) {
                    document.getElementById('active-sessions').innerHTML = '<div class="text-gray-400 text-center py-2 text-xs">No active sessions</div>';
                    return;
                }
                const html = Object.entries(sessions).map(([keyName, session]) => {
                    const models = Object.entries(session.models || {})
                        .sort((a, b) => b[1] - a[1])
                        .map(([m, c]) => `<span class="bg-gray-100 text-gray-600 text-[10px] px-1.5 py-0.5 rounded">${m} (${c})</span>`)
                        .join(' ');
                    return `<div class="bg-gray-50 rounded-lg p-3">
                        <div class="flex justify-between items-start gap-2">
                            <div class="min-w-0"><div class="text-xs font-medium truncate">${keyName}</div><div class="mt-1 flex flex-wrap gap-1">${models || '<span class="text-[10px] text-gray-400">-</span>'}</div></div>
                            <span class="text-xs text-gray-500 shrink-0">${session.requests} req</span>
                        </div>
                    </div>`;
                }).join('');
                document.getElementById('active-sessions').innerHTML = html;
            } catch (e) {}
        }

        async function loadSlowRequests() {
            try {
                const data = await fetchJsonOrRedirect('/admin/api/stats/slow');
                const pending = data.pending || [];
                const recent = data.recent || [];
                const count = pending.length + recent.length;
                document.getElementById('slow-count').textContent = count;
                if (count === 0) {
                    document.getElementById('slow-requests').innerHTML = '<div class="text-gray-400 text-center py-2 text-xs">No slow requests</div>';
                    return;
                }
                let html = '';
                for (const req of pending) {
                    const elapsed = Math.round((Date.now() - new Date(req.created_at).getTime()) / 1000);
                    html += `<div class="bg-orange-50 border border-orange-200 rounded-lg p-3">
                        <div class="flex justify-between items-start gap-2">
                            <div class="min-w-0"><div class="text-xs font-medium truncate">${req.api_key || '-'} / ${req.model || '-'}</div><div class="text-[10px] text-orange-600 mt-1">${elapsed}s elapsed</div></div>
                            <span class="text-[10px] bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded">pending</span>
                        </div>
                    </div>`;
                }
                for (const req of recent.slice(0, 5)) {
                    const statusClass = req.status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700';
                    html += `<div class="bg-gray-50 rounded-lg p-3">
                        <div class="flex justify-between items-start gap-2">
                            <div class="min-w-0"><div class="text-xs font-medium truncate">${req.api_key || '-'} / ${req.model || '-'}</div><div class="text-[10px] text-gray-500 mt-1">${Math.round(req.latency_ms / 1000)}s</div></div>
                            <span class="text-[10px] ${statusClass} px-1.5 py-0.5 rounded">${req.status}</span>
                        </div>
                    </div>`;
                }
                document.getElementById('slow-requests').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No slow requests</div>';
            } catch (e) {}
        }

        async function logout() {
            await fetch('/admin/api/auth/logout', { method: 'POST' });
            window.location.href = '/admin/m/login';
        }

        async function fetchJsonOrRedirect(url, options) {
            const resp = await fetch(url, options);
            if (resp.status === 401) {
                window.location.href = '/admin/m/login';
                throw new Error('Unauthorized');
            }
            return await resp.json();
        }

        loadData();
        loadRealtimeStats();
        loadActiveSessions();
        loadSlowRequests();

        setInterval(loadData, 10000);
        setInterval(loadRealtimeStats, 10000);
        setInterval(loadActiveSessions, 60000);
        setInterval(loadSlowRequests, 5000);
    </script>
</body>
</html>
"""
