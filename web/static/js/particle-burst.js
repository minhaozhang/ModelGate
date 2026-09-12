/* ModelGate user-side interactive particle bursts.
   Click on interactive elements (buttons/links/selects) spawns a small
   themed burst; hovering dashboard cards lifts a few faint sparks.
   No dependencies; disabled under prefers-reduced-motion. */
(function () {
    'use strict';

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var canvas = null;
    var ctx = null;
    var parts = [];
    var rafId = null;
    var lastFrame = 0;
    var hoverSeen = new WeakMap();

    var PALETTES = {
        dark: [[34, 211, 238], [129, 140, 248], [167, 139, 250]],
        blackgold: [[212, 168, 83], [230, 200, 130], [184, 134, 60]],
        light: [[99, 102, 241], [129, 140, 248], [56, 189, 248]]
    };
    var ALPHA = { dark: 0.85, blackgold: 0.85, light: 0.55 };
    var MAX_PARTS = 220;
    var CLICK_TARGETS = 'button, [role="button"], a, select, label, summary';
    var HOVER_TARGETS = '.card-shell, .file-card';
    var HOVER_THROTTLE_MS = 400;

    function themeName() {
        var cl = document.body.classList;
        if (cl.contains('theme-blackgold')) return 'blackgold';
        if (cl.contains('theme-dark')) return 'dark';
        return 'light';
    }

    function ensureCanvas() {
        if (canvas) return;
        canvas = document.createElement('canvas');
        canvas.id = 'particle-burst-canvas';
        canvas.setAttribute('aria-hidden', 'true');
        document.body.appendChild(canvas);
        ctx = canvas.getContext('2d');
        resize();
        window.addEventListener('resize', resize);
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) {
                parts = [];
                stopLoop();
            }
        });
    }

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }

    function spawn(x, y, count, opts) {
        ensureCanvas();
        opts = opts || {};
        var theme = themeName();
        var colors = PALETTES[theme] || PALETTES.dark;
        var alpha = ALPHA[theme] || 0.85;
        for (var i = 0; i < count; i++) {
            if (parts.length >= MAX_PARTS) break;
            var angle = opts.upOnly
                ? -Math.PI / 2 + (Math.random() - 0.5) * 1.4
                : Math.random() * Math.PI * 2;
            var speed = opts.upOnly
                ? 0.6 + Math.random() * 1.2
                : 1.4 + Math.random() * 2.6;
            parts.push({
                x: x,
                y: y,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed,
                size: 1.2 + Math.random() * 1.8,
                life: 0,
                maxLife: 420 + Math.random() * 240,
                color: colors[Math.floor(Math.random() * colors.length)],
                alpha: alpha * (opts.faint ? 0.5 : 1)
            });
        }
        startLoop();
    }

    function startLoop() {
        if (rafId) return;
        lastFrame = performance.now();
        rafId = requestAnimationFrame(tick);
    }

    function stopLoop() {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;
    }

    function tick(now) {
        var dt = Math.min(now - lastFrame, 50);
        lastFrame = now;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        for (var i = parts.length - 1; i >= 0; i--) {
            var p = parts[i];
            p.life += dt;
            if (p.life >= p.maxLife) {
                parts.splice(i, 1);
                continue;
            }
            p.vx *= 0.965;
            p.vy = p.vy * 0.965 + 0.055;
            p.x += p.vx * dt / 16;
            p.y += p.vy * dt / 16;

            var fade = 1 - p.life / p.maxLife;
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size * (0.5 + fade * 0.5), 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + p.color.join(',') + ',' + (p.alpha * fade).toFixed(3) + ')';
            ctx.fill();
        }

        if (parts.length) rafId = requestAnimationFrame(tick);
        else {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            stopLoop();
        }
    }

    document.addEventListener('click', function (e) {
        var target = e.target.closest && e.target.closest(CLICK_TARGETS);
        if (!target) return;
        if (target.disabled) return;
        spawn(e.clientX, e.clientY, 12);
    });

    document.addEventListener('mouseover', function (e) {
        var target = e.target.closest && e.target.closest(HOVER_TARGETS);
        if (!target) return;
        var now = performance.now();
        var last = hoverSeen.get(target) || 0;
        if (now - last < HOVER_THROTTLE_MS) return;
        hoverSeen.set(target, now);
        var rect = target.getBoundingClientRect();
        spawn(
            rect.left + rect.width * (0.2 + Math.random() * 0.6),
            rect.top + 4,
            3,
            { upOnly: true, faint: true }
        );
    });
})();
