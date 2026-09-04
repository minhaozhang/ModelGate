/* ModelGate user-side particle background (dark theme only).
   Deep-space style adapted from design/homepage/index-c.html, tuned down
   for data-dense dashboard pages: fewer particles, lower alpha, subtle links. */
(function () {
    'use strict';

    var canvas = null;
    var ctx = null;
    var particles = [];
    var rafId = null;
    var running = false;
    var width = 0;
    var height = 0;
    var mouseX = -9999;
    var mouseY = -9999;
    var resizeRaf = null;
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

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
        var count = width < 768 ? 24 : 48;
        for (var i = 0; i < count; i++) {
            particles.push({
                x: Math.random() * width,
                y: Math.random() * height,
                vx: (Math.random() - 0.5) * 0.25,
                vy: (Math.random() - 0.5) * 0.25,
                size: Math.random() * 1.3 + 0.4,
                alpha: Math.random() * 0.16 + 0.06
            });
        }
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
            ctx.fillStyle = 'rgba(129, 140, 248, ' + p.alpha + ')';
            ctx.fill();

            for (j = i + 1; j < particles.length; j++) {
                p2 = particles[j];
                dx = p.x - p2.x;
                dy = p.y - p2.y;
                dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 110) {
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.strokeStyle = 'rgba(129, 140, 248, ' + (1 - dist / 110) * 0.045 + ')';
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
        }
    }

    function stop() {
        running = false;
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;
        if (ctx) ctx.clearRect(0, 0, width, height);
    }

    window.ParticleBG = {
        setEnabled: function (on) {
            var enabled = !!on && !reduced;
            if (enabled) start();
            else stop();
            document.body.classList.toggle('has-particle-bg', enabled);
        }
    };
})();
