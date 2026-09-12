/* ModelGate user-side particle background (all themes).
   Deep-space style adapted from design/homepage/index-c.html, tuned down
   for data-dense dashboard pages. Dark keeps the classic indigo family with
   cyan/purple accents; blackgold runs a gold palette; light uses a very
   faint indigo wash so white pages stay clean. */
(function () {
    'use strict';

    var canvas = null;
    var ctx = null;
    var particles = [];
    var rafId = null;
    var running = false;
    var theme = 'dark';
    var width = 0;
    var height = 0;
    var mouseX = -9999;
    var mouseY = -9999;
    var resizeRaf = null;
    /* Must stay in sync with the particleScanDown animation duration in
       particle-bg.css; the scanline Y is derived from the same clock so the
       sweep can ripple particles without reading DOM layout each frame. */
    var SCAN_PERIOD_MS = 8000;
    var scanStart = 0;

    var THEMES = {
        dark: {
            colors: [[34, 211, 238], [129, 140, 248], [167, 139, 250]],
            countWide: 72,
            countNarrow: 36,
            alphaMin: 0.35,
            alphaMax: 0.85,
            sizeMin: 0.7,
            sizeMax: 2.4,
            linkAlpha: 0.22,
            linkDist: 120,
            centerFloor: 0.55
        },
        blackgold: {
            colors: [[212, 168, 83], [230, 200, 130], [184, 134, 60]],
            countWide: 72,
            countNarrow: 36,
            alphaMin: 0.26,
            alphaMax: 0.62,
            sizeMin: 0.6,
            sizeMax: 2.0,
            linkAlpha: 0.16,
            linkDist: 120,
            centerFloor: 0.50
        },
        light: {
            colors: [[99, 102, 241], [129, 140, 248], [56, 189, 248]],
            countWide: 48,
            countNarrow: 24,
            alphaMin: 0.07,
            alphaMax: 0.18,
            sizeMin: 0.4,
            sizeMax: 1.1,
            linkAlpha: 0.05,
            linkDist: 100,
            centerFloor: 0.35
        }
    };

    function palette() {
        return THEMES[theme] || THEMES.dark;
    }

    function ensureElements() {
        if (canvas) return;
        canvas = document.createElement('canvas');
        canvas.id = 'particle-bg-canvas';
        canvas.setAttribute('aria-hidden', 'true');
        var scan = document.createElement('div');
        scan.className = 'particle-scan-line';
        scan.setAttribute('aria-hidden', 'true');
        document.body.insertBefore(canvas, document.body.firstChild);
        document.body.appendChild(scan);
        ctx = canvas.getContext('2d');
        window.addEventListener('resize', onResize);
        document.addEventListener('mousemove', onMouseMove);
    }

    function seed() {
        particles = [];
        var conf = palette();
        var count = width < 768 ? conf.countNarrow : conf.countWide;
        for (var i = 0; i < count; i++) {
            var color = conf.colors[Math.floor(Math.random() * conf.colors.length)];
            particles.push({
                x: Math.random() * width,
                y: Math.random() * height,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                size: Math.random() * conf.sizeMax + (conf.sizeMin || 0.4),
                alpha: Math.random() * (conf.alphaMax - conf.alphaMin) + conf.alphaMin,
                color: color,
                scanGlow: 0
            });
        }
    }

    /* Horizontal brightness weight: bright at the page edges, dimmer in the
       middle so content stays readable. centerFloor is theme-tuned; returns
       centerFloor (center) to 1.0 (edges). */
    function edgeBoost(x) {
        var t = Math.min(Math.abs(x / width - 0.5) * 2, 1);
        var floor = palette().centerFloor || 0.35;
        return floor + (1 - floor) * Math.pow(t, 1.2);
    }

    function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
        seed();
    }

    function onResize() {
        if (!running) return;
        if (resizeRaf) cancelAnimationFrame(resizeRaf);
        resizeRaf = requestAnimationFrame(resize);
    }

    function onMouseMove(e) {
        mouseX = e.clientX;
        mouseY = e.clientY;
    }

    function draw() {
        ctx.clearRect(0, 0, width, height);
        var conf = palette();
        var i, j, p, p2, dx, dy, dist;

        /* current scanline Y from the same 8s cycle the CSS animation runs
           on; light theme hides the line so there is nothing to ripple */
        var scanY = -9999;
        if (theme !== 'light') {
            var t = (performance.now() - scanStart) % SCAN_PERIOD_MS;
            scanY = (t / SCAN_PERIOD_MS) * (height + 2) - 2;
        }

        for (i = 0; i < particles.length; i++) {
            p = particles[i];

            dx = mouseX - p.x;
            dy = mouseY - p.y;
            dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 180 && dist > 0.01) {
                var force = (180 - dist) / 180 * 0.015;
                p.vx += dx * force * 0.01;
                p.vy += dy * force * 0.01;
            }

            p.x += p.vx;
            p.y += p.vy;
            p.vx *= 0.99;
            p.vy *= 0.99;

            /* keep drifting forever: damping alone freezes particles in
               seconds, so re-energize below a gentle minimum speed */
            var sp2 = p.vx * p.vx + p.vy * p.vy;
            if (sp2 < 0.01) {
                var ang = Math.random() * Math.PI * 2;
                var sp = 0.12 + Math.random() * 0.16;
                p.vx = Math.cos(ang) * sp;
                p.vy = Math.sin(ang) * sp;
            } else if (sp2 > 0.36) {
                var clamp = 0.6 / Math.sqrt(sp2);
                p.vx *= clamp;
                p.vy *= clamp;
            }

            /* scanline sweep: part the field vertically and glow as it
               crosses, like a wave rippling through the particles */
            var sd = p.y - scanY;
            if (Math.abs(sd) < 28) {
                var sf = 1 - Math.abs(sd) / 28;
                p.vy += (sd >= 0 ? 1 : -1) * 0.05 * sf;
                p.scanGlow = sf;
            } else if (p.scanGlow) {
                p.scanGlow = 0;
            }

            if (p.x < 0) p.x = width;
            if (p.x > width) p.x = 0;
            if (p.y < 0) p.y = height;
            if (p.y > height) p.y = 0;

            var glowAlpha = p.alpha * edgeBoost(p.x);
            if (p.scanGlow) glowAlpha = Math.min(1, glowAlpha + p.scanGlow * 0.5);
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size * (p.scanGlow ? 1 + p.scanGlow * 0.6 : 1), 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + p.color.join(',') + ',' + glowAlpha.toFixed(3) + ')';
            ctx.fill();

            for (j = i + 1; j < particles.length; j++) {
                p2 = particles[j];
                dx = p.x - p2.x;
                dy = p.y - p2.y;
                dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < conf.linkDist) {
                    var boost = (edgeBoost(p.x) + edgeBoost(p2.x)) / 2;
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.strokeStyle = 'rgba(' + p.color.join(',') + ',' + ((1 - dist / conf.linkDist) * conf.linkAlpha * boost).toFixed(3) + ')';
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }

        if (running) rafId = requestAnimationFrame(draw);
    }

    function start() {
        ensureElements();
        if (!running) {
            running = true;
            /* CSS animation restarts every time the scanline is re-shown
               (display:none -> block), so resync the sweep clock with it */
            scanStart = performance.now();
            resize();
            rafId = requestAnimationFrame(draw);
        } else {
            seed();
        }
    }

    function stop() {
        running = false;
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;
        if (ctx) ctx.clearRect(0, 0, width, height);
    }

    function applyBodyClasses(on) {
        document.body.classList.toggle('has-particle-bg', on);
        document.body.classList.toggle('particle-bg-dark', on && theme === 'dark');
        document.body.classList.toggle('particle-bg-blackgold', on && theme === 'blackgold');
        document.body.classList.toggle('particle-bg-light', on && theme === 'light');
    }

    window.ParticleBG = {
        setTheme: function (mode) {
            theme = THEMES[mode] ? mode : 'dark';
            var enabled = !!mode;
            if (enabled) start();
            else stop();
            applyBodyClasses(enabled);
        },
        /* Deprecated alias: on=true maps to the classic dark behaviour. */
        setEnabled: function (on) {
            window.ParticleBG.setTheme(on ? 'dark' : null);
        }
    };
})();
