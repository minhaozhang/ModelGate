# Three.js 粒子 3D 效果实现指南

> 参考: [Google Antigravity](https://antigravity.google/)

## 最终实现效果

登录页面实现了**环形磁场粒子效果**，模拟磁铁吸引铁屑的视觉效果：

1. **米粒形状粒子** - 使用自定义 Shader 绘制细长的米粒形状（superellipse 超椭圆）
2. **环形磁场排列** - 粒子分布成多层同心圆环，像磁力线分布
3. **径向方向对齐** - 米粒方向指向圆心（N极向内，S极向外）
4. **鼠标跟随** - 整个环形结构缓慢跟随鼠标移动
5. **3D 倾斜** - 鼠标移动时整体有轻微的 3D 翻转效果
6. **脉动呼吸** - 圆环半径有轻微的呼吸脉动
7. **透明登录框** - 深色半透明登录框，粒子可见

## 技术实现

### 文件位置

```
templates/
└── login.py          # LOGIN_PAGE_HTML 包含完整的 Three.js 代码
```

### 核心技术点

#### 1. 自定义 Shader（米粒形状）

使用 ShaderMaterial 替代 PointsMaterial，在片元着色器中绘制米粒形状：

```javascript
// 顶点着色器 - 传递旋转角度
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

// 片元着色器 - 绘制米粒形状
const fragmentShader = `
    varying vec3 vColor;
    varying float vAlpha;
    varying float vRotation;
    
    void main() {
        vec2 uv = gl_PointCoord - vec2(0.5);
        
        // 旋转 UV
        float c = cos(vRotation);
        float s = sin(vRotation);
        vec2 rotUV = vec2(uv.x * c - uv.y * s, uv.x * s + uv.y * c);
        
        // 米粒形状：细长的超椭圆
        float aspect = 3.0;  // 长宽比
        rotUV.y *= aspect;
        
        float n = 2.2;  // 超椭圆指数，越大越尖锐
        float dist = pow(abs(rotUV.x)/0.35, n) + pow(abs(rotUV.y)/0.35, n);
        float alpha = 1.0 - smoothstep(0.8, 1.2, dist);
        
        if (alpha < 0.01) discard;
        
        // 3D 阴影效果
        float shade = 1.0 - abs(rotUV.x) * 0.5 - abs(rotUV.y / aspect) * 0.2;
        gl_FragColor = vec4(vColor * shade, alpha * vAlpha * 0.9);
    }
`;
```

#### 2. 环形分布

粒子按同心圆环分布，每环粒子数量相同：

```javascript
const rings = 10;  // 圆环层数
const particlesPerRing = Math.floor(particleCount / rings);

for (let ring = 0; ring < rings; ring++) {
    const ringRadius = 10 + ring * 10;  // 环半径递增
    
    for (let i = 0; i < particlesPerRing; i++) {
        const angle = (i / particlesPerRing) * Math.PI * 2;
        const x = Math.cos(angle) * ringRadius;
        const y = Math.sin(angle) * ringRadius * 0.85;  // Y轴压缩
        const z = (Math.random() - 0.5) * 25;  // Z轴随机深度
        
        // 粒子方向：径向（指向圆心）
        rotations[idx] = angle;
    }
}
```

#### 3. 鼠标跟随（缓动）

使用线性插值实现平滑跟随：

```javascript
// 跟随速度 0.002，越小越慢
centerX += (mouseX * 55 - centerX) * 0.002;
centerY += (mouseY * 40 - centerY) * 0.002;
```

#### 4. 3D 倾斜（缓动）

```javascript
// 翻转效果也使用缓动，系数 0.02
particles.rotation.x += (mouseY * 0.15 - particles.rotation.x) * 0.02;
particles.rotation.y += (mouseX * 0.1 - particles.rotation.y) * 0.02;
```

#### 5. 脉动效果

```javascript
// 呼吸脉动
const pulse = Math.sin(time * 0.8 + data.pulsePhase) * 2;
const radius = data.ringRadius + pulse;
```

### 关键参数配置

| 参数 | 值 | 说明 |
|------|-----|------|
| `particleCount` | 600 (移动端) / 1800 (桌面) | 粒子数量 |
| `rings` | 10 | 圆环层数 |
| `ringRadius` | 10 + ring * 10 | 每层半径 |
| `aspect` | 0.85 | Y轴压缩比例 |
| `followSpeed` | 0.002 | 鼠标跟随速度 |
| `tiltSpeed` | 0.02 | 3D 翻转速度 |
| `tiltAmount` | 0.15 (X) / 0.1 (Y) | 翻转幅度 |
| `pulseSpeed` | 0.8 | 脉动速度 |
| `pulseAmount` | 2 | 脉动幅度 |

### 登录框样式

```css
.login-card {
    background: rgba(10, 10, 20, 0.2);      /* 20% 透明度 */
    backdrop-filter: blur(2px);              /* 轻微模糊 */
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}
```

### 颜色方案

Google 风格六色：

```javascript
const colorPalette = [
    [0.26, 0.52, 0.96],  // Google Blue
    [0.96, 0.26, 0.21],  // Google Red
    [0.98, 0.73, 0.02],  // Google Yellow
    [0.13, 0.69, 0.33],  // Google Green
    [0.55, 0.36, 0.96],  // Purple
    [0.0, 0.73, 0.83],   // Cyan
];
```

### 性能优化

1. **移动端减少粒子** - `window.innerWidth < 768 ? 600 : 1800`
2. **BufferGeometry** - 高性能存储位置、颜色、大小、旋转数据
3. **ShaderMaterial** - GPU 计算形状和旋转，避免 CPU 开销
4. **限制像素比** - `Math.min(window.devicePixelRatio, 2)`

## 完整代码结构

```html
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <style>
        /* 粒子容器 + 登录框样式 */
    </style>
</head>
<body>
    <div id="particles-container"></div>
    <div class="login-card">...</div>
    
    <script>
        // 1. init() - 创建场景、相机、渲染器
        // 2. createParticles() - 创建粒子几何体 + ShaderMaterial
        // 3. onMouseMove() - 更新鼠标位置
        // 4. animate() - 动画循环：
        //    - 计算中心位置（缓动跟随鼠标）
        //    - 更新每个粒子位置（旋转 + 脉动 + wobble）
        //    - 更新旋转角度（径向）
        //    - 更新整体 3D 倾斜（缓动）
        // 5. 登录表单处理
    </script>
</body>
</html>
```

## 实现状态

- [x] 基础粒子背景
- [x] 米粒形状（自定义 Shader）
- [x] 环形磁场排列
- [x] 径向方向对齐
- [x] 鼠标跟随（缓动）
- [x] 3D 倾斜效果（缓动）
- [x] 脉动呼吸效果
- [x] 透明登录框
- [x] 响应式适配（移动端减少粒子）

## 参考资源

- [Three.js 官方文档](https://threejs.org/docs/)
- [Three.js ShaderMaterial](https://threejs.org/docs/#api/en/materials/ShaderMaterial)
- [Superellipse (Wikipedia)](https://en.wikipedia.org/wiki/Superellipse)
- [Google Antigravity](https://antigravity.google/)
