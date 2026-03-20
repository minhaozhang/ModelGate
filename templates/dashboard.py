DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>API Proxy Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .log-entry { transition: all 0.2s; }
        .log-entry:hover { background: #f8fafc; }
        pre { white-space: pre-wrap; word-break: break-all; }
        .fade-in { animation: fadeIn 0.3s; }
        .tab-active { border-bottom: 2px solid #3b82f6; color: #3b82f6; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-6">API Proxy Dashboard</h1>
        
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
                <div class="text-gray-500 text-sm">Requests/min</div>
                <div id="rpm" class="text-2xl font-bold text-purple-600">0</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-gray-500 text-sm">Errors</div>
                <div id="errors" class="text-2xl font-bold text-red-600">0</div>
            </div>
        </div>
        
        <div class="bg-white rounded-lg shadow mb-6">
            <div class="flex border-b">
                <button onclick="switchTab('apikeys')" id="tab-apikeys" class="px-6 py-3 font-medium tab-active">API Keys</button>
                <button onclick="switchTab('providers')" id="tab-providers" class="px-6 py-3 font-medium text-gray-500 hover:text-gray-700">Providers</button>
                <button onclick="switchTab('stats')" id="tab-stats" class="px-6 py-3 font-medium text-gray-500 hover:text-gray-700">Stats</button>
                <button onclick="switchTab('logs')" id="tab-logs" class="px-6 py-3 font-medium text-gray-500 hover:text-gray-700">Logs</button>
            </div>
            
            <div id="panel-apikeys" class="p-4">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold">API Key Management</h2>
                    <button onclick="showAddApiKey()" class="bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600">+ Add API Key</button>
                </div>
                <div id="apikeys-list" class="space-y-2"></div>
            </div>
            
            <div id="panel-providers" class="p-4 hidden">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold">Provider Management</h2>
                    <button onclick="showAddProvider()" class="bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600">+ Add Provider</button>
                </div>
                <div id="providers-list" class="space-y-2"></div>
            </div>
            
            <div id="panel-stats" class="p-4 hidden">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <h2 class="text-lg font-semibold mb-3">Provider Stats</h2>
                        <div id="provider-stats" class="space-y-2"></div>
                    </div>
                    <div>
                        <h2 class="text-lg font-semibold mb-3">Model Stats</h2>
                        <div id="model-stats" class="space-y-2"></div>
                    </div>
                </div>
            </div>
            
            <div id="panel-logs" class="p-4 hidden">
                <div class="flex justify-between items-center mb-3">
                    <h2 class="text-lg font-semibold">Recent Requests</h2>
                    <div class="flex gap-2">
                        <select id="log-filter" class="border rounded px-2 py-1 text-sm">
                            <option value="all">All</option>
                            <option value="success">Success</option>
                            <option value="error">Errors</option>
                        </select>
                        <button onclick="loadLogs()" class="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">Refresh</button>
                    </div>
                </div>
                <div id="logs" class="space-y-2 max-h-96 overflow-y-auto"></div>
            </div>
        </div>
        
        <div id="apikey-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
            <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
                <div class="p-4 border-b flex justify-between items-center">
                    <h3 class="font-semibold" id="apikey-modal-title">Add API Key</h3>
                    <button onclick="closeApiKeyModal()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
                </div>
                <form id="apikey-form" class="p-4 space-y-4">
                    <input type="hidden" id="apikey-id">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Name</label>
                        <input type="text" id="apikey-name" required class="w-full border rounded px-3 py-2" placeholder="e.g., Project A, Client B">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Allowed Models (comma separated, empty = all)</label>
                        <input type="text" id="apikey-models" class="w-full border rounded px-3 py-2" placeholder="glm-4, deepseek-chat">
                    </div>
                    <div class="flex items-center">
                        <input type="checkbox" id="apikey-active" checked class="mr-2">
                        <label class="text-sm text-gray-700">Active</label>
                    </div>
                    <div class="flex gap-2">
                        <button type="submit" class="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">Save</button>
                        <button type="button" onclick="closeApiKeyModal()" class="px-4 py-2 border rounded hover:bg-gray-50">Cancel</button>
                    </div>
                </form>
            </div>
        </div>
        
        <div id="provider-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
            <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
                <div class="p-4 border-b flex justify-between items-center">
                    <h3 class="font-semibold" id="provider-modal-title">Add Provider</h3>
                    <button onclick="closeProviderModal()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
                </div>
                <form id="provider-form" class="p-4 space-y-4">
                    <input type="hidden" id="provider-id">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Name</label>
                        <input type="text" id="provider-name" required class="w-full border rounded px-3 py-2" placeholder="e.g., zhipu, deepseek">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
                        <input type="text" id="provider-url" required class="w-full border rounded px-3 py-2" placeholder="https://api.example.com/v1">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
                        <input type="password" id="provider-key" class="w-full border rounded px-3 py-2" placeholder="sk-...">
                    </div>
                    <div class="flex items-center">
                        <input type="checkbox" id="provider-active" checked class="mr-2">
                        <label class="text-sm text-gray-700">Active</label>
                    </div>
                    <div class="flex gap-2">
                        <button type="submit" class="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">Save</button>
                        <button type="button" onclick="closeProviderModal()" class="px-4 py-2 border rounded hover:bg-gray-50">Cancel</button>
                    </div>
                </form>
            </div>
        </div>
        
        <div id="detail-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
            <div class="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[80vh] overflow-hidden">
                <div class="p-4 border-b flex justify-between items-center">
                    <h3 class="font-semibold">Request Detail</h3>
                    <button onclick="closeModal()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
                </div>
                <div id="modal-content" class="p-4 overflow-y-auto max-h-[60vh]"></div>
            </div>
        </div>
    </div>
    
    <script>
        function switchTab(tab) {
            ['apikeys', 'providers', 'stats', 'logs'].forEach(t => {
                document.getElementById('panel-' + t).classList.add('hidden');
                document.getElementById('tab-' + t).classList.remove('tab-active');
                document.getElementById('tab-' + t).classList.add('text-gray-500');
            });
            document.getElementById('panel-' + tab).classList.remove('hidden');
            document.getElementById('tab-' + tab).classList.add('tab-active');
            document.getElementById('tab-' + tab).classList.remove('text-gray-500');
        }
        
        async function loadApiKeys() {
            const resp = await fetch('/api/keys');
            const data = await resp.json();
            const html = (data.api_keys || []).map(k => `
                <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                    <div>
                        <span class="font-medium">${k.name}</span>
                        <span class="ml-2 text-xs ${k.is_active ? 'text-green-600' : 'text-red-600'}">${k.is_active ? 'Active' : 'Inactive'}</span>
                        <div class="text-xs text-gray-500 font-mono flex items-center gap-1">
                            <span>${k.key}</span>
                            <button onclick="copyKey('${k.key}')" class="text-blue-500 hover:text-blue-700" title="Copy key">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
                            </button>
                        </div>
                        <div class="text-xs text-gray-400">Models: ${k.allowed_provider_model_ids.length ? k.allowed_provider_model_ids.length + ' selected' : 'All'}</div>
                    </div>
                    <div class="flex gap-2">
                        <a href="/api-keys/${k.id}/query" target="_blank" class="text-green-500 hover:text-green-700 text-sm">Query</a>
                        <button onclick="editApiKey(${k.id}, '${k.name}', [${k.allowed_provider_model_ids}], ${k.is_active})" class="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                        <button onclick="deleteApiKey(${k.id})" class="text-red-500 hover:text-red-700 text-sm">Delete</button>
                    </div>
                </div>
            `).join('');
            document.getElementById('apikeys-list').innerHTML = html || '<div class="text-gray-400 text-center py-4">No API keys</div>';
        }
        
        function copyKey(key) {
            navigator.clipboard.writeText(key).then(() => {
                alert('API Key copied!');
            }).catch(() => {
                prompt('Copy this key:', key);
            });
        }
        
        function showAddApiKey() {
            document.getElementById('apikey-modal-title').textContent = 'Add API Key';
            document.getElementById('apikey-id').value = '';
            document.getElementById('apikey-name').value = '';
            document.getElementById('apikey-models').value = '';
            document.getElementById('apikey-active').checked = true;
            document.getElementById('apikey-modal').classList.remove('hidden');
            document.getElementById('apikey-modal').classList.add('flex');
        }
        
        function editApiKey(id, name, modelIds, active) {
            document.getElementById('apikey-modal-title').textContent = 'Edit API Key';
            document.getElementById('apikey-id').value = id;
            document.getElementById('apikey-name').value = name;
            document.getElementById('apikey-models').value = modelIds.join(',');
            document.getElementById('apikey-active').checked = active;
            document.getElementById('apikey-modal').classList.remove('hidden');
            document.getElementById('apikey-modal').classList.add('flex');
        }
        
        function closeApiKeyModal() {
            document.getElementById('apikey-modal').classList.add('hidden');
            document.getElementById('apikey-modal').classList.remove('flex');
        }
        
        document.getElementById('apikey-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('apikey-id').value;
            const modelsStr = document.getElementById('apikey-models').value;
            const modelIds = modelsStr ? modelsStr.split(',').map(s => parseInt(s.trim())).filter(s => !isNaN(s)) : [];
            const data = {
                name: document.getElementById('apikey-name').value,
                allowed_provider_model_ids: modelIds,
                is_active: document.getElementById('apikey-active').checked
            };
            
            try {
                if (id) {
                    await fetch('/api/keys/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(data)
                    });
                } else {
                    const resp = await fetch('/api/keys', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(data)
                    });
                    const result = await resp.json();
                    alert('API Key created: ' + result.key + '\\nPlease save this key!');
                }
                closeApiKeyModal();
                loadApiKeys();
            } catch(err) {
                alert('Failed to save API key');
            }
        });
        
        async function deleteApiKey(id) {
            if (!confirm('Delete this API key?')) return;
            await fetch('/api/keys/' + id, {method: 'DELETE'});
            loadApiKeys();
        }
        
        async function loadProviders() {
            const resp = await fetch('/providers');
            const data = await resp.json();
            const html = (data.providers || []).map(p => `
                <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                    <div>
                        <span class="font-medium">${p.name}</span>
                        <span class="ml-2 text-xs ${p.is_active ? 'text-green-600' : 'text-red-600'}">${p.is_active ? 'Active' : 'Inactive'}</span>
                        <div class="text-xs text-gray-500">${p.base_url}</div>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="editProvider(${p.id}, '${p.name}', '${p.base_url}', ${p.is_active})" class="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                        <button onclick="deleteProvider(${p.id})" class="text-red-500 hover:text-red-700 text-sm">Delete</button>
                    </div>
                </div>
            `).join('');
            document.getElementById('providers-list').innerHTML = html || '<div class="text-gray-400 text-center py-4">No providers</div>';
        }
        
        function showAddProvider() {
            document.getElementById('provider-modal-title').textContent = 'Add Provider';
            document.getElementById('provider-id').value = '';
            document.getElementById('provider-name').value = '';
            document.getElementById('provider-name').disabled = false;
            document.getElementById('provider-url').value = '';
            document.getElementById('provider-key').value = '';
            document.getElementById('provider-active').checked = true;
            document.getElementById('provider-modal').classList.remove('hidden');
            document.getElementById('provider-modal').classList.add('flex');
        }
        
        function editProvider(id, name, url, active) {
            document.getElementById('provider-modal-title').textContent = 'Edit Provider';
            document.getElementById('provider-id').value = id;
            document.getElementById('provider-name').value = name;
            document.getElementById('provider-name').disabled = true;
            document.getElementById('provider-url').value = url;
            document.getElementById('provider-key').value = '';
            document.getElementById('provider-active').checked = active;
            document.getElementById('provider-modal').classList.remove('hidden');
            document.getElementById('provider-modal').classList.add('flex');
        }
        
        function closeProviderModal() {
            document.getElementById('provider-modal').classList.add('hidden');
            document.getElementById('provider-modal').classList.remove('flex');
        }
        
        document.getElementById('provider-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('provider-id').value;
            const data = {
                name: document.getElementById('provider-name').value,
                base_url: document.getElementById('provider-url').value,
                api_key: document.getElementById('provider-key').value || null,
                is_active: document.getElementById('provider-active').checked
            };
            
            try {
                if (id) {
                    await fetch('/providers/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({base_url: data.base_url, api_key: data.api_key, is_active: data.is_active})
                    });
                } else {
                    await fetch('/providers', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(data)
                    });
                }
                closeProviderModal();
                loadProviders();
            } catch(err) {
                alert('Failed to save provider');
            }
        });
        
        async function deleteProvider(id) {
            if (!confirm('Delete this provider?')) return;
            await fetch('/providers/' + id, {method: 'DELETE'});
            loadProviders();
        }
        
        async function loadStats() {
            const resp = await fetch('/stats');
            const data = await resp.json();
            
            document.getElementById('total-requests').textContent = data.total_requests.toLocaleString();
            document.getElementById('total-tokens').textContent = data.total_tokens.toLocaleString();
            document.getElementById('rpm').textContent = data.requests_per_minute || 0;
            document.getElementById('errors').textContent = data.total_errors || 0;
            
            const providerHtml = Object.entries(data.providers || {}).map(([name, p]) => `
                <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                    <span class="font-medium">${name}</span>
                    <span class="text-sm text-gray-600">${p.requests} req / ${p.tokens.toLocaleString()} tokens</span>
                </div>
            `).join('');
            document.getElementById('provider-stats').innerHTML = providerHtml || '<div class="text-gray-400">No data</div>';
            
            const modelHtml = Object.entries(data.models || {}).slice(0, 10).map(([name, m]) => `
                <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                    <span class="font-medium text-sm truncate flex-1">${name}</span>
                    <span class="text-sm text-gray-600 ml-2">${m.requests} / ${m.tokens.toLocaleString()} tokens</span>
                </div>
            `).join('');
            document.getElementById('model-stats').innerHTML = modelHtml || '<div class="text-gray-400">No data</div>';
        }
        
        async function loadLogs() {
            const filter = document.getElementById('log-filter').value;
            const resp = await fetch('/logs/all?limit=50');
            const data = await resp.json();
            
            let logs = data.logs || [];
            if (filter !== 'all') {
                logs = logs.filter(l => l.status === filter);
            }
            
            const logsHtml = logs.map((log, i) => {
                const statusClass = log.status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';
                const tokens = log.tokens?.total_tokens || log.tokens?.estimated || 0;
                return `
                <div class="log-entry border rounded p-3 cursor-pointer fade-in" onclick="showDetail(${i})">
                    <div class="flex justify-between items-start mb-2">
                        <div class="flex items-center gap-2">
                            <span class="px-2 py-0.5 rounded text-xs ${statusClass}">${log.status}</span>
                            <span class="font-medium">${log.model}</span>
                        </div>
                        <div class="text-right">
                            <div class="text-sm text-gray-500">${log.created_at}</div>
                            <div class="text-xs text-gray-400">${log.latency_ms}ms | ${tokens} tokens</div>
                        </div>
                    </div>
                </div>`;
            }).join('');
            
            document.getElementById('logs').innerHTML = logsHtml || '<div class="text-gray-400 text-center py-4">No logs</div>';
            window.logsData = logs;
        }
        
        function showDetail(index) {
            const log = window.logsData[index];
            if (!log) return;
            
            const responseText = log.response && log.response.trim() ? log.response : '';
            const errorText = log.error && log.error.trim() ? log.error : '';
            const displayText = responseText || errorText || 'No response data';
            const isError = log.status === 'error';
            
            const messagesHtml = (log.messages || []).map(m => 
                `<div class="p-2 bg-gray-100 rounded mb-1"><span class="font-medium text-xs text-gray-500">${m.role}:</span> <span class="text-sm">${m.content || ''}</span></div>`
            ).join('');
            
            document.getElementById('modal-content').innerHTML = `
                <div class="space-y-4">
                    <div class="grid grid-cols-2 gap-4">
                        <div><span class="text-gray-500">Time:</span> ${log.created_at}</div>
                        <div><span class="text-gray-500">Model:</span> ${log.model}</div>
                        <div><span class="text-gray-500">Latency:</span> ${log.latency_ms ? log.latency_ms.toFixed(0) + 'ms' : 'N/A'}</div>
                        <div><span class="text-gray-500">Tokens:</span> ${log.tokens?.total_tokens || log.tokens?.estimated || 0}</div>
                        <div><span class="text-gray-500">Status:</span> <span class="${isError ? 'text-red-600' : 'text-green-600'}">${log.status}</span></div>
                    </div>
                    <div>
                        <h4 class="font-medium mb-2">Messages</h4>
                        <div class="bg-gray-50 p-2 rounded max-h-32 overflow-y-auto">${messagesHtml || '<span class="text-gray-400">No messages</span>'}</div>
                    </div>
                    <div>
                        <h4 class="font-medium mb-2">${isError ? 'Error' : 'Response'}</h4>
                        <pre class="bg-gray-50 p-3 rounded text-sm max-h-64 overflow-y-auto ${isError ? 'text-red-600' : ''}">${displayText}</pre>
                    </div>
                </div>
            `;
            document.getElementById('detail-modal').classList.remove('hidden');
            document.getElementById('detail-modal').classList.add('flex');
        }
        
        function closeModal() {
            document.getElementById('detail-modal').classList.add('hidden');
            document.getElementById('detail-modal').classList.remove('flex');
        }
        
        document.getElementById('detail-modal').addEventListener('click', (e) => {
            if (e.target.id === 'detail-modal') closeModal();
        });
        document.getElementById('provider-modal').addEventListener('click', (e) => {
            if (e.target.id === 'provider-modal') closeProviderModal();
        });
        document.getElementById('apikey-modal').addEventListener('click', (e) => {
            if (e.target.id === 'apikey-modal') closeApiKeyModal();
        });
        
        loadApiKeys();
        loadProviders();
        loadStats();
        loadLogs();
        setInterval(loadStats, 5000);
    </script>
</body>
</html>
"""
