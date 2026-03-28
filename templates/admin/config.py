CONFIG_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Config - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="flex">
        <nav class="w-56 bg-white shadow-lg min-h-screen fixed">
            <div class="p-4 border-b">
                <h1 class="text-xl font-bold text-gray-800">API Proxy</h1>
            </div>
            <div class="py-2">
                <a href="/admin/home" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                    Home
                </a>
                <a href="/admin/config" class="nav-link active flex items-center px-4 py-3 text-gray-700">
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
            <h2 class="text-2xl font-bold text-gray-800 mb-6">Provider & Model Configuration</h2>
            
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div class="bg-white rounded-lg shadow">
                    <div class="p-4 border-b flex justify-between items-center">
                        <h3 class="text-lg font-semibold">Providers</h3>
                        <button onclick="showAddProvider()" class="bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600">+ Add</button>
                    </div>
                    <div id="providers-list" class="p-4 space-y-2 max-h-80 overflow-y-auto"></div>
                </div>
                
                <div class="bg-white rounded-lg shadow">
                    <div class="p-4 border-b flex justify-between items-center">
                        <h3 class="text-lg font-semibold">Models</h3>
                        <div class="flex gap-2">
                            <button onclick="showAddModel()" class="bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600">+ Add</button>
                            <button onclick="syncSelectedProvider()" class="bg-purple-500 text-white px-4 py-2 rounded text-sm hover:bg-purple-600">Sync</button>
                        </div>
                    </div>
                    <div id="models-list" class="p-4 space-y-2 max-h-80 overflow-y-auto"></div>
                </div>
            </div>
            
            <div class="mt-6 bg-white rounded-lg shadow">
                <div class="p-4 border-b flex justify-between items-center">
                    <h3 class="text-lg font-semibold">Provider-Model Bindings</h3>
                    <button onclick="syncSelectedProvider()" class="bg-purple-500 text-white px-4 py-2 rounded text-sm hover:bg-purple-600 ${!selectedProviderId ? 'opacity-50 cursor-not-allowed' : ''}" id="sync-btn">Sync from API</button>
                </div>
                <div id="bindings-container" class="p-4">
                    <div class="text-gray-400 text-center py-4">Select a provider to view bindings</div>
                </div>
            </div>
        </main>
    </div>
    
    <div id="provider-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div class="p-4 border-b flex justify-between items-center">
                <h3 id="provider-modal-title" class="font-semibold">Add Provider</h3>
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
                <div class="flex items-center">
                    <input type="checkbox" id="provider-merge-msgs" class="mr-2">
                    <label class="text-sm text-gray-700">合并连续相同角色消息 <span class="text-xs text-gray-400">(MiniMax等要求角色交替的供应商)</span></label>
                </div>
                <div class="flex gap-2">
                    <button type="submit" class="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">Save</button>
                    <button type="button" onclick="closeProviderModal()" class="px-4 py-2 border rounded hover:bg-gray-50">Cancel</button>
                </div>
            </form>
        </div>
    </div>
    
    <div id="model-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div class="p-4 border-b flex justify-between items-center">
                <h3 id="model-modal-title" class="font-semibold">Add Model</h3>
                <button onclick="closeModelModal()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
            </div>
            <form id="model-form" class="p-4 space-y-4">
                <input type="hidden" id="model-id">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Model Name (ID)</label>
                    <input type="text" id="model-name" required class="w-full border rounded px-3 py-2" placeholder="e.g., glm-4.7">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                    <input type="text" id="model-display-name" class="w-full border rounded px-3 py-2" placeholder="e.g., GLM-4.7">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Max Tokens</label>
                    <input type="number" id="model-max-tokens" value="4096" class="w-full border rounded px-3 py-2">
                </div>
                <div class="flex items-center gap-4">
                    <label class="flex items-center">
                        <input type="checkbox" id="model-multimodal" class="mr-2">
                        <span class="text-sm text-gray-700">Multimodal</span>
                    </label>
                    <label class="flex items-center">
                        <input type="checkbox" id="model-active" checked class="mr-2">
                        <span class="text-sm text-gray-700">Active</span>
                    </label>
                </div>
                <div class="flex gap-2">
                    <button type="submit" class="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">Save</button>
                    <button type="button" onclick="closeModelModal()" class="px-4 py-2 border rounded hover:bg-gray-50">Cancel</button>
                </div>
            </form>
        </div>
    </div>
    
    <script>
        let allProviders = [];
        let allModels = [];
        let selectedProviderId = null;
        
        async function logout() {
            await fetch('/admin/api/auth/logout', {method: 'POST'});
            window.location.href = '/admin/login';
        }

        async function fetchOrRedirect(url, options) {
            const resp = await fetch(url, options);
            if (resp.status === 401) {
                window.location.href = '/admin/login';
                throw new Error('Unauthorized');
            }
            return resp;
        }

        async function fetchJsonOrRedirect(url, options) {
            const resp = await fetchOrRedirect(url, options);
            return await resp.json();
        }
        
        async function loadProviders() {
            const data = await fetchJsonOrRedirect('/admin/api/providers');
            allProviders = data.providers || [];
            const html = allProviders.map(p => `
                <div class="flex justify-between items-center p-3 bg-gray-50 rounded cursor-pointer hover:bg-blue-50 ${selectedProviderId === p.id ? 'ring-2 ring-blue-500' : ''}" onclick="selectProvider(${p.id})">
                    <div>
                        <span class="font-medium">${p.name}</span>
                        <span class="ml-2 text-xs ${p.is_active ? 'text-green-600' : 'text-red-600'}">${p.is_active ? 'Active' : 'Inactive'}</span>
                        <div class="text-xs text-gray-500">${p.base_url}</div>
                    </div>
                    <div class="flex gap-2" onclick="event.stopPropagation()">
                        <button onclick="editProvider(${p.id})" class="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                        <button onclick="deleteProvider(${p.id})" class="text-red-500 hover:text-red-700 text-sm">Delete</button>
                    </div>
                </div>
            `).join('');
            document.getElementById('providers-list').innerHTML = html || '<div class="text-gray-400 text-center py-4">No providers</div>';
        }
        
        async function loadModels() {
            const data = await fetchJsonOrRedirect('/admin/api/models');
            allModels = data.models || [];
            const html = allModels.map(m => `
                <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                    <div>
                        <span class="font-medium">${m.display_name || m.name}</span>
                        <span class="ml-2 text-xs text-gray-500">${m.name}</span>
                        <span class="ml-2 text-xs ${m.is_active ? 'text-green-600' : 'text-red-600'}">${m.is_active ? 'Active' : 'Inactive'}</span>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="editModel(${m.id})" class="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                        <button onclick="deleteModel(${m.id})" class="text-red-500 hover:text-red-700 text-sm">Delete</button>
                    </div>
                </div>
            `).join('');
            document.getElementById('models-list').innerHTML = html || '<div class="text-gray-400 text-center py-4">No models</div>';
        }
        
        async function selectProvider(id) {
            selectedProviderId = id;
            loadProviders();
            await loadProviderBindings(id);
        }
        
        async function loadProviderBindings(providerId) {
            const provider = allProviders.find(p => p.id === providerId);
            const data = await fetchJsonOrRedirect('/admin/api/providers/' + providerId + '/models');
            const bindings = data.models || [];
            
            const unboundModels = allModels.filter(m => m.is_active && !bindings.find(b => b.model_id === m.id));
            
            let html = `<div class="mb-4"><span class="font-medium">${provider.name}</span> - Bound Models</div>`;
            
            if (bindings.length > 0) {
                html += '<div class="space-y-2 mb-4">';
                bindings.forEach(b => {
                    html += `
                        <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                            <span>${b.display_name || b.model_name}</span>
                            <button onclick="unbindModel(${b.id})" class="text-red-500 hover:text-red-700 text-sm">Unbind</button>
                        </div>
                    `;
                });
                html += '</div>';
            } else {
                html += '<div class="text-gray-400 text-center py-2 mb-4">No models bound</div>';
            }
            
            if (unboundModels.length > 0) {
                html += `
                    <div class="flex gap-2">
                        <select id="bind-model-select" class="flex-1 border rounded px-3 py-2 text-sm">
                            ${unboundModels.map(m => `<option value="${m.id}">${m.display_name || m.name}</option>`).join('')}
                        </select>
                        <button onclick="bindModel()" class="bg-green-500 text-white px-4 py-2 rounded text-sm hover:bg-green-600">Bind</button>
                    </div>
                `;
            }
            
            document.getElementById('bindings-container').innerHTML = html;
        }
        
        async function bindModel() {
            const modelId = document.getElementById('bind-model-select').value;
            if (!modelId || !selectedProviderId) return;
            await fetchOrRedirect('/admin/api/providers/' + selectedProviderId + '/models', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({model_id: parseInt(modelId), is_active: true})
            });
            loadProviderBindings(selectedProviderId);
        }
        
        async function unbindModel(pmId) {
            await fetchOrRedirect('/admin/api/providers/' + selectedProviderId + '/models/' + pmId, {method: 'DELETE'});
            loadProviderBindings(selectedProviderId);
        }
        
        async function syncSelectedProvider() {
            if (!selectedProviderId) {
                alert('Please select a provider first');
                return;
            }
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Syncing...';
            try {
                const data = await fetchJsonOrRedirect('/admin/api/providers/' + selectedProviderId + '/sync-models', {method: 'POST'});
                if (data.synced) {
                    alert('Synced ' + data.total + ' models: ' + data.synced.join(', '));
                    loadModels();
                    loadProviderBindings(selectedProviderId);
                } else if (data.error) {
                    alert('Sync failed: ' + data.error);
                }
            } catch(e) {
                alert('Sync failed: ' + e.message);
            }
            btn.disabled = false;
            btn.textContent = 'Sync';
        }
        
        function showAddProvider() {
            document.getElementById('provider-modal-title').textContent = 'Add Provider';
            document.getElementById('provider-id').value = '';
            document.getElementById('provider-name').value = '';
            document.getElementById('provider-name').disabled = false;
            document.getElementById('provider-url').value = '';
            document.getElementById('provider-key').value = '';
            document.getElementById('provider-active').checked = true;
            document.getElementById('provider-merge-msgs').checked = false;
            document.getElementById('provider-modal').classList.remove('hidden');
            document.getElementById('provider-modal').classList.add('flex');
        }
        
        function editProvider(id) {
            const p = allProviders.find(x => x.id === id);
            if (!p) return;
            document.getElementById('provider-modal-title').textContent = 'Edit Provider';
            document.getElementById('provider-id').value = p.id;
            document.getElementById('provider-name').value = p.name;
            document.getElementById('provider-name').disabled = true;
            document.getElementById('provider-url').value = p.base_url;
            document.getElementById('provider-key').value = '';
            document.getElementById('provider-active').checked = p.is_active;
            document.getElementById('provider-merge-msgs').checked = p.merge_consecutive_messages || false;
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
                is_active: document.getElementById('provider-active').checked,
                merge_consecutive_messages: document.getElementById('provider-merge-msgs').checked
            };
            
            try {
                if (id) {
                    await fetchOrRedirect('/admin/api/providers/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({base_url: data.base_url, api_key: data.api_key, is_active: data.is_active, merge_consecutive_messages: data.merge_consecutive_messages})
                    });
                } else {
                    await fetchOrRedirect('/admin/api/providers', {
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
            await fetchOrRedirect('/admin/api/providers/' + id, {method: 'DELETE'});
            if (selectedProviderId === id) {
                selectedProviderId = null;
                document.getElementById('bindings-container').innerHTML = '<div class="text-gray-400 text-center py-4">Select a provider to view bindings</div>';
            }
            loadProviders();
        }
        
        function showAddModel() {
            document.getElementById('model-modal-title').textContent = 'Add Model';
            document.getElementById('model-id').value = '';
            document.getElementById('model-name').value = '';
            document.getElementById('model-name').disabled = false;
            document.getElementById('model-display-name').value = '';
            document.getElementById('model-max-tokens').value = '4096';
            document.getElementById('model-multimodal').checked = false;
            document.getElementById('model-active').checked = true;
            document.getElementById('model-modal').classList.remove('hidden');
            document.getElementById('model-modal').classList.add('flex');
        }
        
        function editModel(id) {
            const m = allModels.find(x => x.id === id);
            if (!m) return;
            document.getElementById('model-modal-title').textContent = 'Edit Model';
            document.getElementById('model-id').value = m.id;
            document.getElementById('model-name').value = m.name;
            document.getElementById('model-name').disabled = true;
            document.getElementById('model-display-name').value = m.display_name || '';
            document.getElementById('model-max-tokens').value = m.max_tokens;
            document.getElementById('model-multimodal').checked = m.is_multimodal;
            document.getElementById('model-active').checked = m.is_active;
            document.getElementById('model-modal').classList.remove('hidden');
            document.getElementById('model-modal').classList.add('flex');
        }
        
        function closeModelModal() {
            document.getElementById('model-modal').classList.add('hidden');
            document.getElementById('model-modal').classList.remove('flex');
        }
        
        document.getElementById('model-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('model-id').value;
            const data = {
                name: document.getElementById('model-name').value,
                display_name: document.getElementById('model-display-name').value || null,
                max_tokens: parseInt(document.getElementById('model-max-tokens').value) || 4096,
                is_multimodal: document.getElementById('model-multimodal').checked,
                is_active: document.getElementById('model-active').checked
            };
            
            try {
                if (id) {
                    await fetchOrRedirect('/admin/api/models/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            display_name: data.display_name,
                            max_tokens: data.max_tokens,
                            is_multimodal: data.is_multimodal,
                            is_active: data.is_active
                        })
                    });
                } else {
                    await fetchOrRedirect('/admin/api/models', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(data)
                    });
                }
                closeModelModal();
                loadModels();
            } catch(err) {
                alert('Failed to save model');
            }
        });
        
        async function deleteModel(id) {
            if (!confirm('Delete this model?')) return;
            await fetchOrRedirect('/admin/api/models/' + id, {method: 'DELETE'});
            loadModels();
        }
        
        document.getElementById('provider-modal').addEventListener('click', (e) => {
            if (e.target.id === 'provider-modal') closeProviderModal();
        });
        document.getElementById('model-modal').addEventListener('click', (e) => {
            if (e.target.id === 'model-modal') closeModelModal();
        });
        
        loadProviders();
        loadModels();
    </script>
</body>
</html>
"""
