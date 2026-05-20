(function () {
    const STYLE_ID = 'mg-dp-style';

    function injectStyle() {
        if (document.getElementById(STYLE_ID)) return;
        const s = document.createElement('style');
        s.id = STYLE_ID;
        s.textContent = `
.mg-dp-wrap{position:relative;display:inline-block}
.mg-dp-input{border:1px solid #e5e7eb;border-radius:0.375rem;padding:0.5rem 0.75rem;font-size:0.8125rem;cursor:pointer;background:#fff;color:#374151;min-width:220px;user-select:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mg-dp-input:hover{border-color:#d1d5db}
.mg-dp-input.active{border-color:#3b82f6;box-shadow:0 0 0 2px rgba(59,130,246,0.25)}
.mg-dp-input.placeholder{color:#9ca3af}
.mg-dp-panel{position:absolute;top:calc(100% + 4px);left:0;z-index:999;background:#fff;border:1px solid #e5e7eb;border-radius:0.5rem;box-shadow:0 4px 16px rgba(0,0,0,0.12);padding:12px;width:296px}
.mg-dp-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.mg-dp-header button{background:none;border:none;cursor:pointer;padding:4px 8px;border-radius:4px;color:#374151;font-size:0.875rem}
.mg-dp-header button:hover{background:#f3f4f6}
.mg-dp-header .mg-dp-title{font-weight:600;font-size:0.875rem;color:#1e293b}
.mg-dp-weekdays{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;margin-bottom:4px}
.mg-dp-weekdays span{font-size:0.75rem;color:#9ca3af;font-weight:500;padding:4px 0}
.mg-dp-days{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
.mg-dp-day{width:36px;height:32px;display:flex;align-items:center;justify-content:center;border-radius:6px;font-size:0.8125rem;cursor:pointer;color:#374151;border:none;background:none;transition:background .1s}
.mg-dp-day:hover:not(.disabled):not(.other){background:#f3f4f6}
.mg-dp-day.other{color:#d1d5db;cursor:default}
.mg-dp-day.disabled{color:#e5e7eb;cursor:not-allowed}
.mg-dp-day.today{font-weight:700;color:#3b82f6}
.mg-dp-day.selected{background:#3b82f6;color:#fff!important}
.mg-dp-day.in-range{background:#eff6ff;color:#1e40af}
.mg-dp-day.range-start{border-radius:6px 0 0 6px;background:#3b82f6;color:#fff}
.mg-dp-day.range-end{border-radius:0 6px 6px 0;background:#3b82f6;color:#fff}
.mg-dp-day.range-start.range-end{border-radius:6px}
.mg-dp-time{margin-top:8px;padding-top:8px;border-top:1px solid #f3f4f6;display:flex;gap:8px;align-items:center;justify-content:center}
.mg-dp-time label{font-size:0.75rem;color:#6b7280}
.mg-dp-time input{width:60px;border:1px solid #e5e7eb;border-radius:4px;padding:2px 6px;font-size:0.8125rem;text-align:center}
.mg-dp-footer{margin-top:8px;padding-top:8px;border-top:1px solid #f3f4f6;display:flex;justify-content:flex-end;gap:6px}
.mg-dp-footer button{padding:4px 12px;border-radius:4px;font-size:0.8125rem;cursor:pointer;border:1px solid #e5e7eb;background:#fff;color:#374151}
.mg-dp-footer button:hover{background:#f9fafb}
.mg-dp-footer .mg-dp-ok{background:#3b82f6;color:#fff;border-color:#3b82f6}
.mg-dp-footer .mg-dp-ok:hover{background:#2563eb}
body.theme-dark .mg-dp-input{background:#0f172a;color:#e5e7eb;border-color:#334155}
body.theme-dark .mg-dp-input:hover{border-color:#475569}
body.theme-dark .mg-dp-input.active{border-color:#3b82f6;box-shadow:0 0 0 2px rgba(59,130,246,0.3)}
body.theme-dark .mg-dp-panel{background:#0f172a;border-color:#334155;box-shadow:0 4px 16px rgba(0,0,0,0.4)}
body.theme-dark .mg-dp-header button{color:#e5e7eb}
body.theme-dark .mg-dp-header button:hover{background:#1e293b}
body.theme-dark .mg-dp-header .mg-dp-title{color:#f1f5f9}
body.theme-dark .mg-dp-day{color:#e5e7eb}
body.theme-dark .mg-dp-day:hover:not(.disabled):not(.other){background:#1e293b}
body.theme-dark .mg-dp-day.other{color:#475569}
body.theme-dark .mg-dp-day.today{color:#60a5fa}
body.theme-dark .mg-dp-day.in-range{background:rgba(59,130,246,0.15);color:#93c5fd}
body.theme-dark .mg-dp-time input{background:#0f172a;color:#e5e7eb;border-color:#334155}
body.theme-dark .mg-dp-footer button{background:#0f172a;color:#e5e7eb;border-color:#334155}
body.theme-dark .mg-dp-footer button:hover{background:#1e293b}
body.theme-dark .mg-dp-footer .mg-dp-ok{background:#3b82f6;color:#fff;border-color:#3b82f6}
`;
        document.head.appendChild(s);
    }

    function pad(n) { return String(n).padStart(2, '0'); }

    function isSameDay(a, b) {
        return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    function dateStr(d) {
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    function datetimeStr(d) {
        return `${dateStr(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    function getMonthDays(year, month) {
        const first = new Date(year, month, 1);
        const last = new Date(year, month + 1, 0);
        const days = [];
        const startDow = first.getDay();
        for (let i = startDow - 1; i >= 0; i--) {
            const d = new Date(year, month, -i);
            days.push({ date: d, other: true });
        }
        for (let i = 1; i <= last.getDate(); i++) {
            days.push({ date: new Date(year, month, i), other: false });
        }
        const remain = 42 - days.length;
        for (let i = 1; i <= remain; i++) {
            days.push({ date: new Date(year, month + 1, i), other: true });
        }
        return days;
    }

    const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

    function createInstance(opts) {
        injectStyle();

        const container = typeof opts.el === 'string' ? document.querySelector(opts.el) : opts.el;
        const type = opts.type || 'date';
        const onChange = opts.onChange || function () {};
        const placeholder = opts.placeholder || (type === 'datetime' ? 'Select date & time range' : 'Select date range');

        let viewYear, viewMonth;
        let startDate = null, endDate = null;
        let picking = false;
        let startHour = 0, startMin = 0, endHour = 23, endMin = 59;
        let panelVisible = false;

        const now = new Date();
        viewYear = now.getFullYear();
        viewMonth = now.getMonth();

        const wrap = document.createElement('div');
        wrap.className = 'mg-dp-wrap';

        const input = document.createElement('div');
        input.className = 'mg-dp-input placeholder';
        input.textContent = placeholder;
        wrap.appendChild(input);

        const panel = document.createElement('div');
        panel.className = 'mg-dp-panel';
        panel.style.display = 'none';
        wrap.appendChild(panel);

        container.appendChild(wrap);

        function renderPanel() {
            const days = getMonthDays(viewYear, viewMonth);
            const today = new Date();
            const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

            let html = `<div class="mg-dp-header">
                <button data-dir="-1">&#8249;</button>
                <span class="mg-dp-title">${monthNames[viewMonth]} ${viewYear}</span>
                <button data-dir="1">&#8250;</button>
            </div>
            <div class="mg-dp-weekdays">${WEEKDAYS.map(w => `<span>${w}</span>`).join('')}</div>
            <div class="mg-dp-days">`;

            for (const d of days) {
                let cls = 'mg-dp-day';
                if (d.other) cls += ' other';
                if (!d.other && isSameDay(d.date, today)) cls += ' today';
                if (startDate && isSameDay(d.date, startDate)) cls += ' range-start selected';
                if (endDate && isSameDay(d.date, endDate)) cls += ' range-end selected';
                if (startDate && endDate && !d.other && d.date > startDate && d.date < endDate) cls += ' in-range';
                html += `<button class="${cls}" data-date="${dateStr(d.date)}" ${d.other ? '' : ''}>${d.date.getDate()}</button>`;
            }
            html += '</div>';

            if (type === 'datetime') {
                html += `<div class="mg-dp-time">
                    <label>Start</label>
                    <input type="number" min="0" max="23" value="${pad(startHour)}" data-field="startHour">
                    <span>:</span>
                    <input type="number" min="0" max="59" value="${pad(startMin)}" data-field="startMin">
                    <label style="margin-left:8px">End</label>
                    <input type="number" min="0" max="23" value="${pad(endHour)}" data-field="endHour">
                    <span>:</span>
                    <input type="number" min="0" max="59" value="${pad(endMin)}" data-field="endMin">
                </div>`;
            }

            html += `<div class="mg-dp-footer">
                <button class="mg-dp-clear" data-action="clear">Clear</button>
                <button class="mg-dp-ok" data-action="confirm">OK</button>
            </div>`;

            panel.innerHTML = html;

            panel.querySelector('[data-dir="-1"]').onclick = () => {
                viewMonth--;
                if (viewMonth < 0) { viewMonth = 11; viewYear--; }
                renderPanel();
            };
            panel.querySelector('[data-dir="1"]').onclick = () => {
                viewMonth++;
                if (viewMonth > 11) { viewMonth = 0; viewYear++; }
                renderPanel();
            };

            panel.querySelectorAll('.mg-dp-day:not(.other)').forEach(btn => {
                btn.onclick = () => {
                    const ds = btn.dataset.date;
                    const parts = ds.split('-').map(Number);
                    const clicked = new Date(parts[0], parts[1] - 1, parts[2]);
                    if (!picking || (startDate && endDate)) {
                        startDate = clicked;
                        endDate = null;
                        picking = true;
                    } else if (!endDate) {
                        if (clicked < startDate) {
                            endDate = startDate;
                            startDate = clicked;
                        } else {
                            endDate = clicked;
                        }
                        picking = false;
                    }
                    renderPanel();
                };
            });

            if (type === 'datetime') {
                panel.querySelectorAll('.mg-dp-time input').forEach(inp => {
                    inp.onchange = () => {
                        const v = parseInt(inp.value) || 0;
                        const field = inp.dataset.field;
                        if (field === 'startHour') startHour = Math.min(23, Math.max(0, v));
                        if (field === 'startMin') startMin = Math.min(59, Math.max(0, v));
                        if (field === 'endHour') endHour = Math.min(23, Math.max(0, v));
                        if (field === 'endMin') endMin = Math.min(59, Math.max(0, v));
                    };
                    inp.onclick = (e) => e.stopPropagation();
                });
            }

            panel.querySelector('[data-action="clear"]').onclick = () => {
                startDate = null;
                endDate = null;
                picking = false;
                input.textContent = placeholder;
                input.classList.add('placeholder');
                onChange(null, null);
            };

            panel.querySelector('[data-action="confirm"]').onclick = () => {
                closePanel();
                updateInput();
                fireChange();
            };
        }

        function updateInput() {
            if (!startDate) {
                input.textContent = placeholder;
                input.classList.add('placeholder');
                return;
            }
            input.classList.remove('placeholder');
            if (type === 'datetime') {
                const s = new Date(startDate);
                s.setHours(startHour, startMin);
                if (endDate) {
                    const e = new Date(endDate);
                    e.setHours(endHour, endMin);
                    input.textContent = `${datetimeStr(s)} ~ ${datetimeStr(e)}`;
                } else {
                    input.textContent = `${datetimeStr(s)} ~ ...`;
                }
            } else {
                if (endDate) {
                    input.textContent = `${dateStr(startDate)} ~ ${dateStr(endDate)}`;
                } else {
                    input.textContent = `${dateStr(startDate)} ~ ...`;
                }
            }
        }

        function fireChange() {
            if (!startDate) { onChange(null, null); return; }
            let s, e;
            if (type === 'datetime') {
                s = new Date(startDate);
                s.setHours(startHour, startMin, 0, 0);
                if (endDate) {
                    e = new Date(endDate);
                    e.setHours(endHour, endMin, 59, 999);
                } else {
                    e = new Date(s);
                    e.setHours(23, 59, 59, 999);
                }
            } else {
                s = new Date(startDate);
                s.setHours(0, 0, 0, 0);
                if (endDate) {
                    e = new Date(endDate);
                    e.setHours(23, 59, 59, 999);
                } else {
                    e = new Date(s);
                    e.setHours(23, 59, 59, 999);
                }
            }
            onChange(s, e);
        }

        function openPanel() {
            panelVisible = true;
            panel.style.display = '';
            input.classList.add('active');
            renderPanel();
        }

        function closePanel() {
            panelVisible = false;
            panel.style.display = 'none';
            input.classList.remove('active');
        }

        input.onclick = (e) => {
            e.stopPropagation();
            if (panelVisible) closePanel();
            else openPanel();
        };

        document.addEventListener('click', (e) => {
            if (!wrap.contains(e.target)) closePanel();
        });

        return {
            getStartDate: () => startDate,
            getEndDate: () => endDate,
            getStartISO: () => {
                if (!startDate) return null;
                const s = new Date(startDate);
                if (type === 'datetime') s.setHours(startHour, startMin, 0, 0);
                else s.setHours(0, 0, 0, 0);
                return s.toISOString();
            },
            getEndISO: () => {
                if (!endDate && !startDate) return null;
                const ref = endDate || startDate;
                const e = new Date(ref);
                if (type === 'datetime') e.setHours(endHour, endMin, 59, 999);
                else e.setHours(23, 59, 59, 999);
                return e.toISOString();
            },
            setRange: (s, e) => {
                if (s) {
                    startDate = new Date(s);
                    startDate.setHours(0, 0, 0, 0);
                    viewYear = startDate.getFullYear();
                    viewMonth = startDate.getMonth();
                }
                if (e) {
                    endDate = new Date(e);
                    endDate.setHours(0, 0, 0, 0);
                }
                updateInput();
            },
            clear: () => {
                startDate = null;
                endDate = null;
                picking = false;
                input.textContent = placeholder;
                input.classList.add('placeholder');
            },
            open: openPanel,
            close: closePanel
        };
    }

    window.MgDateRangePicker = { create: createInstance };
})();
