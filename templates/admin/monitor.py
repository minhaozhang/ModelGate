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
        .stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="flex">
        <nav class="w-56 bg-white shadow-lg min-h-screen fixed">
            <div class="p-4 border-b"><h1 class="text-xl font-bold text-gray-800">API Proxy</h1></div>
            <div class="py-2">
                <a href="/admin/home" class="nav-link flex items-center px-4 py-3 text-gray-700">
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
                <a href="/admin/monitor" class="nav-link active flex items-center px-4 py-3 text-gray-700">
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
                <div>
                    <h2 class="text-2xl font-bold text-gray-800">Statistics Monitor</h2>
                    <p class="text-sm text-gray-500 mt-1">Composition, concentration, hotspots, and trend behavior</p>
                </div>
                <div class="flex bg-white rounded border overflow-hidden">
                    <button onclick="setPeriod('day')" id="btn-day" class="px-4 py-2 text-sm font-medium bg-blue-500 text-white">Day</button>
                    <button onclick="setPeriod('week')" id="btn-week" class="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100">Week</button>
                    <button onclick="setPeriod('month')" id="btn-month" class="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100">Month</button>
                    <button onclick="setPeriod('year')" id="btn-year" class="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100">Year</button>
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
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-semibold">Request Trend</h3>
                    <div id="trend-meta" class="text-sm text-gray-500">Requests / Tokens / Errors</div>
                </div>
                <canvas id="trendChart" height="80"></canvas>
            </div>

            <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Provider Usage</h3>
                    <div class="h-64"><canvas id="providerChart"></canvas></div>
                    <div id="provider-legend" class="mt-4 space-y-2 max-h-64 overflow-y-auto"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">API Key Usage</h3>
                    <div class="h-64"><canvas id="apikeyChart"></canvas></div>
                    <div id="apikey-legend" class="mt-4 space-y-2 max-h-64 overflow-y-auto"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Model Usage</h3>
                    <div class="h-64"><canvas id="modelChart"></canvas></div>
                    <div id="model-legend" class="mt-4 space-y-2 max-h-64 overflow-y-auto"></div>
                </div>
            </div>

            <div class="grid grid-cols-1 xl:grid-cols-3 gap-6 mt-6">
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Traffic Concentration</h3>
                    <div id="concentration-cards" class="space-y-3"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Error Hotspots</h3>
                    <div id="error-hotspots" class="space-y-3"></div>
                </div>
                <div class="bg-white rounded-lg shadow p-5">
                    <h3 class="text-lg font-semibold mb-4">Active Footprint</h3>
                    <div id="footprint-cards" class="space-y-3"></div>
                </div>
            </div>
        </main>
    </div>

    <script>
        let currentPeriod = 'day';
        let trendChart = null;
        let providerChart = null;
        let apikeyChart = null;
        let modelChart = null;
        const chartPalette = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#f97316', '#6366f1'];

        async function logout() {
            await fetch('/admin/api/auth/logout', { method: 'POST' });
            window.location.href = '/admin/login';
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

        function formatCompactTokens(tokens) {
            const value = Number(tokens || 0);
            if (value >= 1000000) return (value / 1000000).toFixed(1).replace(/\\.0$/, '') + 'M';
            if (value >= 1000) return (value / 1000).toFixed(1).replace(/\\.0$/, '') + 'K';
            if (Number.isInteger(value)) return value.toLocaleString();
            return value.toFixed(1).replace(/\\.0$/, '');
        }

        function formatPct(value, digits = 1) {
            return `${(Number(value || 0) * 100).toFixed(digits)}%`;
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

        function buildDonutSeries(data, metric = 'tokens', limit = 5) {
            const entries = Object.entries(data || {})
                .sort((a, b) => (b[1][metric] || 0) - (a[1][metric] || 0))
                .filter(([, stats]) => (stats[metric] || 0) > 0);
            const topEntries = entries.slice(0, limit);
            const otherValue = entries.slice(limit).reduce((sum, [, stats]) => sum + (stats[metric] || 0), 0);
            const labels = topEntries.map(([name]) => name);
            const values = topEntries.map(([, stats]) => stats[metric] || 0);
            const colors = topEntries.map((_, index) => chartPalette[index % chartPalette.length]);
            if (otherValue > 0) {
                labels.push('Others');
                values.push(otherValue);
                colors.push('#cbd5e1');
            }
            return { entries, labels, values, colors };
        }

        function renderDonutChart(currentChart, canvasId, legendId, data, accentColor) {
            const series = buildDonutSeries(data, 'tokens', 5);
            const canvas = document.getElementById(canvasId);
            if (currentChart) currentChart.destroy();

            const chart = new Chart(canvas.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: series.labels,
                    datasets: [{
                        data: series.values,
                        backgroundColor: series.colors,
                        borderWidth: 0,
                        hoverOffset: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '62%',
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const total = series.values.reduce((sum, value) => sum + value, 0) || 1;
                                    const pct = context.raw / total;
                                    return `${context.label}: ${formatCompactTokens(context.raw)} (${formatPct(pct)})`;
                                }
                            }
                        }
                    }
                }
            });

            const total = series.entries.reduce((sum, [, stats]) => sum + (stats.tokens || 0), 0) || 1;
            const legendHtml = series.entries.slice(0, 6).map(([name, stats], index) => {
                const pct = (stats.tokens || 0) / total;
                const errRate = stats.requests ? stats.errors / stats.requests : 0;
                const color = chartPalette[index % chartPalette.length];
                return `
                    <div class="rounded-lg border border-gray-100 p-3">
                        <div class="flex items-start justify-between gap-3">
                            <div class="min-w-0">
                                <div class="flex items-center gap-2">
                                    <span class="inline-block h-2.5 w-2.5 rounded-full" style="background:${color}"></span>
                                    <div class="font-medium text-sm truncate" title="${name}">${name}</div>
                                </div>
                                <div class="mt-1 text-xs text-gray-500">${stats.requests.toLocaleString()} req / ${formatCompactTokens(stats.tokens || 0)} tok</div>
                            </div>
                            <div class="text-right shrink-0">
                                <div class="text-sm font-semibold" style="color:${accentColor}">${formatPct(pct)}</div>
                                <div class="text-xs text-gray-400">err ${formatPct(errRate, 1)}</div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            document.getElementById(legendId).innerHTML = legendHtml || '<div class="text-gray-400 text-center py-4">No data</div>';
            return { chart, entries: series.entries };
        }

        function renderConcentrationCards(providerEntries, apikeyEntries, modelEntries) {
            const sections = [
                ['Providers', providerEntries],
                ['API Keys', apikeyEntries],
                ['Models', modelEntries]
            ];
            const html = sections.map(([label, entries]) => {
                const total = entries.reduce((sum, [, stats]) => sum + (stats.tokens || 0), 0) || 1;
                const top1 = entries[0];
                const top3Value = entries.slice(0, 3).reduce((sum, [, stats]) => sum + (stats.tokens || 0), 0);
                return `
                    <div class="rounded-lg bg-slate-50 p-4">
                        <div class="text-xs uppercase tracking-wide text-slate-500">${label}</div>
                        <div class="mt-2 text-sm font-medium text-slate-800 truncate" title="${top1 ? top1[0] : 'No data'}">${top1 ? top1[0] : 'No data'}</div>
                        <div class="mt-1 text-xs text-slate-500">Top 1 share ${top1 ? formatPct((top1[1].tokens || 0) / total) : '0%'}</div>
                        <div class="mt-3 h-2 rounded-full bg-slate-200 overflow-hidden">
                            <div class="h-full bg-slate-700" style="width:${Math.min((top3Value / total) * 100, 100)}%"></div>
                        </div>
                        <div class="mt-2 text-xs text-slate-500">Top 3 combined ${formatPct(top3Value / total)}</div>
                    </div>
                `;
            }).join('');
            document.getElementById('concentration-cards').innerHTML = html;
        }

        function renderErrorHotspots(providerEntries, apikeyEntries, modelEntries) {
            const hotspots = [
                ...providerEntries.map(([name, stats]) => ({ scope: 'Provider', name, stats })),
                ...apikeyEntries.map(([name, stats]) => ({ scope: 'API Key', name, stats })),
                ...modelEntries.map(([name, stats]) => ({ scope: 'Model', name, stats }))
            ]
            .filter(item => (item.stats.requests || 0) >= 3)
            .map(item => ({ ...item, errorRate: item.stats.requests ? item.stats.errors / item.stats.requests : 0 }))
            .sort((a, b) => b.errorRate - a.errorRate || (b.stats.errors || 0) - (a.stats.errors || 0))
            .slice(0, 6);

            const html = hotspots.map(item => `
                <div class="rounded-lg border border-red-100 bg-red-50 p-3">
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <div class="text-xs uppercase tracking-wide text-red-500">${item.scope}</div>
                            <div class="mt-1 font-medium text-sm truncate" title="${item.name}">${item.name}</div>
                            <div class="mt-1 text-xs text-red-400">${item.stats.errors.toLocaleString()} errors / ${item.stats.requests.toLocaleString()} requests</div>
                        </div>
                        <div class="text-right shrink-0">
                            <div class="text-lg font-bold text-red-600">${formatPct(item.errorRate, 1)}</div>
                        </div>
                    </div>
                </div>
            `).join('');

            document.getElementById('error-hotspots').innerHTML = html || '<div class="text-gray-400 text-center py-4">No hotspots</div>';
        }

        function renderFootprintCards(providerEntries, apikeyEntries, modelEntries) {
            const cards = [
                {
                    label: 'Active Providers',
                    value: providerEntries.length,
                    detail: providerEntries[0] ? `Top: ${providerEntries[0][0]}` : 'No traffic'
                },
                {
                    label: 'Active API Keys',
                    value: apikeyEntries.length,
                    detail: apikeyEntries[0] ? `Top: ${apikeyEntries[0][0]}` : 'No traffic'
                },
                {
                    label: 'Active Models',
                    value: modelEntries.length,
                    detail: modelEntries[0] ? `Top: ${modelEntries[0][0]}` : 'No traffic'
                }
            ];

            const html = cards.map(card => `
                <div class="rounded-lg border border-gray-100 bg-gray-50 p-4">
                    <div class="text-xs uppercase tracking-wide text-gray-500">${card.label}</div>
                    <div class="mt-2 text-2xl font-bold text-gray-800">${card.value.toLocaleString()}</div>
                    <div class="mt-1 text-sm text-gray-500 truncate" title="${card.detail}">${card.detail}</div>
                </div>
            `).join('');

            document.getElementById('footprint-cards').innerHTML = html;
        }

        function renderTrendChart(data) {
            const ctx = document.getElementById('trendChart').getContext('2d');
            if (trendChart) trendChart.destroy();

            const requests = data.intervals.map(label => data.data[label]?.requests || 0);
            const rawTokens = data.intervals.map(label => data.data[label]?.tokens || 0);
            const errors = data.intervals.map(label => data.data[label]?.errors || 0);
            const tokenScale = getTokenChartScale(requests, rawTokens);
            const tokens = rawTokens.map(value => Number((value / tokenScale.divisor).toFixed(2)));
            const tokenLabel = tokenScale.suffix ? `Tokens (${tokenScale.suffix})` : 'Tokens';
            document.getElementById('trend-meta').textContent = `${tokenLabel} on right axis`;

            trendChart = new Chart(ctx, {
                data: {
                    labels: data.intervals,
                    datasets: [
                        {
                            type: 'bar',
                            label: 'Requests',
                            data: requests,
                            backgroundColor: 'rgba(59, 130, 246, 0.35)',
                            borderColor: 'rgba(59, 130, 246, 0.85)',
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
                            pointRadius: 3,
                            pointHoverRadius: 4,
                            borderWidth: 2,
                            tension: 0.25,
                            fill: true,
                            yAxisID: 'yTokens'
                        },
                        {
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
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: {
                            ticks: {
                                autoSkip: true,
                                maxRotation: 0,
                                minRotation: 0,
                                maxTicksLimit: currentPeriod === 'week' ? 10 : 12
                            }
                        },
                        yRequests: {
                            beginAtZero: true,
                            position: 'left',
                            title: { display: true, text: 'Requests / Errors' }
                        },
                        yTokens: {
                            beginAtZero: true,
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: tokenLabel }
                        }
                    },
                    plugins: {
                        legend: { position: 'top' },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    if (context.dataset.yAxisID === 'yTokens') {
                                        const rawValue = rawTokens[context.dataIndex] || 0;
                                        return `${tokenLabel}: ${formatCompactTokens(rawValue)} (${rawValue.toLocaleString()})`;
                                    }
                                    return `${context.dataset.label}: ${(context.parsed.y || 0).toLocaleString()}`;
                                }
                            }
                        }
                    }
                }
            });
        }

        async function loadData() {
            const [providerData, apikeyData, modelData, trendData] = await Promise.all([
                fetch('/admin/api/stats/aggregate?dimension=provider&period=' + currentPeriod).then(r => r.json()),
                fetch('/admin/api/stats/aggregate?dimension=api_key&period=' + currentPeriod).then(r => r.json()),
                fetch('/admin/api/stats/aggregate?dimension=model&period=' + currentPeriod).then(r => r.json()),
                fetch('/admin/api/stats/trend?dimension=provider&period=' + currentPeriod).then(r => r.json())
            ]);

            const totalRequests = providerData.total_requests || 0;
            const totalTokens = providerData.total_tokens || 0;
            const totalErrors = providerData.total_errors || 0;

            document.getElementById('total-requests').textContent = totalRequests.toLocaleString();
            document.getElementById('total-tokens').textContent = formatCompactTokens(totalTokens);
            document.getElementById('total-errors').textContent = totalErrors.toLocaleString();
            document.getElementById('error-rate').textContent = (totalRequests > 0 ? ((totalErrors / totalRequests) * 100).toFixed(1) : '0.0') + '%';

            const providerResult = renderDonutChart(providerChart, 'providerChart', 'provider-legend', providerData.data || {}, '#2563eb');
            providerChart = providerResult.chart;
            const apikeyResult = renderDonutChart(apikeyChart, 'apikeyChart', 'apikey-legend', apikeyData.data || {}, '#059669');
            apikeyChart = apikeyResult.chart;
            const modelResult = renderDonutChart(modelChart, 'modelChart', 'model-legend', modelData.data || {}, '#7c3aed');
            modelChart = modelResult.chart;

            renderConcentrationCards(providerResult.entries, apikeyResult.entries, modelResult.entries);
            renderErrorHotspots(providerResult.entries, apikeyResult.entries, modelResult.entries);
            renderFootprintCards(providerResult.entries, apikeyResult.entries, modelResult.entries);
            renderTrendChart(trendData);
        }

        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""
