LOGIN_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Login - API Proxy</title>
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
        .login-card input {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #fff;
        }
        .login-card input::placeholder {
            color: rgba(255, 255, 255, 0.4);
        }
        .login-card input:focus {
            border-color: rgba(100, 150, 255, 0.6);
            background: rgba(255, 255, 255, 0.12);
        }
    </style>
</head>
<body class="min-h-screen flex items-center justify-center overflow-hidden">
    <div id="particles-container"></div>
    
    <div class="login-card rounded-2xl shadow-2xl p-8 w-full max-w-md mx-4">
        <h1 class="text-2xl font-bold text-white mb-6 text-center">API Proxy Login</h1>
        <form id="login-form" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1" style="color: rgba(255,255,255,0.8)">Username</label>
                <input type="text" id="username" required 
                    class="w-full rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder="Enter username">
            </div>
            <div>
                <label class="block text-sm font-medium mb-1" style="color: rgba(255,255,255,0.8)">Password</label>
                <input type="password" id="password" required 
                    class="w-full rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder="Enter admin password">
            </div>
            <div id="error" class="text-red-400 text-sm hidden"></div>
            <button type="submit" class="w-full bg-gradient-to-r from-blue-500 to-purple-500 text-white py-2.5 rounded-lg hover:from-blue-600 hover:to-purple-600 font-medium transition-all shadow-lg hover:shadow-xl">
                Login
            </button>
        </form>
    </div>
    
    <script>
        // Three.js Particle System
        let scene, camera, renderer, particles;
        let mouseX = 0, mouseY = 0;
        
        function init() {
            const container = document.getElementById('particles-container');
            
            // Scene
            scene = new THREE.Scene();
            
            // Camera
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            camera.position.z = 50;
            
            // Renderer
            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            renderer.setClearColor(0x0d1117, 1);
            container.appendChild(renderer.domElement);
            
            // Create particles
            createParticles();
            
            // Mouse move listener
            document.addEventListener('mousemove', onMouseMove);
            
            // Resize listener
            window.addEventListener('resize', onWindowResize);
            
            // Start animation
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
            
            // Create particles in concentric rings - spread wider
            const rings = 10;
            const particlesPerRing = Math.floor(particleCount / rings);
            
            for (let ring = 0; ring < rings; ring++) {
                const ringRadius = 10 + ring * 10;  // Wider spacing, more rings
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
                    
                    // Tangent direction (along the ring)
                    rotations[idx] = angle + Math.PI / 2;
                    
                    particleData.push({
                        x: x,
                        y: y,
                        z: z,
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
            
            // Custom shader for rice-grain shaped particles with rotation
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
                    
                    // Rotate UV based on particle rotation
                    float c = cos(vRotation);
                    float s = sin(vRotation);
                    vec2 rotUV = vec2(
                        uv.x * c - uv.y * s,
                        uv.x * s + uv.y * c
                    );
                    
                    // Rice grain: tall narrow ellipse with pointed ends
                    float aspect = 3.0;
                    rotUV.y *= aspect;
                    
                    // Superellipse for pointed ends
                    float n = 2.2;
                    float rx = 0.35;
                    float ry = 0.35;
                    float dist = pow(abs(rotUV.x)/rx, n) + pow(abs(rotUV.y)/ry, n);
                    
                    // Soft edge
                    float alpha = 1.0 - smoothstep(0.8, 1.2, dist);
                    
                    if (alpha < 0.01) discard;
                    
                    // 3D shading effect
                    float shade = 1.0 - abs(rotUV.x) * 0.5 - abs(rotUV.y / aspect) * 0.2;
                    vec3 finalColor = vColor * shade;
                    
                    gl_FragColor = vec4(finalColor, alpha * vAlpha * 0.9);
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
            
            // Center follows mouse smoothly (slower) - wider range
            centerX += (mouseX * 55 - centerX) * 0.002;
            centerY += (mouseY * 40 - centerY) * 0.002;
            
            for (let i = 0; i < particleCount; i++) {
                const data = particleData[i];
                
                // Rotate around center
                const angle = data.baseAngle + time * data.angularSpeed * (1 + Math.sin(time * 0.5) * 0.3);
                
                // Pulsing radius
                const pulse = Math.sin(time * 0.8 + data.pulsePhase) * 2;
                const radius = data.ringRadius + pulse;
                
                // Calculate position - more circular to reach corners
                const x = Math.cos(angle) * radius + centerX;
                const y = Math.sin(angle) * radius * 0.85 + centerY;
                
                // Wobble
                const wobbleX = Math.sin(time * data.wobbleSpeed + data.wobblePhase) * data.wobbleAmount;
                const wobbleZ = Math.cos(time * data.wobbleSpeed * 0.7 + data.wobblePhase) * data.wobbleAmount * 0.5;
                
                positions[i * 3] = x + wobbleX;
                positions[i * 3 + 1] = y;
                positions[i * 3 + 2] = data.z + wobbleZ;
                
                // Rotation: radial direction (pointing toward/away from center, like magnetic field lines)
                rotations[i] = angle;
            }
            
            particles.geometry.attributes.position.needsUpdate = true;
            particles.geometry.attributes.rotation.needsUpdate = true;
            
            // Subtle 3D tilt based on mouse (smooth easing)
            particles.rotation.x += (mouseY * 0.15 - particles.rotation.x) * 0.02;
            particles.rotation.y += (mouseX * 0.1 - particles.rotation.y) * 0.02;
            
            renderer.render(scene, camera);
        }
        
        // Initialize on load
        init();
        
        // Login form handler
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorEl = document.getElementById('error');
            try {
                const resp = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                const data = await resp.json();
                if (data.success) {
                    window.location.href = '/home';
                } else {
                    errorEl.textContent = data.error || 'Login failed';
                    errorEl.classList.remove('hidden');
                }
            } catch (err) {
                errorEl.textContent = 'Connection error';
                errorEl.classList.remove('hidden');
            }
        });
    </script>
</body>
</html>
"""
