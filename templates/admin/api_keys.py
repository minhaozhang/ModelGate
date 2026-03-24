API_KEYS_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>API Keys - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
        .model-item.selected { background: #dbeafe; }
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
                <a href="/admin/config" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                    Config
                </a>
                <a href="/admin/api-keys" class="nav-link active flex items-center px-4 py-3 text-gray-700">
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
                <h2 class="text-2xl font-bold text-gray-800">API Keys</h2>
                <button onclick="showAddApiKey()" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">Add API Key</button>
            </div>
            
            <div class="mb-4 flex items-center gap-4">
                <div class="relative flex-1 max-w-md">
                    <input type="text" id="search-input" placeholder="Search by name or key..." 
                        class="w-full border rounded-lg px-4 py-2 pl-10 focus:outline-none focus:ring-2 focus:ring-blue-400"
                        oninput="handleSearch()">
                    <svg class="w-5 h-5 text-gray-400 absolute left-3 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                    </svg>
                </div>
                <div class="text-sm text-gray-500">
                    <span id="total-count">0</span> keys
                </div>
            </div>
            
            <div class="bg-white rounded-lg shadow">
                <div id="apikeys-list" class="divide-y"></div>
            </div>
            
            <div id="pagination" class="flex justify-center items-center gap-2 mt-4"></div>
        </main>
    </div>
    
    <div id="apikey-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
        <div class="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4">
            <div class="p-4 border-b flex justify-between items-center">
                <h3 id="apikey-modal-title" class="font-semibold">Add API Key</h3>
                <button onclick="closeApiKeyModal()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
            </div>
            <form id="apikey-form" class="p-4">
                <input type="hidden" id="apikey-id">
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">Name</label>
                    <input type="text" id="apikey-name" required class="w-full border rounded px-3 py-2" placeholder="e.g., Project A">
                </div>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">
                        Allowed Models <span class="text-gray-400">(<span id="selected-count">0</span> selected)</span>
                    </label>
                    <div class="border rounded max-h-60 overflow-y-auto">
                        <div id="models-checkbox-container" class="divide-y"></div>
                    </div>
                    <p class="text-xs text-gray-500 mt-1">Leave empty to allow all models</p>
                </div>
                <div class="flex justify-end gap-2">
                    <button type="button" onclick="closeApiKeyModal()" class="px-4 py-2 border rounded hover:bg-gray-50">Cancel</button>
                    <button type="submit" class="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">Save</button>
                </div>
            </form>
        </div>
    </div>
    
    <script>
        let selectedModelIds = [];
        let providerModels = [];
        let apiKeysData = [];
        let filteredData = [];
        let currentPage = 1;
        const pageSize = 10;
        
        async function logout() {
            await fetch('/admin/api/auth/logout', {method: 'POST'});
            window.location.href = '/admin/login';
        }
        
        async function loadApiKeys() {
            const resp = await fetch('/admin/api/keys');
            const data = await resp.json();
            apiKeysData = data.api_keys || [];
            handleSearch();
        }
        
        function handleSearch() {
            const query = document.getElementById('search-input').value.toLowerCase().trim();
            if (query) {
                filteredData = apiKeysData.filter(k => 
                    k.name.toLowerCase().includes(query) || 
                    k.key.toLowerCase().includes(query)
                );
            } else {
                filteredData = apiKeysData;
            }
            document.getElementById('total-count').textContent = filteredData.length;
            currentPage = 1;
            renderApiKeys();
            renderPagination();
        }
        
        async function loadProviderModels() {
            const resp = await fetch('/admin/api/provider-models');
            const data = await resp.json();
            providerModels = data.provider_models || [];
            renderModelCheckboxes();
        }
        
        function getModelDisplayName(pmId) {
            const pm = providerModels.find(p => p.id === pmId);
            return pm ? pm.display_name : `ID:${pmId}`;
        }
        
        function renderApiKeys() {
            const baseUrl = window.location.origin;
            const start = (currentPage - 1) * pageSize;
            const end = start + pageSize;
            const pageData = filteredData.slice(start, end);
            
            const html = pageData.map(k => {
                const modelNames = (k.allowed_provider_model_ids || []).map(id => getModelDisplayName(id));
                const modelsDisplay = modelNames.length > 0 
                    ? modelNames.slice(0, 3).join(', ') + (modelNames.length > 3 ? ` +${modelNames.length - 3}` : '')
                    : '<span class="text-gray-400">All models</span>';
                const userPageUrl = `${baseUrl}/user/login`;
                const setupMdUrl = `${baseUrl}/opencode/setup.md?api_key=${k.key}`;
                return `
                <div class="p-4">
                    <div class="flex justify-between items-center">
                        <div>
                            <div class="font-medium">${k.name}</div>
                            <div class="text-sm text-gray-500 flex items-center gap-2">
                                <code class="bg-gray-100 px-2 py-0.5 rounded text-xs">${k.key}</code>
                                <button onclick="copyKey('${k.key}')" class="text-blue-500 hover:text-blue-700 text-xs">Copy</button>
                            </div>
                            <div class="text-xs text-gray-400 mt-1">${modelsDisplay}</div>
                        </div>
                        <div class="flex gap-2">
                            <a href="/api-keys/${k.id}/query" target="_blank" class="text-green-500 hover:text-green-700 text-sm">Query</a>
                            <button onclick="editApiKey(${k.id})" class="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                            <button onclick="deleteApiKey(${k.id})" class="text-red-500 hover:text-red-700 text-sm">Delete</button>
                        </div>
                    </div>
                    <div class="mt-2 bg-gray-50 rounded p-2 text-xs space-y-1">
                        <div class="flex justify-between items-center">
                            <div>
                                <span class="text-gray-500">User Page: </span>
                                <a href="${userPageUrl}" target="_blank" class="text-blue-500 hover:underline">${userPageUrl}</a>
                            </div>
                            <button onclick="copyKey('${userPageUrl}')" class="text-blue-500 hover:text-blue-700">Copy</button>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-gray-500">Setup Doc:</span>
                            <a href="${setupMdUrl}" target="_blank" class="text-orange-500 hover:underline">OpenCode配置.md</a>
                            <button onclick="copyKeyWithInstructions('${k.key}', '${userPageUrl}', '${setupMdUrl}')" class="text-orange-500 hover:text-orange-700">Copy</button>
                        </div>
                    </div>
                </div>
            `}).join('');
            document.getElementById('apikeys-list').innerHTML = html || '<div class="text-gray-400 text-center py-8">No API keys found</div>';
        }
        
        function renderPagination() {
            const totalPages = Math.ceil(filteredData.length / pageSize);
            if (totalPages <= 1) {
                document.getElementById('pagination').innerHTML = '';
                return;
            }
            
            let html = '';
            
            if (currentPage > 1) {
                html += `<button onclick="goToPage(${currentPage - 1})" class="px-3 py-1 border rounded hover:bg-gray-50">Previous</button>`;
            }
            
            const maxVisible = 5;
            let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
            let endPage = Math.min(totalPages, startPage + maxVisible - 1);
            
            if (endPage - startPage + 1 < maxVisible) {
                startPage = Math.max(1, endPage - maxVisible + 1);
            }
            
            if (startPage > 1) {
                html += `<button onclick="goToPage(1)" class="px-3 py-1 border rounded hover:bg-gray-50">1</button>`;
                if (startPage > 2) html += `<span class="px-2">...</span>`;
            }
            
            for (let i = startPage; i <= endPage; i++) {
                if (i === currentPage) {
                    html += `<button class="px-3 py-1 border rounded bg-blue-500 text-white">${i}</button>`;
                } else {
                    html += `<button onclick="goToPage(${i})" class="px-3 py-1 border rounded hover:bg-gray-50">${i}</button>`;
                }
            }
            
            if (endPage < totalPages) {
                if (endPage < totalPages - 1) html += `<span class="px-2">...</span>`;
                html += `<button onclick="goToPage(${totalPages})" class="px-3 py-1 border rounded hover:bg-gray-50">${totalPages}</button>`;
            }
            
            if (currentPage < totalPages) {
                html += `<button onclick="goToPage(${currentPage + 1})" class="px-3 py-1 border rounded hover:bg-gray-50">Next</button>`;
            }
            
            document.getElementById('pagination').innerHTML = html;
        }
        
        function goToPage(page) {
            currentPage = page;
            renderApiKeys();
            renderPagination();
            window.scrollTo({top: 0, behavior: 'smooth'});
        }
        
        function copyExample(cmd) {
            navigator.clipboard.writeText(cmd).then(() => alert('Copied!'));
        }
        
        function renderModelCheckboxes() {
            const container = document.getElementById('models-checkbox-container');
            if (providerModels.length === 0) {
                container.innerHTML = '<div class="text-gray-400 text-center py-4">No models available. Add providers and models in Config first.</div>';
                return;
            }
            container.innerHTML = providerModels.map(pm => `
                <label class="flex items-center p-2 hover:bg-gray-50 cursor-pointer ${selectedModelIds.includes(pm.id) ? 'selected' : ''}" data-pm-id="${pm.id}">
                    <input type="checkbox" class="mr-2" value="${pm.id}" ${selectedModelIds.includes(pm.id) ? 'checked' : ''} onchange="toggleModel(${pm.id})">
                    <span class="text-sm">${pm.display_name}</span>
                </label>
            `).join('');
        }
        
        function toggleModel(id) {
            const idx = selectedModelIds.indexOf(id);
            if (idx > -1) {
                selectedModelIds.splice(idx, 1);
            } else {
                selectedModelIds.push(id);
            }
            updateSelectedCount();
            const label = document.querySelector(`label[data-pm-id="${id}"]`);
            if (label) label.classList.toggle('selected', selectedModelIds.includes(id));
        }
        
        function updateSelectedCount() {
            document.getElementById('selected-count').textContent = selectedModelIds.length;
        }
        
        function copyKey(key) {
            navigator.clipboard.writeText(key).then(() => alert('Copied!'));
        }
        
        function copyKeyWithInstructions(key, userPageUrl, setupMdUrl) {
            const text = `API Key: ${key}

使用说明：
1. 登录用户页面：${userPageUrl}
   在页面中粘贴上面的 API Key 进行登录

2. 配置 OpenCode：
   让智能体读取配置文档：${setupMdUrl}`;
            navigator.clipboard.writeText(text).then(() => alert('API Key 和使用说明已复制!'));
        }
        
        function showAddApiKey() {
            document.getElementById('apikey-modal-title').textContent = 'Add API Key';
            document.getElementById('apikey-id').value = '';
            document.getElementById('apikey-name').value = '';
            selectedModelIds = [];
            updateSelectedCount();
            renderModelCheckboxes();
            document.getElementById('apikey-modal').classList.remove('hidden');
            document.getElementById('apikey-modal').classList.add('flex');
        }
        
        function editApiKey(id) {
            const key = apiKeysData.find(k => k.id === id);
            if (!key) return;
            document.getElementById('apikey-modal-title').textContent = 'Edit API Key';
            document.getElementById('apikey-id').value = id;
            document.getElementById('apikey-name').value = key.name;
            selectedModelIds = key.allowed_provider_model_ids || [];
            updateSelectedCount();
            renderModelCheckboxes();
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
            const data = {
                name: document.getElementById('apikey-name').value,
                allowed_provider_model_ids: selectedModelIds,
            };
            
            try {
                if (id) {
                    await fetch('/admin/api/keys/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(data)
                    });
                } else {
                    const resp = await fetch('/admin/api/keys', {
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
            await fetch('/admin/api/keys/' + id, {method: 'DELETE'});
            loadApiKeys();
        }
        
        document.getElementById('apikey-modal').addEventListener('click', (e) => {
            if (e.target.id === 'apikey-modal') closeApiKeyModal();
        });
        
        loadProviderModels().then(() => loadApiKeys());
        
        document.getElementById('search-input').addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.target.value = '';
                handleSearch();
            }
        });
    </script>
</body>
</html>
"""
