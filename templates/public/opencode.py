OPENCODE_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OpenCode Config v2 - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
        pre { white-space: pre-wrap; word-break: break-all; }
        .copy-btn { transition: all 0.2s; }
        .copy-btn:hover { background: #3b82f6; color: white; }
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
                <a href="/admin/monitor" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                    Monitor
                </a>
                <a href="/opencode" class="nav-link active flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>
                    OpenCode Config
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
            <h2 class="text-2xl font-bold text-gray-800 mb-2">OpenCode Configuration</h2>
            <p class="text-gray-500 mb-6">Generate opencode.json config for this proxy</p>
            
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <label class="block text-sm font-medium text-gray-700 mb-2">Enter your API Key to generate config</label>
                <div class="flex gap-2">
                    <input type="text" id="api-key-input" placeholder="sk-..." 
                        class="flex-1 border rounded px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <button onclick="generateConfig()" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                        Generate
                    </button>
                </div>
            </div>
            
            <div id="config-section" class="hidden">
                <div class="bg-white rounded-lg shadow mb-6">
                    <div class="flex justify-between items-center p-4 border-b">
                        <h3 class="text-lg font-semibold">opencode.json</h3>
                        <button onclick="copyConfig()" class="copy-btn border border-blue-500 text-blue-500 px-3 py-1 rounded text-sm">
                            Copy
                        </button>
                    </div>
                    <pre id="config-output" class="p-4 text-sm bg-gray-50 overflow-x-auto"></pre>
                </div>
                
                <div class="bg-white rounded-lg shadow p-4">
                    <h3 class="text-lg font-semibold mb-3">Available Models</h3>
                    <div id="models-list" class="space-y-2"></div>
                </div>
            </div>
            
            <div id="error-section" class="hidden bg-red-50 border border-red-200 rounded-lg p-4">
                <p id="error-msg" class="text-red-600"></p>
            </div>
            
            <div class="bg-white rounded-lg shadow p-6 mt-6">
                <h3 class="text-lg font-semibold mb-3">How to use</h3>
                <ol class="list-decimal list-inside space-y-2 text-gray-600">
                    <li>Enter your API Key and click Generate</li>
                    <li>Copy the generated <code class="bg-gray-100 px-1 rounded">opencode.json</code></li>
                    <li>Create <code class="bg-gray-100 px-1 rounded">opencode.json</code> in your project root</li>
                    <li>Paste the configuration and save</li>
                    <li>OpenCode will now use this proxy for API requests</li>
                </ol>
            </div>
        </main>
    </div>
    
    <script>
        async function logout() {
            await fetch('/admin/api/auth/logout', {method: 'POST'});
            window.location.href = '/login';
        }
        
        const urlParams = new URLSearchParams(window.location.search);
        const apiKeyFromUrl = urlParams.get('api_key');
        if (apiKeyFromUrl) {
            document.getElementById('api-key-input').value = apiKeyFromUrl;
            generateConfig();
        }
        
        async function generateConfig() {
            const apiKey = document.getElementById('api-key-input').value.trim();
            if (!apiKey) {
                showError('Please enter an API Key');
                return;
            }
            
            try {
                const resp = await fetch('/opencode/config?api_key=' + encodeURIComponent(apiKey));
                const data = await resp.json();
                
                if (data.error) {
                    showError(data.error);
                    return;
                }
                
                document.getElementById('config-section').classList.remove('hidden');
                document.getElementById('error-section').classList.add('hidden');
                
                const config = data.config;
                config.provider['model-token-plan'].options.baseURL = window.location.origin + '/v1';
                
                const prompt = "# 请帮我将以下provider配置添加到 ~/.opencode/opencode.json 中。保留现有的providers和其他设置，只添加或更新 'model-token-plan' 这个provider。\\n\\n";
                const configJson = prompt + JSON.stringify(config, null, 2);
                document.getElementById('config-output').textContent = configJson;
                
                const modelsHtml = data.models.map(m => `
                    <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                        <span class="font-medium">${m.name}</span>
                        <span class="text-sm text-gray-500">context: ${m.context.toLocaleString()} | output: ${m.output.toLocaleString()}</span>
                    </div>
                `).join('');
                document.getElementById('models-list').innerHTML = modelsHtml;
            } catch (e) {
                showError('Failed to generate config: ' + e.message);
            }
        }
        
        function showError(msg) {
            document.getElementById('config-section').classList.add('hidden');
            document.getElementById('error-section').classList.remove('hidden');
            document.getElementById('error-msg').textContent = msg;
        }
        
        function copyConfig() {
            const config = document.getElementById('config-output').textContent;
            navigator.clipboard.writeText(config).then(() => {
                const btn = document.querySelector('.copy-btn');
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy', 2000);
            });
        }
    </script>
</body>
</html>
"""
