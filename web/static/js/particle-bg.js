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
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var THEMES = {
        dark: {
            colors: [[34, 211, 238], [129, 140, 248], [167, 139, 250]],
            countWide: 72,
            countNarrow: 36,
            alphaMin: 0.16,
            alphaMax: 0.50,
            sizeMax: 1.7,
            linkAlpha: 0.12,
            linkDist: 120
        },
        blackgold: {
            colors: [[212, 168, 83], [230, 200, 130], [184, 134, 60]],
            countWide: 72,
            countNarrow: 36,
            alphaMin: 0.16,
            alphaMax: 0.48,
            sizeMax: 1.7,
            linkAlpha: 0.10,
            linkDist: 120
        },
        light: {
            colors: [[99, 102, 241], [129, 140, 248], [56, 189, 248]],
            countWide: 48,
            countNarrow: 24,
            alphaMin: 0.07,
            alphaMax: 0.18,
            sizeMax: 1.1,
            linkAlpha: 0.05,
            linkDist: 100
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
                vx: (Math.random() - 0.5) * 0.25,
                vy: (Math.random() - 0.5) * 0.25,
                size: Math.random() * conf.sizeMax + 0.4,
                alpha: Math.random() * (conf.alphaMax - conf.alphaMin) + conf.alphaMin,
                color: color
            });
        }
    }

    /* Horizontal brightness weight: bright at the page edges, dimmer in the
       middle so content stays readable. Returns ~0.35 (center) to 1.0 (edges). */
    function edgeBoost(x) {
        var t = Math.min(Math.abs(x / width - 0.5) * 2, 1);
        return 0.35 + 0.65 * Math.pow(t, 1.2);
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

            if (p.x < 0) p.x = width;
            if (p.x > width) p.x = 0;
            if (p.y < 0) p.y = height;
            if (p.y > height) p.y = 0;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + p.color.join(',') + ',' + (p.alpha * edgeBoost(p.x)).toFixed(3) + ')';
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
        if (reduced) return;
        ensureElements();
        if (!running) {
            running = true;
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
            var enabled = !!mode && !reduced;
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
