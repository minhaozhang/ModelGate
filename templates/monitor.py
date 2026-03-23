MONITOR_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Monitor - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
        .stat-card { transition: transform 0.2s, box-shadow 0.2s; }
        .stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .bar-item { transition: all 0.2s; }
        .bar-item:hover { background: #f8fafc; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="flex">
        <nav class="w-56 bg-white shadow-lg min-h-screen fixed">
            <div class="p-4 border-b"><h1 class="text-xl font-bold text-gray-800">API Proxy</h1></div>
            <div class="py-2">
                <a href="/home" class="nav-link flex items-center px-4 py-3 text-gray-700">
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
                <a href="/monitor" class="nav-link active flex items-center px-4 py-3 text-gray-700">
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
                <h2 class="text-2xl font-bold text-gray-800">Statistics Monitor</h2>
                <div class="flex gap-2">
                    <div class="flex bg-white rounded border overflow-hidden">
                        <button onclick="setPeriod('day')" id="btn-day" class="px-4 py-2 text-sm font-medium bg-blue-500 text-white">Day</button>
                        <button onclick="setPeriod('week')" id="btn-week" class="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100">Week</button>
                        <button onclick="setPeriod('month')" id="btn-month" class="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100">Month</button>
                        <button onclick="setPeriod('year')" id="btn-year" class="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100">Year</button>
                    </div>
                </div>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Total Requests</div>
                    <div id="total-requests" class="text-3xl font-bold text-blue-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Total Tokens</div>
                    <div id="total-tokens" class="text-3xl font-bold text-green-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Errors</div>
                    <div id="total-errors" class="text-3xl font-bold text-red-600">0</div>
                </div>
                <div class="stat-card bg-white rounded-lg shadow p-5">
                    <div class="text-gray-500 text-sm mb-1">Error Rate</div>
                    <div id="error-rate" class="text-3xl font-bold text-orange-600">0%</div>
                </div>
            </div>
            
            <div class="bg-white rounded-lg shadow p-5 mb-6">
                <h3 class="text-lg font-semibold mb-4">Request Trend</h3>
                <canvas id="trendChart" height="80"></canvas>
            </div>
            
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Provider Usage</h3>
                    <div id="provider-bars" class="space-y-2 max-h-80 overflow-y-auto"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">API Key Usage</h3>
                    <div id="apikey-bars" class="space-y-2 max-h-80 overflow-y-auto"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Model Usage</h3>
                    <div id="model-bars" class="space-y-2 max-h-80 overflow-y-auto"></div>
                </div>
            </div>
        </main>
    </div>
    
    <script>
        let currentPeriod = 'day';
        let trendChart = null;
        
        async function logout() {
            await fetch('/api/logout', {method: 'POST'});
            window.location.href = '/login';
        }
        
        function setPeriod(period) {
            currentPeriod = period;
            document.querySelectorAll('[id^="btn-"]').forEach(btn => {
                btn.classList.remove('bg-blue-500', 'text-white');
                btn.classList.add('text-gray-600', 'hover:bg-gray-100');
            });
            document.getElementById('btn-' + period).classList.add('bg-blue-500', 'text-white');
            document.getElementById('btn-' + period).classList.remove('text-gray-600', 'hover:bg-gray-100');
            loadData();
        }
        
        async function loadData() {
            const [providerData, apikeyData, modelData, trendData] = await Promise.all([
                fetch('/stats/aggregate?dimension=provider&period=' + currentPeriod).then(r => r.json()),
                fetch('/stats/aggregate?dimension=api_key&period=' + currentPeriod).then(r => r.json()),
                fetch('/stats/aggregate?dimension=model&period=' + currentPeriod).then(r => r.json()),
                fetch('/stats/trend?dimension=provider&period=' + currentPeriod).then(r => r.json())
            ]);
            
            const totalRequests = providerData.total_requests || 0;
            const totalTokens = providerData.total_tokens || 0;
            const totalErrors = providerData.total_errors || 0;
            
            document.getElementById('total-requests').textContent = totalRequests.toLocaleString();
            document.getElementById('total-tokens').textContent = totalTokens.toLocaleString();
            document.getElementById('total-errors').textContent = totalErrors;
            const errorRate = totalRequests > 0 ? ((totalErrors / totalRequests) * 100).toFixed(1) : 0;
            document.getElementById('error-rate').textContent = errorRate + '%';
            
            renderBarChart('provider-bars', providerData.data || {}, '#3b82f6');
            renderBarChart('apikey-bars', apikeyData.data || {}, '#10b981');
            renderBarChart('model-bars', modelData.data || {}, '#8b5cf6');
            renderTrendChart(trendData);
        }
        
        function renderBarChart(containerId, data, color) {
            const entries = Object.entries(data).sort((a, b) => b[1].requests - a[1].requests);
            const maxReq = Math.max(...entries.map(e => e[1].requests), 1);
            
            const html = entries.map(([name, stats]) => {
                const pct = (stats.requests / maxReq) * 100;
                return `
                <div class="bar-item rounded p-2">
                    <div class="flex justify-between text-sm mb-1">
                        <span class="font-medium truncate max-w-[120px]" title="${name}">${name}</span>
                        <span class="text-gray-500 ml-2">${stats.requests.toLocaleString()} / ${stats.tokens.toLocaleString()} tok</span>
                    </div>
                    <div class="w-full bg-gray-200 rounded-full h-2">
                        <div class="h-2 rounded-full" style="width: ${pct}%; background: ${color}"></div>
                    </div>
                </div>`;
            }).join('');
            
            document.getElementById(containerId).innerHTML = html || '<div class="text-gray-400 text-center py-4">No data</div>';
        }
        
        function renderTrendChart(data) {
            const ctx = document.getElementById('trendChart').getContext('2d');
            if (trendChart) trendChart.destroy();
            
            const requests = data.intervals.map(i => data.data[i]?.requests || 0);
            const tokens = data.intervals.map(i => Math.floor((data.data[i]?.tokens || 0) / 1000));
            
            trendChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: data.intervals,
                    datasets: [
                        { label: 'Requests', data: requests, backgroundColor: '#3b82f6', borderRadius: 4 },
                        { label: 'Tokens (K)', data: tokens, backgroundColor: '#10b981', borderRadius: 4 }
                    ]
                },
                options: {
                    responsive: true,
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { position: 'top' } }
                }
            });
        }
        
        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""
