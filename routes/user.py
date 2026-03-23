from datetime import datetime, timedelta
from fastapi import APIRouter, Cookie, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from typing import Optional
import secrets
import os

from database import async_session_maker, ApiKey, RequestLog
from config import logger

router = APIRouter(tags=["user"])

USER_SESSIONS: dict[str, dict] = {}
USER_SESSION_EXPIRE_HOURS = 24


USER_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>User Login - API Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <style>
        #particles-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
        }
        .login-card {
            background: rgba(10, 10, 20, 0.2);
            backdrop-filter: blur(2px);
            -webkit-backdrop-filter: blur(2px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        }
        .login-card label {
            color: rgba(255, 255, 255, 0.85);
        }
        .login-card input[type="password"] {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #fff;
        }
        .login-card input[type="password"]::placeholder {
            color: rgba(255, 255, 255, 0.4);
        }
        .login-card input[type="password"]:focus {
            border-color: rgba(100, 150, 255, 0.6);
            background: rgba(255, 255, 255, 0.12);
        }
        .login-card input[type="checkbox"] {
            accent-color: #6366f1;
        }
    </style>
</head>
<body class="min-h-screen flex items-center justify-center overflow-hidden">
    <div id="particles-container"></div>
    
    <div class="login-card rounded-2xl shadow-2xl p-8 w-full max-w-md mx-4">
        <h1 class="text-2xl font-bold text-white mb-6 text-center">API Key Login</h1>
        
        <form id="login-form" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1" style="color: rgba(255,255,255,0.8)">API Key</label>
                <input type="password" id="api-key" required
                    class="w-full rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder="sk-...">
            </div>
            <div class="flex items-center">
                <input type="checkbox" id="remember" class="mr-2" checked>
                <label for="remember" class="text-sm" style="color: rgba(255,255,255,0.7)">Remember API Key</label>
            </div>
            <div id="error-msg" class="text-red-400 text-sm hidden"></div>
            <button type="submit" id="login-btn" class="w-full bg-gradient-to-r from-blue-500 to-purple-500 text-white py-2.5 rounded-lg hover:from-blue-600 hover:to-purple-600 font-medium transition-all shadow-lg hover:shadow-xl">
                Login
            </button>
        </form>
        
        <p class="text-sm text-center mt-4" style="color: rgba(255,255,255,0.5)">
            Enter your API Key to view usage statistics
        </p>
    </div>
    
    <script>
        // Three.js Particle System
        let scene, camera, renderer, particles;
        let mouseX = 0, mouseY = 0;
        
        function init() {
            const container = document.getElementById('particles-container');
            
            scene = new THREE.Scene();
            
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            camera.position.z = 50;
            
            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            renderer.setClearColor(0x0d1117, 1);
            container.appendChild(renderer.domElement);
            
            createParticles();
            
            document.addEventListener('mousemove', onMouseMove);
            window.addEventListener('resize', onWindowResize);
            
            animate();
        }
        
        function createParticles() {
            const particleCount = window.innerWidth < 768 ? 600 : 1800;
            const geometry = new THREE.BufferGeometry();
            
            const positions = new Float32Array(particleCount * 3);
            const colors = new Float32Array(particleCount * 3);
            const sizes = new Float32Array(particleCount);
            const rotations = new Float32Array(particleCount);
            const particleData = [];
            
            const colorPalette = [
                [0.26, 0.52, 0.96],
                [0.96, 0.26, 0.21],
                [0.98, 0.73, 0.02],
                [0.13, 0.69, 0.33],
                [0.55, 0.36, 0.96],
                [0.0, 0.73, 0.83],
            ];
            
            const rings = 10;
            const particlesPerRing = Math.floor(particleCount / rings);
            
            for (let ring = 0; ring < rings; ring++) {
                const ringRadius = 10 + ring * 10;
                const particlesInThisRing = particlesPerRing + (ring === rings - 1 ? particleCount % rings : 0);
                
                for (let i = 0; i < particlesInThisRing; i++) {
                    const idx = ring * particlesPerRing + i;
                    if (idx >= particleCount) break;
                    
                    const angle = (i / particlesInThisRing) * Math.PI * 2;
                    const x = Math.cos(angle) * ringRadius;
                    const y = Math.sin(angle) * ringRadius * 0.6;
                    const z = (Math.random() - 0.5) * 25;
                    
                    positions[idx * 3] = x;
                    positions[idx * 3 + 1] = y;
                    positions[idx * 3 + 2] = z;
                    
                    const color = colorPalette[Math.floor(Math.random() * colorPalette.length)];
                    colors[idx * 3] = color[0] + (Math.random() - 0.5) * 0.1;
                    colors[idx * 3 + 1] = color[1] + (Math.random() - 0.5) * 0.1;
                    colors[idx * 3 + 2] = color[2] + (Math.random() - 0.5) * 0.1;
                    
                    const depthFactor = (z + 10) / 20;
                    sizes[idx] = (2 + Math.random() * 2.5) * (0.7 + depthFactor * 0.3);
                    
                    rotations[idx] = angle + Math.PI / 2;
                    
                    particleData.push({
                        x: x, y: y, z: z,
                        ringRadius: ringRadius,
                        baseAngle: angle,
                        angularSpeed: 0.0003 + Math.random() * 0.0005,
                        wobblePhase: Math.random() * Math.PI * 2,
                        wobbleSpeed: 0.5 + Math.random() * 1,
                        wobbleAmount: 0.3 + Math.random() * 0.5,
                        pulsePhase: Math.random() * Math.PI * 2
                    });
                }
            }
            
            geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
            geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
            geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));
            geometry.setAttribute('rotation', new THREE.BufferAttribute(rotations, 1));
            
            geometry.userData.particleData = particleData;
            
            const vertexShader = `
                attribute float size;
                attribute vec3 color;
                attribute float rotation;
                varying vec3 vColor;
                varying float vAlpha;
                varying float vRotation;
                
                void main() {
                    vColor = color;
                    vRotation = rotation;
                    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
                    gl_PointSize = size * (300.0 / -mvPosition.z);
                    gl_Position = projectionMatrix * mvPosition;
                    vAlpha = smoothstep(-100.0, -10.0, mvPosition.z);
                }
            `;
            
            const fragmentShader = `
                varying vec3 vColor;
                varying float vAlpha;
                varying float vRotation;
                
                void main() {
                    vec2 uv = gl_PointCoord - vec2(0.5);
                    float c = cos(vRotation);
                    float s = sin(vRotation);
                    vec2 rotUV = vec2(uv.x * c - uv.y * s, uv.x * s + uv.y * c);
                    
                    float aspect = 3.0;
                    rotUV.y *= aspect;
                    
                    float n = 2.2;
                    float dist = pow(abs(rotUV.x)/0.35, n) + pow(abs(rotUV.y)/0.35, n);
                    float alpha = 1.0 - smoothstep(0.8, 1.2, dist);
                    
                    if (alpha < 0.01) discard;
                    
                    float shade = 1.0 - abs(rotUV.x) * 0.5 - abs(rotUV.y / aspect) * 0.2;
                    gl_FragColor = vec4(vColor * shade, alpha * vAlpha * 0.9);
                }
            `;
            
            const material = new THREE.ShaderMaterial({
                vertexShader: vertexShader,
                fragmentShader: fragmentShader,
                transparent: true,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });
            
            particles = new THREE.Points(geometry, material);
            scene.add(particles);
        }
        
        function onMouseMove(event) {
            mouseX = (event.clientX / window.innerWidth) * 2 - 1;
            mouseY = -(event.clientY / window.innerHeight) * 2 + 1;
        }
        
        function onWindowResize() {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        }
        
        let time = 0;
        let centerX = 0, centerY = 0;
        
        function animate() {
            requestAnimationFrame(animate);
            time += 0.016;
            
            const positions = particles.geometry.attributes.position.array;
            const rotations = particles.geometry.attributes.rotation.array;
            const particleData = particles.geometry.userData.particleData;
            const particleCount = positions.length / 3;
            
            centerX += (mouseX * 55 - centerX) * 0.002;
            centerY += (mouseY * 40 - centerY) * 0.002;
            
            for (let i = 0; i < particleCount; i++) {
                const data = particleData[i];
                
                const angle = data.baseAngle + time * data.angularSpeed * (1 + Math.sin(time * 0.5) * 0.3);
                const pulse = Math.sin(time * 0.8 + data.pulsePhase) * 2;
                const radius = data.ringRadius + pulse;
                
                const x = Math.cos(angle) * radius + centerX;
                const y = Math.sin(angle) * radius * 0.85 + centerY;
                
                const wobbleX = Math.sin(time * data.wobbleSpeed + data.wobblePhase) * data.wobbleAmount;
                const wobbleZ = Math.cos(time * data.wobbleSpeed * 0.7 + data.wobblePhase) * data.wobbleAmount * 0.5;
                
                positions[i * 3] = x + wobbleX;
                positions[i * 3 + 1] = y;
                positions[i * 3 + 2] = data.z + wobbleZ;
                
                rotations[i] = angle;
            }
            
            particles.geometry.attributes.position.needsUpdate = true;
            particles.geometry.attributes.rotation.needsUpdate = true;
            
            particles.rotation.x += (mouseY * 0.15 - particles.rotation.x) * 0.02;
            particles.rotation.y += (mouseX * 0.1 - particles.rotation.y) * 0.02;
            
            renderer.render(scene, camera);
        }
        
        init();
        
        // Login form handler
        const STORAGE_KEY = 'user_api_key';
        const errorMsg = document.getElementById('error-msg');
        const loginBtn = document.getElementById('login-btn');
        
        async function tryAutoLogin(apiKey) {
            loginBtn.textContent = 'Logging in...';
            loginBtn.disabled = true;
            try {
                const resp = await fetch('/user/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key: apiKey})
                });
                if (resp.ok) {
                    window.location.href = '/user/dashboard';
                    return true;
                } else {
                    localStorage.removeItem(STORAGE_KEY);
                }
            } catch (err) {
                console.error('Auto login failed:', err);
            }
            loginBtn.textContent = 'Login';
            loginBtn.disabled = false;
            return false;
        }
        
        (async function() {
            const savedKey = localStorage.getItem(STORAGE_KEY);
            if (savedKey) {
                document.getElementById('api-key').value = savedKey;
                await tryAutoLogin(savedKey);
            }
        })();
        
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const apiKey = document.getElementById('api-key').value;
            const remember = document.getElementById('remember').checked;
            errorMsg.classList.add('hidden');
            
            loginBtn.textContent = 'Logging in...';
            loginBtn.disabled = true;
            
            try {
                const resp = await fetch('/user/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key: apiKey})
                });
                const data = await resp.json();
                
                if (resp.ok) {
                    if (remember) {
                        localStorage.setItem(STORAGE_KEY, apiKey);
                    } else {
                        localStorage.removeItem(STORAGE_KEY);
                    }
                    window.location.href = '/user/dashboard';
                } else {
                    errorMsg.textContent = data.error || 'Login failed';
                    errorMsg.classList.remove('hidden');
                    loginBtn.textContent = 'Login';
                    loginBtn.disabled = false;
                }
            } catch (err) {
                errorMsg.textContent = 'Network error';
                errorMsg.classList.remove('hidden');
                loginBtn.textContent = 'Login';
                loginBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""


USER_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Dashboard - {name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .tab-btn.active {{ border-bottom: 2px solid #3b82f6; color: #3b82f6; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        pre {{ background: #1e293b; color: #e2e8f0; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; }}
        code {{ font-family: 'Monaco', 'Menlo', monospace; font-size: 0.875rem; }}
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <div class="flex justify-between items-center mb-6">
            <div>
                <h1 class="text-3xl font-bold text-gray-800">API Key Dashboard</h1>
                <p class="text-gray-500">{name}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="logout()" class="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600">
                    Logout
                </button>
            </div>
        </div>
        
        <div class="bg-white rounded-lg shadow mb-6">
            <div class="flex border-b">
                <button class="tab-btn active px-6 py-3 font-medium" onclick="showTab('stats')">Statistics</button>
                <button class="tab-btn px-6 py-3 font-medium" onclick="showTab('opencode')">OpenCode Config</button>
                <button class="tab-btn px-6 py-3 font-medium" onclick="showTab('usage')">Usage Guide</button>
            </div>
            
            <!-- Stats Tab -->
            <div id="tab-stats" class="tab-content active p-6">
                <div class="flex justify-end mb-4">
                    <select id="period-select" onchange="loadStats()" class="border rounded px-3 py-2 text-sm">
                        <option value="day">Today</option>
                        <option value="week">This Week</option>
                        <option value="month">This Month</option>
                    </select>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Total Requests</div>
                        <div id="total-requests" class="text-2xl font-bold text-blue-600">0</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Total Tokens</div>
                        <div id="total-tokens" class="text-2xl font-bold text-green-600">0</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Errors</div>
                        <div id="total-errors" class="text-2xl font-bold text-red-600">0</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <div class="text-gray-500 text-sm">Models Used</div>
                        <div id="model-count" class="text-2xl font-bold text-purple-600">0</div>
                    </div>
                </div>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="text-lg font-semibold">Active Sessions (Last 1 Minute)</h3>
                        <span id="active-count" class="text-sm text-gray-500">0 active</span>
                    </div>
                    <div id="active-sessions" class="space-y-2"><div class="text-gray-400 text-center py-2">No active sessions</div></div>
                </div>
                
                <div class="mb-6" style="height: 250px;">
                    <canvas id="trend-chart"></canvas>
                </div>
                
                <div>
                    <h3 class="text-lg font-semibold mb-3">Model Usage</h3>
                    <div id="model-stats" class="space-y-2"></div>
                </div>
            </div>
            
            <!-- OpenCode Config Tab -->
            <div id="tab-opencode" class="tab-content p-6">
                <h2 class="text-xl font-bold mb-4">OpenCode Configuration</h2>
                <p class="text-gray-600 mb-4">Generate opencode.json config for this proxy</p>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-2">opencode.json</h3>
                    <div class="relative">
                        <button onclick="copyConfig()" class="absolute top-2 right-2 bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">Copy</button>
                        <pre id="config-output" class="text-sm"></pre>
                    </div>
                </div>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-3">Available Models</h3>
                    <div id="models-list" class="space-y-2 max-h-64 overflow-y-auto"></div>
                </div>
                
                <div class="bg-blue-50 rounded-lg p-4">
                    <h3 class="font-semibold text-blue-800 mb-2">How to use</h3>
                    <ol class="list-decimal list-inside text-sm text-blue-700 space-y-1">
                        <li>Copy the generated <code class="bg-blue-100 px-1 rounded">opencode.json</code></li>
                        <li>Create <code class="bg-blue-100 px-1 rounded">opencode.json</code> in your project root</li>
                        <li>Paste the configuration and save</li>
                        <li>OpenCode will now use this proxy for API requests</li>
                    </ol>
                </div>
            </div>
            
            <!-- Usage Tab -->
            <div id="tab-usage" class="tab-content p-6">
                <h2 class="text-xl font-bold mb-4">How to Configure API Clients</h2>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-3">Basic Information</h3>
                    <div class="space-y-2 text-sm">
                        <div class="flex"><span class="text-gray-500 w-32">Proxy URL:</span><code class="bg-white px-2 py-1 rounded" id="proxy-url"></code></div>
                        <div class="flex"><span class="text-gray-500 w-32">API Endpoint:</span><code class="bg-white px-2 py-1 rounded">/v1/chat/completions</code></div>
                        <div class="flex"><span class="text-gray-500 w-32">Auth Header:</span><code class="bg-white px-2 py-1 rounded">Authorization: Bearer YOUR_API_KEY</code></div>
                    </div>
                </div>
                
                <div class="bg-gray-50 rounded-lg p-4 mb-6">
                    <h3 class="font-semibold mb-3">Model Name Format</h3>
                    <p class="text-gray-600 text-sm mb-3">Use <code class="bg-white px-2 py-1 rounded">provider/model</code> format:</p>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="bg-white p-3 rounded"><div class="text-xs text-gray-500 mb-1">With Provider</div><code class="text-sm">zhipu/glm-4</code></div>
                        <div class="bg-white p-3 rounded"><div class="text-xs text-gray-500 mb-1">Without Prefix</div><code class="text-sm">glm-4</code></div>
                    </div>
                </div>
                
                <div class="space-y-4">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <h3 class="font-semibold mb-3 flex items-center">
                            <span class="w-5 h-5 mr-2 bg-green-500 text-white rounded text-xs flex items-center justify-center">Py</span>
                            Python (OpenAI SDK)
                        </h3>
                        <div class="relative">
                            <button onclick="copyCode('python')" class="absolute top-2 right-2 bg-gray-700 text-white px-2 py-1 rounded text-xs">Copy</button>
                            <pre id="code-python"><code>from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY",
    base_url="<span id="base-python"></span>"
)

response = client.chat.completions.create(
    model="zhipu/glm-4",
    messages=[{{"role": "user", "content": "Hello!"}}]
)
print(response.choices[0].message.content)</code></pre>
                        </div>
                    </div>
                    
                    <div class="bg-gray-50 rounded-lg p-4">
                        <h3 class="font-semibold mb-3 flex items-center">
                            <span class="w-5 h-5 mr-2 bg-yellow-500 text-white rounded text-xs flex items-center justify-center">JS</span>
                            JavaScript
                        </h3>
                        <div class="relative">
                            <button onclick="copyCode('js')" class="absolute top-2 right-2 bg-gray-700 text-white px-2 py-1 rounded text-xs">Copy</button>
                            <pre id="code-js"><code>const response = await fetch('<span id="base-js"></span>/chat/completions', {{
  method: 'POST',
  headers: {{
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_API_KEY'
  }},
  body: JSON.stringify({{
    model: 'zhipu/glm-4',
    messages: [{{ role: 'user', content: 'Hello!' }}]
  }})
}});
const data = await response.json();</code></pre>
                        </div>
                    </div>
                    
                    <div class="bg-gray-50 rounded-lg p-4">
                        <h3 class="font-semibold mb-3 flex items-center">
                            <span class="w-5 h-5 mr-2 bg-blue-500 text-white rounded text-xs flex items-center justify-center">$</span>
                            cURL
                        </h3>
                        <div class="relative">
                            <button onclick="copyCode('curl')" class="absolute top-2 right-2 bg-gray-700 text-white px-2 py-1 rounded text-xs">Copy</button>
                            <pre id="code-curl"><code>curl <span id="base-curl"></span>/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{{"model": "zhipu/glm-4", "messages": [{{"role": "user", "content": "Hello!"}}]}}'</code></pre>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const apiKeyId = {api_key_id};
        const baseUrl = window.location.origin + '/v1';
        let trendChart = null;
        
        document.getElementById('proxy-url').textContent = baseUrl;
        document.getElementById('base-python').textContent = baseUrl;
        document.getElementById('base-js').textContent = baseUrl;
        document.getElementById('base-curl').textContent = baseUrl;
        
        function showTab(tab) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
            
            if (tab === 'opencode') loadOpenCodeConfig();
        }}
        
        async function loadStats() {{
            const period = document.getElementById('period-select').value;
            const resp = await fetch('/user/api/stats?period=' + period);
            const data = await resp.json();
            
            if (data.error) {{ window.location.href = '/user/login'; return; }}
            
            document.getElementById('total-requests').textContent = data.total_requests.toLocaleString();
            document.getElementById('total-tokens').textContent = data.total_tokens.toLocaleString();
            document.getElementById('total-errors').textContent = data.total_errors;
            document.getElementById('model-count').textContent = Object.keys(data.models || {{}}).length;
            
            const modelHtml = Object.entries(data.models || {{}}).map(([name, m]) => `
                <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                    <span class="font-medium text-sm">${{name}}</span>
                    <span class="text-sm text-gray-600">${{m.requests}} req / ${{m.tokens.toLocaleString()}} tokens</span>
                </div>
            `).join('');
            document.getElementById('model-stats').innerHTML = modelHtml || '<div class="text-gray-400">No data</div>';
            
            renderTrendChart(data.trend || {{}});
        }}
        
        function renderTrendChart(trendData) {{
            const ctx = document.getElementById('trend-chart').getContext('2d');
            if (trendChart) trendChart.destroy();
            
            const labels = Object.keys(trendData);
            const requests = labels.map(l => trendData[l].requests || 0);
            const tokens = labels.map(l => Math.floor((trendData[l].tokens || 0) / 1000));
            
            trendChart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [
                        {{ label: 'Requests', data: requests, backgroundColor: '#3b82f6', borderRadius: 4 }},
                        {{ label: 'Tokens (K)', data: tokens, backgroundColor: '#10b981', borderRadius: 4 }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{ y: {{ beginAtZero: true }} }},
                    plugins: {{ legend: {{ position: 'top' }} }}
                }}
            }});
        }}
        
        async function loadOpenCodeConfig() {{
            try {{
                const resp = await fetch('/user/api/opencode-config');
                const data = await resp.json();
                
                if (data.error) return;
                
                const config = data.config;
                config.provider['model-token-plan'].options.baseURL = window.location.origin + '/v1';
                
                const prompt = "# 请帮我将以下provider配置添加到 ~/.opencode/opencode.json 中。保留现有的providers和其他设置，只添加或更新 'model-token-plan' 这个provider。\\n\\n";
                document.getElementById('config-output').textContent = prompt + JSON.stringify(config, null, 2);
                
                const modelsHtml = data.models.map(m => `
                    <div class="flex justify-between items-center p-2 bg-white rounded">
                        <span class="font-medium text-sm">${{m.name}}</span>
                        <span class="text-xs text-gray-500">ctx: ${{m.context.toLocaleString()}} | out: ${{m.output.toLocaleString()}}</span>
                    </div>
                `).join('');
                document.getElementById('models-list').innerHTML = modelsHtml || '<div class="text-gray-400">No models</div>';
            }} catch (e) {{
                console.error('Failed to load OpenCode config:', e);
            }}
        }}
        
        function copyConfig() {{
            const config = document.getElementById('config-output').textContent;
            navigator.clipboard.writeText(config).then(() => alert('Copied!'));
        }}
        
        function copyCode(type) {{
            const el = document.getElementById('code-' + type);
            navigator.clipboard.writeText(el.textContent).then(() => alert('Copied!'));
        }}
        
        async function logout() {{
            const clearSaved = confirm('Clear saved API Key?');
            if (clearSaved) localStorage.removeItem('user_api_key');
            await fetch('/user/api/logout', {{method: 'POST'}});
            window.location.href = '/user/login';
        }}
        
        async function loadActiveSessions() {{
            const resp = await fetch('/user/api/active');
            const data = await resp.json();
            
            document.getElementById('active-count').textContent = data.active_count + ' active';
            
            if (data.active_count === 0) {{
                document.getElementById('active-sessions').innerHTML = '<div class="text-gray-400 text-center py-2">No active sessions</div>';
                return;
            }}
            
            const html = Object.entries(data.sessions).map(([model, session]) => `
                <div class="flex justify-between items-center p-2 bg-white rounded">
                    <span class="font-medium text-sm">${{model}}</span>
                    <span class="text-sm text-gray-600">${{session.requests}} req</span>
                </div>
            `).join('');
            document.getElementById('active-sessions').innerHTML = html;
        }}
        
        loadStats();
        loadActiveSessions();
        setInterval(loadStats, 30000);
        setInterval(loadActiveSessions, 60000);
    </script>
