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
    /* Link pulses: bright dots hop between linked particles like requests
       flowing through the gateway (dark themes only). */
    var PULSE_SPEED = 0.35;
    var pulses = [];
    var nextPulseAt = 0;
    var lastFrame = 0;

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
        document.body.insertBefore(canvas, document.body.firstChild);
        ctx = canvas.getContext('2d');
        window.addEventListener('resize', onResize);
        document.addEventListener('mousemove', onMouseMove);
    }

    function seed() {
        particles = [];
        pulses = [];
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
                glow: 0
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
        if (!running) {
            if (REDUCE_MOTION) { resize(); draw(); }
            return;
        }
        if (resizeRaf) cancelAnimationFrame(resizeRaf);
        resizeRaf = requestAnimationFrame(resize);
    }

    function onMouseMove(e) {
        mouseX = e.clientX;
        mouseY = e.clientY;
    }

    function pulseMax() {
        return width < 768 ? 2 : 3;
    }

    function neighborsWithin(p, maxDist) {
        var out = [];
        var r2 = maxDist * maxDist;
        for (var k = 0; k < particles.length; k++) {
            var q = particles[k];
            if (q === p) continue;
            var ddx = q.x - p.x;
            var ddy = q.y - p.y;
            if (ddx * ddx + ddy * ddy < r2) out.push(q);
        }
        return out;
    }

    function neighborsOf(p, conf) {
        return neighborsWithin(p, conf.linkDist);
    }

    function spawnPulse(conf) {
        if (!particles.length) return;
        var a = particles[Math.floor(Math.random() * particles.length)];
        var nb = neighborsOf(a, conf);
        if (!nb.length) return;
        var b = nb[Math.floor(Math.random() * nb.length)];
        a.glow = 1;
        pulses.push({ from: a, to: b, t: 0, hopsLeft: 8 + Math.floor(Math.random() * 9), seen: [a, b] });
        nextPulseAt = performance.now() + 2500 + Math.random() * 3000;
    }

    function updatePulses(dt, conf, now) {
        var alive = [];
        var born = [];
        for (var k = 0; k < pulses.length; k++) {
            var pl = pulses[k];
            pl.t += PULSE_SPEED * dt;
            var dx = pl.to.x - pl.from.x;
            var dy = pl.to.y - pl.from.y;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist > conf.linkDist * 1.5) continue; /* endpoints drifted apart or wrapped: drop */
            if (pl.t >= dist) {
                pl.to.glow = 1;
                pl.hopsLeft--;
                if (pl.hopsLeft <= 0) continue; /* signal delivered */
                /* lightning never retraces a visited particle; when the local
                   mesh runs dry it arcs progressively farther (2x -> 3.5x ->
                   5x link distance) so the path always keeps moving forward */
                var fresh = function (q) {
                    return q !== pl.from && pl.seen.indexOf(q) < 0;
                };
                var nb = neighborsOf(pl.to, conf).filter(fresh);
                if (!nb.length) {
                    var arcs = [2, 3.5, 5];
                    for (var ai = 0; ai < arcs.length && !nb.length; ai++) {
                        nb = neighborsWithin(pl.to, conf.linkDist * arcs[ai]).filter(fresh);
                    }
                }
                if (!nb.length) continue; /* every nearby particle visited: discharge ends */
                var main = nb[Math.floor(Math.random() * nb.length)];
                /* lightning fork: sometimes a second pulse splits off and
                   takes a different branch through the mesh */
                if (Math.random() < 0.35 && alive.length + born.length + 1 < pulseMax()) {
                    var forkNbs = nb.filter(function (q) { return q !== main; });
                    if (forkNbs.length) {
                        born.push({ from: pl.to, to: forkNbs[Math.floor(Math.random() * forkNbs.length)], t: 0, hopsLeft: 3 + Math.floor(Math.random() * 4), seen: pl.seen.slice() });
                    }
                }
                pl.from = pl.to;
                pl.to = main;
                pl.seen.push(main);
                pl.t = 0;
            }
            alive.push(pl);
        }
        pulses = alive.concat(born);
        if (now > nextPulseAt && pulses.length < pulseMax()) spawnPulse(conf);
    }

    function drawPulses(conf) {
        var rgb = conf.colors[0].join(',');
        for (var k = 0; k < pulses.length; k++) {
            var pl = pulses[k];
            var dx = pl.to.x - pl.from.x;
            var dy = pl.to.y - pl.from.y;
            var dist = Math.sqrt(dx * dx + dy * dy) || 1;
            var f = Math.min(1, pl.t / dist);
            var px = pl.from.x + dx * f;
            var py = pl.from.y + dy * f;
            /* trail along the traversed link */
            ctx.beginPath();
            ctx.moveTo(pl.from.x, pl.from.y);
            ctx.lineTo(px, py);
            ctx.strokeStyle = 'rgba(' + rgb + ',0.55)';
            ctx.lineWidth = 1;
            ctx.stroke();
            /* halo + hot core */
            ctx.beginPath();
            ctx.arc(px, py, 5, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + rgb + ',0.22)';
            ctx.fill();
            ctx.beginPath();
            ctx.arc(px, py, 1.8, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + rgb + ',0.95)';
            ctx.fill();
        }
    }

    function draw() {
        ctx.clearRect(0, 0, width, height);
        var conf = palette();
        var i, j, p, p2, dx, dy, dist;
        var now = performance.now();
        var dt = lastFrame ? Math.min(50, now - lastFrame) : 16;
        lastFrame = now;

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

            /* pulse-visit glow fades out gradually */
            if (p.glow > 0.01) p.glow *= 0.94; else p.glow = 0;

            if (p.x < 0) p.x = width;
            if (p.x > width) p.x = 0;
            if (p.y < 0) p.y = height;
            if (p.y > height) p.y = 0;

            var glowAlpha = p.alpha * edgeBoost(p.x);
            if (p.glow) glowAlpha = Math.min(1, glowAlpha + p.glow * 0.5);
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size * (p.glow ? 1 + p.glow * 0.6 : 1), 0, Math.PI * 2);
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

        if (theme !== 'light') {
            updatePulses(dt, conf, now);
            drawPulses(conf);
        }

        if (running) rafId = requestAnimationFrame(draw);
    }

    var REDUCE_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function start() {
        ensureElements();
        if (!running) {
            /* honour prefers-reduced-motion: draw one static frame, no loop */
            running = !REDUCE_MOTION;
            pulses = [];
            lastFrame = 0;
            nextPulseAt = performance.now() + 1200;
            resize();
            if (running) {
                rafId = requestAnimationFrame(draw);
            } else {
                draw();
            }
        } else {
            seed();
        }
    }

    function stop() {
        running = false;
        pulses = [];
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
