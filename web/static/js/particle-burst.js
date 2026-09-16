/* ModelGate user-side interactive particle bursts.
   Clicking anywhere on the page spawns a themed burst; roughly a third of
   the particles survive as gentle floaters that drift, breathe and get
   pushed around by newer bursts (shockwave). Hovering dashboard cards
   lifts a few faint sparks. No dependencies. */
(function () {
    'use strict';

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
    var HOVER_TARGETS = '.card-shell, .file-card';
    var HOVER_THROTTLE_MS = 400;

    /* Floater settings */
    var PERSIST_CHANCE = 0.3;      /* share of burst particles that survive */
    var MAX_FLOATERS = 60;         /* hard cap; oldest fade out beyond this */
    var FLOAT_DRIFT_MAX = 0.35;    /* px/frame cruise speed */
    var FLOAT_ALPHA = 0.45;        /* multiplier vs burst alpha */
    var FLOAT_BREATH_MS = 1600;    /* alpha breathing period */
    var FLOAT_DIE_MS = 1500;       /* fade-out time when evicted */
    var SHOCK_RADIUS = 160;        /* new bursts push floaters within this */
    var SHOCK_FORCE = 3.4;
    var NO_BURST_TARGETS = 'input, textarea, [contenteditable="true"], [contenteditable=""]';

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

    function shockwave(x, y) {
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i];
            if (p.mode !== 'float') continue;
            var dx = p.x - x;
            var dy = p.y - y;
            var d = Math.sqrt(dx * dx + dy * dy);
            if (d > SHOCK_RADIUS || d < 1) continue;
            var force = SHOCK_FORCE * (1 - d / SHOCK_RADIUS);
            p.vx += (dx / d) * force;
            p.vy += (dy / d) * force;
        }
    }

    function convertToFloat(p) {
        p.mode = 'float';
        p.life = 0;
        p.maxLife = Infinity;
        p.size = 1.0 + Math.random() * 1.6;
        p.alpha *= FLOAT_ALPHA;
        p.phase = Math.random() * Math.PI * 2;
        p.vx = (Math.random() - 0.5) * 2 * FLOAT_DRIFT_MAX;
        p.vy = (Math.random() - 0.5) * 2 * FLOAT_DRIFT_MAX;
    }

    function evictOldestFloater() {
        var floaters = parts.filter(function (p) { return p.mode === 'float'; });
        if (floaters.length <= MAX_FLOATERS) return;
        floaters.sort(function (a, b) { return a.bornAt - b.bornAt; });
        var overflow = floaters.length - MAX_FLOATERS;
        for (var i = 0; i < overflow; i++) {
            floaters[i].mode = 'dying';
            floaters[i].life = 0;
            floaters[i].maxLife = FLOAT_DIE_MS;
        }
    }

    function spawn(x, y, count, opts) {
        ensureCanvas();
        opts = opts || {};
        var theme = themeName();
        var colors = PALETTES[theme] || PALETTES.dark;
        var alpha = ALPHA[theme] || 0.85;
        var born = performance.now();
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
                alpha: alpha * (opts.faint ? 0.5 : 1),
                mode: 'burst',
                persist: !opts.upOnly && !opts.faint && Math.random() < PERSIST_CHANCE,
                bornAt: born
            });
        }
        if (!opts.upOnly && !opts.faint) shockwave(x, y);
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

    function stepFloat(p, dt) {
        var speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
        if (speed > FLOAT_DRIFT_MAX) {
            var k = Math.max(FLOAT_DRIFT_MAX / speed, 0.94);
            p.vx *= k;
            p.vy *= k;
        } else {
            p.vx += (Math.random() - 0.5) * 0.02;
            p.vy += (Math.random() - 0.5) * 0.02;
        }
        p.x += p.vx * dt / 16;
        p.y += p.vy * dt / 16;
        /* wrap around screen edges so floaters never leave */
        if (canvas) {
            if (p.x < -8) p.x = canvas.width + 8;
            else if (p.x > canvas.width + 8) p.x = -8;
            if (p.y < -8) p.y = canvas.height + 8;
            else if (p.y > canvas.height + 8) p.y = -8;
        }
    }

    function tick(now) {
        var dt = Math.min(now - lastFrame, 50);
        lastFrame = now;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        var converted = false;

        for (var i = parts.length - 1; i >= 0; i--) {
            var p = parts[i];
            p.life += dt;

            if (p.mode === 'float') {
                stepFloat(p, dt);
                var breath = 0.55 + 0.45 * Math.sin((p.life / FLOAT_BREATH_MS) * Math.PI * 2 + p.phase);
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(' + p.color.join(',') + ',' + (p.alpha * breath).toFixed(3) + ')';
                ctx.fill();
                continue;
            }

            if (p.mode === 'dying') {
                if (p.life >= p.maxLife) {
                    parts.splice(i, 1);
                    continue;
                }
                stepFloat(p, dt);
                var dfade = 1 - p.life / p.maxLife;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size * (0.5 + dfade * 0.5), 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(' + p.color.join(',') + ',' + (p.alpha * dfade).toFixed(3) + ')';
                ctx.fill();
                continue;
            }

            /* burst mode */
            if (p.life >= p.maxLife) {
                if (p.persist) {
                    convertToFloat(p);
                    converted = true;
                } else {
                    parts.splice(i, 1);
                }
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

        if (converted) evictOldestFloater();

        if (parts.length) rafId = requestAnimationFrame(tick);
        else {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            stopLoop();
        }
    }

    document.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest(NO_BURST_TARGETS)) return;
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