</body>
</html>
"""


class UserLoginRequest(BaseModel):
    api_key: str


def get_user_session(user_session: Optional[str] = Cookie(None)) -> Optional[int]:
    if not user_session:
        return None
    session_data = USER_SESSIONS.get(user_session)
    if not session_data:
        return None
    if datetime.now() > session_data["expires"]:
        del USER_SESSIONS[user_session]
        return None
    return session_data.get("api_key_id")


@router.get("/user/login", response_class=HTMLResponse)
async def user_login_page():
    return HTMLResponse(content=USER_LOGIN_HTML)


@router.post("/user/api/login")
async def user_login(data: UserLoginRequest, response: Response):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == data.api_key, ApiKey.is_active == True)
        )
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)

        import secrets

        session_token = secrets.token_hex(32)
        USER_SESSIONS[session_token] = {
            "api_key_id": key.id,
            "name": key.name,
            "expires": datetime.now() + timedelta(hours=USER_SESSION_EXPIRE_HOURS),
        }

        response.set_cookie(
            key="user_session",
            value=session_token,
            httponly=True,
            max_age=USER_SESSION_EXPIRE_HOURS * 3600,
        )
        logger.info(f"[USER LOGIN] API Key '{key.name}' logged in")
        return {"success": True, "name": key.name}


@router.post("/user/api/logout")
async def user_logout(response: Response, user_session: Optional[str] = Cookie(None)):
    if user_session and user_session in USER_SESSIONS:
        del USER_SESSIONS[user_session]
    response.delete_cookie("user_session")
    return {"success": True}


@router.get("/user/api/stats")
async def get_user_stats(
    api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from datetime import datetime, timedelta

    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [
            ((start + timedelta(hours=i)).strftime("%H:00")) for i in range(24)
        ]
        format_func = lambda d: d.strftime("%H:00")
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [((start + timedelta(days=i)).strftime("%m/%d")) for i in range(7)]
        format_func = lambda d: d.strftime("%m/%d")
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = (
            now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)
        ).day
        intervals = [
            ((start + timedelta(days=i)).strftime("%m/%d"))
            for i in range(days_in_month)
        ]
        format_func = lambda d: d.strftime("%m/%d")

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)

        total_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer())).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.status == "error",
                RequestLog.created_at >= start,
            )
        )
        total_errors = errors_result.scalar() or 0

        model_stats_result = await session.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("count"),
                func.sum(RequestLog.tokens["total_tokens"].as_integer()).label(
                    "tokens"
                ),
            )
            .where(RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start)
            .group_by(RequestLog.model)
        )
        model_stats_rows = model_stats_result.fetchall()
        model_stats = {
            row.model: {"requests": row.count, "tokens": row.tokens or 0}
            for row in model_stats_rows
        }

        trend_query = select(RequestLog).where(
            RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
        )
        trend_result = await session.execute(trend_query)
        trend_logs = trend_result.scalars().all()

        trend_data = {label: {"requests": 0, "tokens": 0} for label in intervals}
        for log in trend_logs:
            label = format_func(log.created_at)
            if label in trend_data:
                trend_data[label]["requests"] += 1
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                trend_data[label]["tokens"] += tokens

        return {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "models": model_stats,
            "trend": trend_data,
        }


@router.get("/user/api/active")
async def get_user_active_sessions(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.created_at >= func.now() - timedelta(minutes=1),
            )
        )
        logs = result.scalars().all()

        model_sessions = {}
        for log in logs:
            if not log.model:
                continue

            model = log.model
            if model not in model_sessions:
                model_sessions[model] = {"requests": 0}

            model_sessions[model]["requests"] += 1

        return {
            "active_count": len(model_sessions),
            "sessions": model_sessions,
        }


@router.get("/user/dashboard", response_class=HTMLResponse)
async def user_dashboard(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return RedirectResponse(url="/user/login")

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return RedirectResponse(url="/user/login")

        html = USER_DASHBOARD_HTML.format(name=key.name, api_key_id=api_key_id)
        return HTMLResponse(content=html)


@router.get("/user/api/opencode-config")
async def get_user_opencode_config(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from database import Provider, Model, ProviderModel, ApiKeyModel

    async with async_session_maker() as session:
        key_result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id)
        )
        api_key = key_result.scalar_one_or_none()
        if not api_key:
            return JSONResponse({"error": "API Key not found"}, status_code=404)

        models_result = await session.execute(
            select(ApiKeyModel).where(ApiKeyModel.api_key_id == api_key_id)
        )
        key_models = models_result.scalars().all()

        allowed_pm_ids = [km.provider_model_id for km in key_models]

        if allowed_pm_ids:
            pm_result = await session.execute(
                select(ProviderModel).where(ProviderModel.id.in_(allowed_pm_ids))
            )
        else:
            pm_result = await session.execute(select(ProviderModel))

        provider_models = pm_result.scalars().all()

        models_data = []
        models_config = {}

        for pm in provider_models:
            provider_result = await session.execute(
                select(Provider).where(Provider.id == pm.provider_id)
            )
            provider = provider_result.scalar_one_or_none()
            if not provider:
                continue

            model_result = await session.execute(
                select(Model).where(Model.id == pm.model_id)
            )
            model = model_result.scalar_one_or_none()
            if not model:
                continue

            model_key = f"{provider.name}/{model.name}"
            display_name = model.display_name or model.name

            max_output = model.max_tokens or 16384
            context_window = max_output * 8

            models_config[model_key] = {
                "name": f"{provider.name}/{display_name}",
                "modalities": {"input": ["text"], "output": ["text"]},
                "options": {"thinking": {"type": "enabled", "budgetTokens": 8192}},
                "limit": {"context": context_window, "output": max_output},
            }

            models_data.append(
                {"name": model_key, "context": context_window, "output": max_output}
            )

        config = {
            "provider": {
                "model-token-plan": {
                    "name": "Model Token Plan",
                    "options": {
                        "baseURL": "BASEURL_PLACEHOLDER",
                        "apiKey": api_key.key,
                    },
                    "models": models_config,
                }
            },
        }

        return {"config": config, "models": models_data}
