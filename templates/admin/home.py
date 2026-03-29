HOME_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Dashboard - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
        .stat-card { transition: transform 0.2s, box-shadow 0.2s; }
        .stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        body.theme-dark { background: #020617 !important; color: #e2e8f0; }
        body.theme-dark nav,
        body.theme-dark .bg-white { background: #0f172a !important; }
        body.theme-dark .bg-gray-50 { background: #111827 !important; }
        body.theme-dark .bg-gray-200 { background: #1f2937 !important; }
        body.theme-dark .bg-blue-50 { background: rgba(37, 99, 235, 0.15) !important; }
        body.theme-dark .bg-blue-100 { background: rgba(59, 130, 246, 0.2) !important; }
        body.theme-dark .bg-green-50 { background: rgba(16, 185, 129, 0.14) !important; }
        body.theme-dark .bg-green-100 { background: rgba(16, 185, 129, 0.2) !important; }
        body.theme-dark .bg-orange-50 { background: rgba(249, 115, 22, 0.16) !important; }
        body.theme-dark .bg-red-50 { background: rgba(239, 68, 68, 0.14) !important; }
        body.theme-dark .bg-red-100 { background: rgba(239, 68, 68, 0.18) !important; }
        body.theme-dark .bg-yellow-50 { background: rgba(234, 179, 8, 0.14) !important; }
        body.theme-dark .bg-slate-50 { background: #111827 !important; }
        body.theme-dark .bg-gray-100 { background: #020617 !important; }
        body.theme-dark .text-blue-800 { color: #bfdbfe !important; }
        body.theme-dark .text-green-800 { color: #bbf7d0 !important; }
        body.theme-dark .text-red-800 { color: #fecaca !important; }
        body.theme-dark .text-gray-800 { color: #f8fafc !important; }
        body.theme-dark .text-gray-700 { color: #e5e7eb !important; }
        body.theme-dark .text-gray-600 { color: #cbd5e1 !important; }
        body.theme-dark .text-gray-500 { color: #94a3b8 !important; }
        body.theme-dark .text-gray-400 { color: #64748b !important; }
        body.theme-dark .text-slate-800 { color: #f8fafc !important; }
        body.theme-dark .text-slate-700 { color: #e2e8f0 !important; }
        body.theme-dark .text-slate-600 { color: #cbd5e1 !important; }
        body.theme-dark .text-slate-500 { color: #94a3b8 !important; }
        body.theme-dark .border,
        body.theme-dark .border-b,
        body.theme-dark .border-t,
        body.theme-dark .border-l-2,
        body.theme-dark .border-l-4 { border-color: #1f2937 !important; }
        body.theme-dark input,
        body.theme-dark select,
        body.theme-dark textarea { background: #0f172a !important; color: #e5e7eb !important; border-color: #334155 !important; }
        body.theme-dark button:not(.bg-blue-500):not(.bg-red-500):not(.bg-green-500):not(.bg-purple-500):not(.bg-orange-500):not(.bg-teal-500) { background-color: #0f172a; color: #e5e7eb; border-color: #334155; }
        body.theme-dark .shadow,
        body.theme-dark .shadow-sm,
        body.theme-dark .shadow-lg,
        body.theme-dark .shadow-xl { box-shadow: 0 12px 30px rgba(2, 6, 23, 0.45) !important; }
        body.theme-dark .nav-link { color: #cbd5e1 !important; }
        body.theme-dark .nav-link.active { background: rgba(96, 165, 250, 0.15); color: #60a5fa !important; border-right-color: #60a5fa; }
        body.theme-dark .nav-link:hover { background: rgba(148, 163, 184, 0.12); }
        body.theme-dark .ring-blue-500 { --tw-ring-color: rgba(96, 165, 250, 0.75) !important; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="flex">
        <nav class="w-56 bg-white shadow-lg min-h-screen fixed">
            <div class="p-4 border-b"><h1 class="text-xl font-bold text-gray-800">API Proxy</h1></div>
            <div class="py-2">
                <a href="/admin/home" class="nav-link active flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                    Home
                </a>
                <a href="/admin/config" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                    Config
                </a>
                <a href="/admin/api-keys" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"></path></svg>
                    API Keys
                </a>
                <a href="/admin/monitor" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                    Monitor
                </a>
                <a href="/admin/usage" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    Usage Guide
                </a>
            </div>
            <div class="absolute bottom-0 w-full p-4 border-t">
                <button onclick="logout()" class="w-full text-left text-gray-600 hover:text-red-600 flex items-center">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path></svg>
                    Logout
                </button>
            </div>
        </nav>
        <main class="ml-56 flex-1 p-6">
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-gray-800">Dashboard</h2>
                <div class="flex items-center gap-3">
                    <button id="theme-toggle" onclick="toggleTheme()" class="border border-gray-200 bg-white text-gray-700 px-4 py-2 rounded hover:bg-gray-50">
                        Dark Mode
                    </button>
                    <select id="period-select" onchange="changePeriod()" class="border rounded px-3 py-2 bg-white">
                        <option value="day">Today</option>
                        <option value="week">This Week</option>
                        <option value="month">This Month</option>
                        <option value="year">This Year</option>
                    </select>
                </div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Total Requests</div>
                    <div id="total-requests" class="text-2xl font-bold text-blue-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Total Tokens</div>
                    <div id="total-tokens" class="text-2xl font-bold text-green-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Req/sec</div>
                    <div id="rps" class="text-2xl font-bold text-orange-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Tokens/sec</div>
                    <div id="tps" class="text-2xl font-bold text-teal-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Errors</div>
                    <div id="total-errors" class="text-2xl font-bold text-red-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Error Rate</div>
                    <div id="error-rate" class="text-2xl font-bold text-purple-600">0%</div>
                </div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="text-sm font-semibold">Active Sessions</h3>
                        <span id="active-count" class="text-xs text-gray-500">0</span>
                    </div>
                    <div id="active-sessions" class="space-y-2 text-sm" style="height: 280px; overflow-y: auto;">No active sessions</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="text-sm font-semibold text-orange-600">Slow Requests (>60s)</h3>
                        <span id="slow-count" class="text-xs text-gray-500">0</span>
                    </div>
                    <div id="slow-requests" class="space-y-2 text-sm" style="height: 280px; overflow-y: auto;">No slow requests</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <h3 class="text-sm font-semibold mb-3">Provider Usage</h3>
                    <div id="provider-bars" class="space-y-2 text-sm" style="height: 280px; overflow-y: auto;"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <h3 class="text-sm font-semibold mb-3">API Key Usage</h3>
                    <div id="apikey-bars" class="space-y-2 text-sm" style="height: 280px; overflow-y: auto;"></div>
                </div>
            </div>
            <div class="bg-white rounded-lg shadow p-5 mb-6">
                <h3 class="text-lg font-semibold mb-4">Request Trend</h3>
                <canvas id="trendChart" height="80"></canvas>
            </div>
        </main>
    </div>
    <script>
        let currentPeriod = 'day';
        let trendChart = null;
        async function logout() { await fetch('/admin/api/auth/logout', {method: 'POST'}); window.location.href = '/admin/login'; }
        function getThemeMode() { return localStorage.getItem('admin_theme') || 'light'; }
        function getChartTheme() {
            const isDark = document.body.classList.contains('theme-dark');
            return {
                tickColor: isDark ? '#94a3b8' : '#6b7280',
                gridColor: isDark ? 'rgba(148, 163, 184, 0.16)' : 'rgba(148, 163, 184, 0.18)',
                titleColor: isDark ? '#cbd5e1' : '#4b5563',
                legendColor: isDark ? '#e5e7eb' : '#374151',
                tooltipBg: isDark ? '#0f172a' : '#ffffff',
                tooltipTitle: isDark ? '#f8fafc' : '#111827',
                tooltipBody: isDark ? '#cbd5e1' : '#374151',
                tooltipBorder: isDark ? '#334155' : '#e5e7eb'
            };
        }
        function applyTheme(mode) {
            const isDark = mode === 'dark';
            document.body.classList.toggle('theme-dark', isDark);
            localStorage.setItem('admin_theme', mode);
            document.getElementById('theme-toggle').textContent = isDark ? 'Light Mode' : 'Dark Mode';
        }
        function toggleTheme() {
            const nextMode = getThemeMode() === 'dark' ? 'light' : 'dark';
            applyTheme(nextMode);
            loadData();
        }
        applyTheme(getThemeMode());
        async function fetchJsonOrRedirect(url, options) {
            const resp = await fetch(url, options);
            if (resp.status === 401) {
                window.location.href = '/admin/login';
                throw new Error('Unauthorized');
            }
            return await resp.json();
        }
        function changePeriod() { currentPeriod = document.getElementById('period-select').value; loadData(); }
        async function loadData() {
            const data = await fetchJsonOrRedirect('/admin/api/stats/period?period=' + currentPeriod);
            document.getElementById('total-requests').textContent = data.total_requests.toLocaleString();
            document.getElementById('total-tokens').textContent = formatCompactTokens(data.total_tokens || 0);
            document.getElementById('total-errors').textContent = data.total_errors;
            const errorRate = data.total_requests > 0 ? ((data.total_errors / data.total_requests) * 100).toFixed(1) : 0;
            document.getElementById('error-rate').textContent = errorRate + '%';
            renderProviderBars(data.providers || {});
            renderApiKeyBars(data.api_keys || {});
            loadChart();
        }
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
        function renderModelList(models, accentClass) {
            const items = Object.entries(models || {})
                .filter(([, m]) => (m.requests || 0) > 0)
                .sort((a, b) => (b[1].tokens || 0) - (a[1].tokens || 0) || (b[1].requests || 0) - (a[1].requests || 0))
                .map(([model, m]) => `<div class="flex justify-between gap-2 text-[11px] text-gray-500"><span class="truncate ${accentClass}">${model}</span><span class="shrink-0">${m.requests} / ${formatCompactTokens(m.tokens || 0)}</span></div>`)
                .join('');
            return items ? `<div class="mt-2 space-y-1 border-l-2 border-gray-100 pl-2">${items}</div>` : '';
        }
        function renderProviderBars(providers) {
            const entries = Object.entries(providers)
                .sort((a, b) => (b[1].tokens || 0) - (a[1].tokens || 0) || (b[1].requests || 0) - (a[1].requests || 0));
            const maxTokens = Math.max(...entries.map(([, p]) => p.tokens || 0), 1);
            const html = entries.map(([name, p]) => {
                const pct = ((p.tokens || 0) / maxTokens) * 100;
                const modelsHtml = renderModelList(p.models, 'text-gray-600');
                return `<div class="rounded p-2 bg-gray-50"><div class="flex justify-between text-xs mb-1 gap-2"><span class="font-medium truncate">${name}</span><span class="text-gray-500 shrink-0">${p.requests} req / ${formatCompactTokens(p.tokens || 0)}</span></div><div class="w-full bg-gray-200 rounded-full h-1.5"><div class="bg-blue-500 h-1.5 rounded-full" style="width: ${pct}%"></div></div>${modelsHtml}</div>`;
            }).join('');
            document.getElementById('provider-bars').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No data</div>';
        }
        function renderApiKeyBars(apiKeys) {
            const entries = Object.entries(apiKeys)
                .sort((a, b) => (b[1].tokens || 0) - (a[1].tokens || 0) || (b[1].requests || 0) - (a[1].requests || 0));
            const maxTokens = Math.max(...entries.map(([, k]) => k.tokens || 0), 1);
            const html = entries.map(([name, k]) => {
                const pct = ((k.tokens || 0) / maxTokens) * 100;
                const modelsHtml = renderModelList(k.models, 'text-gray-600');
                return `<div class="rounded p-2 bg-gray-50"><div class="flex justify-between text-xs mb-1 gap-2"><span class="font-medium truncate">${name}</span><span class="text-gray-500 shrink-0">${k.requests} req / ${formatCompactTokens(k.tokens || 0)}</span></div><div class="w-full bg-gray-200 rounded-full h-1.5"><div class="bg-green-500 h-1.5 rounded-full" style="width: ${pct}%"></div></div>${modelsHtml}</div>`;
            }).join('');
            document.getElementById('apikey-bars').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No data</div>';
        }
        async function loadChart() {
            const data = await fetchJsonOrRedirect('/admin/api/stats/chart?period=' + currentPeriod);
            const ctx = document.getElementById('trendChart').getContext('2d');
            const chartTheme = getChartTheme();
            const scrollY = window.scrollY;
            if (trendChart) trendChart.destroy();
            const requests = data.intervals.map(i => data.data[i]?.requests || 0);
            const rawTokens = data.intervals.map(i => data.data[i]?.tokens || 0);
            const tokenScale = getTokenChartScale(requests, rawTokens);
            const tokens = rawTokens.map(v => Number((v / tokenScale.divisor).toFixed(2)));
            const tokenLabel = tokenScale.suffix ? `Tokens (${tokenScale.suffix})` : 'Tokens';
            trendChart = new Chart(ctx, {
                data: {
                    labels: data.intervals,
                    datasets: [
                        {
                            type: 'bar',
                            label: 'Requests',
                            data: requests,
                            backgroundColor: 'rgba(59, 130, 246, 0.45)',
                            borderColor: 'rgba(59, 130, 246, 0.9)',
                            borderWidth: 1,
                            borderRadius: 4,
                            yAxisID: 'yRequests'
                        },
                        {
                            type: 'line',
                            label: tokenLabel,
                            data: tokens,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.12)',
                            pointBackgroundColor: '#10b981',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 1,
                            pointRadius: 3,
                            pointHoverRadius: 4,
                            borderWidth: 2,
                            tension: 0.25,
                            fill: true,
                            yAxisID: 'yTokens'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: {
                            grid: { color: chartTheme.gridColor },
                            ticks: {
                                color: chartTheme.tickColor,
                                autoSkip: true,
                                maxRotation: 0,
                                minRotation: 0,
                                maxTicksLimit: currentPeriod === 'week' ? 10 : 12
                            }
                        },
                        yRequests: {
                            beginAtZero: true,
                            position: 'left',
                            grid: { color: chartTheme.gridColor },
                            ticks: { color: chartTheme.tickColor },
                            title: { display: true, text: 'Requests', color: chartTheme.titleColor }
                        },
                        yTokens: {
                            beginAtZero: true,
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            ticks: { color: chartTheme.tickColor },
                            title: { display: true, text: tokenLabel, color: chartTheme.titleColor }
                        }
                    },
                    plugins: {
                        legend: { position: 'top', labels: { color: chartTheme.legendColor } },
                        tooltip: {
                            backgroundColor: chartTheme.tooltipBg,
                            titleColor: chartTheme.tooltipTitle,
                            bodyColor: chartTheme.tooltipBody,
                            borderColor: chartTheme.tooltipBorder,
                            borderWidth: 1,
                            callbacks: {
                                label: function(context) {
                                    if (context.dataset.yAxisID === 'yTokens') {
                                        const rawValue = rawTokens[context.dataIndex] || 0;
                                        return `${tokenLabel}: ${formatCompactTokens(rawValue)} (${rawValue.toLocaleString()})`;
                                    }
                                    return `Requests: ${(context.parsed.y || 0).toLocaleString()}`;
                                }
                            }
                        }
                    }
                }
            });
            window.scrollTo(0, scrollY);
        }
        loadData();
        setInterval(loadData, 10000);
        loadActiveSessions();
        setInterval(loadActiveSessions, 60000);
        
        async function loadActiveSessions() {
            const data = await fetchJsonOrRedirect('/admin/api/stats/active');
            document.getElementById('active-count').textContent = data.active_count;
            
            if (data.active_count === 0) {
                document.getElementById('active-sessions').innerHTML = '<div class="text-gray-400 text-center py-4">No active sessions</div>';
                return;
            }
            
            const html = Object.entries(data.sessions).map(([name, session]) => {
                const modelsHtml = Object.entries(session.models).map(([model, count]) => 
                    `<span class="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">${model} (${count})</span>`
                ).join(' ');
                return `
                    <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                        <div>
                            <div class="font-medium">${name}</div>
                            <div class="text-xs text-gray-500 mt-1">${modelsHtml}</div>
                        </div>
                        <div class="text-right">
                            <div class="text-sm font-medium">${session.requests} req</div>
                        </div>
                    </div>
                `;
            }).join('');
            document.getElementById('active-sessions').innerHTML = html;
        }
        
        function formatDuration(seconds) {
            if (seconds >= 60) {
                const mins = Math.floor(seconds / 60);
                const secs = Math.floor(seconds % 60);
                return `${mins}m ${secs}s`;
            }
            return `${seconds.toFixed(1)}s`;
        }
        
        async function loadSlowRequests() {
            const data = await fetchJsonOrRedirect('/admin/api/stats/slow');
            
            const pending = data.pending || [];
            const completed = data.completed || [];
            const total = pending.length + completed.length;
            
            document.getElementById('slow-count').textContent = total;
            
            if (total === 0) {
                document.getElementById('slow-requests').innerHTML = '<div class="text-gray-400 text-center py-4">No slow requests</div>';
                return;
            }
            
            let html = '';
            
            pending.forEach(req => {
                const startTime = req.start_time ? new Date(req.start_time).toLocaleTimeString() : '';
                html += `
                    <div class="flex justify-between items-center p-2 bg-orange-50 rounded border-l-4 border-orange-500 mb-2">
                        <div>
                            <div class="font-medium text-sm">${req.provider} / ${req.model}</div>
                            <div class="text-xs text-gray-500">${startTime} | ${req.key_name}</div>
                        </div>
                        <div class="text-right">
                            <div class="text-lg font-bold text-orange-600">${formatDuration(req.elapsed_seconds)}</div>
                        </div>
                    </div>
                `;
            });
            
            completed.slice(0, 5).forEach(req => {
                const statusClass = req.status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';
                const createdAt = req.created_at ? new Date(req.created_at).toLocaleTimeString() : '';
                html += `
                    <div class="flex justify-between items-center p-2 bg-gray-50 rounded mb-2">
                        <div>
                            <div class="font-medium text-sm">${req.provider || 'N/A'} / ${req.model}</div>
                            <div class="text-xs text-gray-500">${createdAt} | ${req.key_name || 'N/A'}</div>
                        </div>
                        <div class="text-right">
                            <div class="text-sm font-bold text-orange-600">${formatDuration(req.latency_ms / 1000)}</div>
                            <span class="px-1.5 py-0.5 rounded text-xs ${statusClass}">${req.status}</span>
                        </div>
                    </div>
                `;
            });
            
            document.getElementById('slow-requests').innerHTML = html;
        }
        
        async function loadRealtimeStats() {
            const data = await fetchJsonOrRedirect('/admin/api/stats/realtime');
            document.getElementById('rps').textContent = data.requests_per_second;
            document.getElementById('tps').textContent = formatCompactTokens(data.tokens_per_second || 0);
        }
        
        loadSlowRequests();
        setInterval(loadSlowRequests, 5000);
        loadRealtimeStats();
        setInterval(loadRealtimeStats, 10000);
    </script>
</body>
</html>
"""
