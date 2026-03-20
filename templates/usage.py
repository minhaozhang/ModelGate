USAGE_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Usage Guide - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
        pre { background: #1e293b; color: #e2e8f0; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; }
        code { font-family: 'Monaco', 'Menlo', monospace; font-size: 0.875rem; }
        .copy-btn { position: absolute; top: 0.5rem; right: 0.5rem; }
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
                <a href="/monitor" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                    Monitor
                </a>
                <a href="/opencode" class="nav-link flex items-center px-4 py-3 text-gray-700">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>
                    OpenCode Config
                </a>
                <a href="/usage" class="nav-link active flex items-center px-4 py-3 text-gray-700">
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
            <h2 class="text-2xl font-bold text-gray-800 mb-6">How to Configure API Clients</h2>
            
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h3 class="text-lg font-semibold mb-4">Basic Information</h3>
                <div class="space-y-3">
                    <div class="flex items-center">
                        <span class="text-gray-600 w-32">Proxy URL:</span>
                        <code class="bg-gray-100 px-3 py-1 rounded text-sm" id="proxy-url"></code>
                    </div>
                    <div class="flex items-center">
                        <span class="text-gray-600 w-32">API Endpoint:</span>
                        <code class="bg-gray-100 px-3 py-1 rounded text-sm">/v1/chat/completions</code>
                    </div>
                    <div class="flex items-center">
                        <span class="text-gray-600 w-32">Auth Header:</span>
                        <code class="bg-gray-100 px-3 py-1 rounded text-sm">Authorization: Bearer YOUR_API_KEY</code>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h3 class="text-lg font-semibold mb-4">Model Name Format</h3>
                <p class="text-gray-600 mb-3">Use <code class="bg-gray-100 px-2 py-1 rounded">provider/model</code> format to specify provider:</p>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="bg-gray-50 p-4 rounded">
                        <div class="text-sm text-gray-500 mb-2">With Provider Prefix</div>
                        <code class="text-sm">zhipu/glm-4</code>
                        <div class="text-xs text-gray-400 mt-1">Routes to Zhipu provider</div>
                    </div>
                    <div class="bg-gray-50 p-4 rounded">
                        <div class="text-sm text-gray-500 mb-2">Without Prefix</div>
                        <code class="text-sm">glm-4</code>
                        <div class="text-xs text-gray-400 mt-1">Uses default provider</div>
                    </div>
                </div>
            </div>
            
            <div class="space-y-6">
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold mb-4 flex items-center">
                        <img src="https://cdn.oaistatic.com/assets/apple-touch-icon-mz9nytnj.webp" class="w-6 h-6 mr-2 rounded">
                        ChatGPT-Next-Web / LobeChat
                    </h3>
                    <p class="text-gray-600 mb-4">Go to Settings and configure:</p>
                    <div class="relative">
                        <pre><code>Endpoint: <span id="endpoint-nextweb"></span>
API Key: YOUR_API_KEY
Model: zhipu/glm-4  (or other provider/model)</code></pre>
                    </div>
                </div>

                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold mb-4 flex items-center">
                        <span class="w-6 h-6 mr-2 bg-green-500 text-white rounded text-xs flex items-center justify-center font-bold">Py</span>
                        Python (OpenAI SDK)
                    </h3>
                    <div class="relative">
                        <button onclick="copyCode('python')" class="copy-btn bg-gray-700 text-white px-2 py-1 rounded text-xs hover:bg-gray-600">Copy</button>
                        <pre id="code-python"><code>from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY",
    base_url="<span id="base-python"></span>"
)

response = client.chat.completions.create(
    model="zhipu/glm-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)</code></pre>
                    </div>
                </div>

                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold mb-4 flex items-center">
                        <span class="w-6 h-6 mr-2 bg-yellow-500 text-white rounded text-xs flex items-center justify-center font-bold">JS</span>
                        JavaScript / Node.js
                    </h3>
                    <div class="relative">
                        <button onclick="copyCode('js')" class="copy-btn bg-gray-700 text-white px-2 py-1 rounded text-xs hover:bg-gray-600">Copy</button>
                        <pre id="code-js"><code>const response = await fetch('<span id="base-js"></span>/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_API_KEY'
  },
  body: JSON.stringify({
    model: 'zhipu/glm-4',
    messages: [{ role: 'user', content: 'Hello!' }]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);</code></pre>
                    </div>
                </div>

                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold mb-4 flex items-center">
                        <span class="w-6 h-6 mr-2 bg-blue-500 text-white rounded text-xs flex items-center justify-center font-bold">cURL</span>
                        cURL
                    </h3>
                    <div class="relative">
                        <button onclick="copyCode('curl')" class="copy-btn bg-gray-700 text-white px-2 py-1 rounded text-xs hover:bg-gray-600">Copy</button>
                        <pre id="code-curl"><code>curl <span id="base-curl"></span>/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "model": "zhipu/glm-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'</code></pre>
                    </div>
                </div>

                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold mb-4 flex items-center">
                        <span class="w-6 h-6 mr-2 bg-purple-500 text-white rounded text-xs flex items-center justify-center font-bold">VS</span>
                        VS Code (Continue / Cline)
                    </h3>
                    <p class="text-gray-600 mb-4">Add to your config.json:</p>
                    <div class="relative">
                        <button onclick="copyCode('vscode')" class="copy-btn bg-gray-700 text-white px-2 py-1 rounded text-xs hover:bg-gray-600">Copy</button>
                        <pre id="code-vscode"><code>{
  "models": [{
    "title": "API Proxy",
    "provider": "openai",
    "model": "zhipu/glm-4",
    "apiBase": "<span id="base-vscode"></span>",
    "apiKey": "YOUR_API_KEY"
  }]
}</code></pre>
                    </div>
                </div>
            </div>

            <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mt-6">
                <h4 class="font-semibold text-yellow-800 mb-2">Tips</h4>
                <ul class="text-sm text-yellow-700 space-y-1">
                    <li>- Get your API key from <a href="/api-keys" class="underline">API Keys</a> page</li>
                    <li>- Check available models in <a href="/config" class="underline">Config</a> page</li>
                    <li>- Monitor usage in <a href="/monitor" class="underline">Monitor</a> page</li>
                    <li>- Each provider has its own concurrency limit</li>
                </ul>
            </div>
        </main>
    </div>
    
    <script>
        async function logout() {
            await fetch('/api/logout', {method: 'POST'});
            window.location.href = '/login';
        }
        
        function copyCode(type) {
            const el = document.getElementById('code-' + type);
            navigator.clipboard.writeText(el.textContent).then(() => {
                alert('Copied!');
            });
        }
        
        const baseUrl = window.location.origin + '/v1';
        document.getElementById('proxy-url').textContent = baseUrl;
        document.getElementById('endpoint-nextweb').textContent = baseUrl;
        document.getElementById('base-python').textContent = baseUrl;
        document.getElementById('base-js').textContent = baseUrl;
        document.getElementById('base-curl').textContent = baseUrl;
        document.getElementById('base-vscode').textContent = baseUrl;
    </script>
</body>
</html>
"""
