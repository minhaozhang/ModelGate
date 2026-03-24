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
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="flex">
        <nav class="w-56 bg-white shadow-lg min-h-screen fixed">
            <div class="p-4 border-b"><h1 class="text-xl font-bold text-gray-800">API Proxy</h1></div>
            <div class="py-2">
                <a href="/home" class="nav-link active flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                    Home
                </a>
                <a href="/config" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                    Config
                </a>
                <a href="/api-keys" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"></path></svg>
                    API Keys
                </a>
                <a href="/monitor" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                    Monitor
                </a>
                <a href="/usage" class="nav-link flex items-center px-4 py-3 text-gray-700">
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
                <select id="period-select" onchange="changePeriod()" class="border rounded px-3 py-2 bg-white">
                    <option value="day">Today</option>
                    <option value="week">This Week</option>
                    <option value="month">This Month</option>
                    <option value="year">This Year</option>
                </select>
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
            <div class="bg-white rounded-lg shadow p-5 mb-6">
                <h3 class="text-lg font-semibold mb-4">Request Trend</h3>
                <canvas id="trendChart" height="80"></canvas>
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
        </main>
    </div>
    <script>
        let currentPeriod = 'day';
        let trendChart = null;
        async function logout() { await fetch('/api/logout', {method: 'POST'}); window.location.href = '/login'; }
        function changePeriod() { currentPeriod = document.getElementById('period-select').value; loadData(); }
        async function loadData() {
            const resp = await fetch('/stats/period?period=' + currentPeriod);
            const data = await resp.json();
            document.getElementById('total-requests').textContent = data.total_requests.toLocaleString();
            document.getElementById('total-tokens').textContent = data.total_tokens.toLocaleString();
            document.getElementById('total-errors').textContent = data.total_errors;
            const errorRate = data.total_requests > 0 ? ((data.total_errors / data.total_requests) * 100).toFixed(1) : 0;
            document.getElementById('error-rate').textContent = errorRate + '%';
            renderProviderBars(data.providers || {});
            renderApiKeyBars(data.api_keys || {});
            loadChart();
        }
        function renderProviderBars(providers) {
            const maxReq = Math.max(...Object.values(providers).map(p => p.requests), 1);
            const html = Object.entries(providers).map(([name, p]) => {
                const pct = (p.requests / maxReq) * 100;
                return `<div class="rounded p-1"><div class="flex justify-between text-xs mb-1"><span class="font-medium truncate">${name}</span><span class="text-gray-500 ml-1">${p.requests}</span></div><div class="w-full bg-gray-200 rounded-full h-1.5"><div class="bg-blue-500 h-1.5 rounded-full" style="width: ${pct}%"></div></div></div>`;
            }).join('');
            document.getElementById('provider-bars').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No data</div>';
        }
        function renderApiKeyBars(apiKeys) {
            const maxReq = Math.max(...Object.values(apiKeys).map(k => k.requests), 1);
            const html = Object.entries(apiKeys).map(([name, k]) => {
                const pct = (k.requests / maxReq) * 100;
                return `<div class="rounded p-1"><div class="flex justify-between text-xs mb-1"><span class="font-medium truncate">${name}</span><span class="text-gray-500 ml-1">${k.requests}</span></div><div class="w-full bg-gray-200 rounded-full h-1.5"><div class="bg-green-500 h-1.5 rounded-full" style="width: ${pct}%"></div></div></div>`;
            }).join('');
            document.getElementById('apikey-bars').innerHTML = html || '<div class="text-gray-400 text-center py-2 text-xs">No data</div>';
        }
        async function loadChart() {
            const resp = await fetch('/stats/chart?period=' + currentPeriod);
            const data = await resp.json();
            const ctx = document.getElementById('trendChart').getContext('2d');
            const scrollY = window.scrollY;
            if (trendChart) trendChart.destroy();
            const requests = data.intervals.map(i => data.data[i]?.requests || 0);
            const tokens = data.intervals.map(i => Math.floor((data.data[i]?.tokens || 0) / 1000));
            trendChart = new Chart(ctx, {
                type: 'bar',
                data: { labels: data.intervals, datasets: [{ label: 'Requests', data: requests, backgroundColor: '#3b82f6', borderRadius: 4 }, { label: 'Tokens (K)', data: tokens, backgroundColor: '#10b981', borderRadius: 4 }] },
                options: { responsive: true, maintainAspectRatio: true, scales: { y: { beginAtZero: true } }, plugins: { legend: { position: 'top' } } }
            });
            window.scrollTo(0, scrollY);
        }
        loadData();
        setInterval(loadData, 10000);
        loadActiveSessions();
        setInterval(loadActiveSessions, 60000);
        
        async function loadActiveSessions() {
            const resp = await fetch('/stats/active');
            const data = await resp.json();
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
        
        async function loadSlowRequests() {
            const resp = await fetch('/stats/slow');
            const data = await resp.json();
            
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
                            <div class="text-lg font-bold text-orange-600">${req.elapsed_seconds}s</div>
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
                            <div class="text-sm font-bold text-orange-600">${(req.latency_ms / 1000).toFixed(1)}s</div>
                            <span class="px-1.5 py-0.5 rounded text-xs ${statusClass}">${req.status}</span>
                        </div>
                    </div>
                `;
            });
            
            document.getElementById('slow-requests').innerHTML = html;
        }
        
        async function loadRealtimeStats() {
            const resp = await fetch('/stats/realtime');
            const data = await resp.json();
            document.getElementById('rps').textContent = data.requests_per_second;
            document.getElementById('tps').textContent = data.tokens_per_second;
        }
        
        loadSlowRequests();
        setInterval(loadSlowRequests, 5000);
        loadRealtimeStats();
        setInterval(loadRealtimeStats, 1000);
    </script>
</body>
</html>
"""
