# Usage Report Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add async usage report generation that queries per-API-key usage stats, calls an LLM for fun Chinese analysis, and produces a downloadable Word (.docx) file.

**Architecture:** New `services/usage_report.py` handles data aggregation, AI analysis, and docx generation. New `routes/reports.py` exposes REST endpoints for creating/polling/downloading reports. New admin page `templates/admin/reports.html` provides the UI. The existing `AnalysisRecord` + `start_analysis_task()` from `services/analysis_store.py` manages the async task lifecycle.

**Tech Stack:** python-docx, SQLAlchemy async (RequestLogRead for cross-table queries), internal LLM proxy, Jinja2 templates with Babel i18n.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/usage_report.py` | Data aggregation, AI analysis prompt, docx generation |
| Create | `routes/reports.py` | REST endpoints: create task, poll status, download file |
| Create | `templates/admin/reports.html` | Admin report page with date picker, exclude modal, progress, history |
| Modify | `templates/components/nav.html` | Add "Usage Report" nav link |
| Modify | `routes/pages.py` | Add `/admin/reports` page route |
| Modify | `main.py` | Register `routes.reports` router |
| Modify | `requirements.txt` | Add `python-docx` |
| Modify | `locales/en/LC_MESSAGES/messages.po` | English translations |
| Modify | `locales/zh/LC_MESSAGES/messages.po` | Chinese translations |

---

### Task 1: Add python-docx dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add python-docx to requirements.txt**

Append `python-docx>=1.1.0` to `requirements.txt`.

- [ ] **Step 2: Install dependency**

Run: `pip install python-docx>=1.1.0`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add python-docx dependency for usage reports"
```

---

### Task 2: Create report data aggregation service

**Files:**
- Create: `services/usage_report.py`

- [ ] **Step 1: Create `services/usage_report.py` with data query function**

This file contains the core logic. Create it with the data aggregation function:

```python
import datetime
import json
import asyncio
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func, case, and_, extract

from core.config import providers_cache, proxy_logger as logger
from core.database import (
    async_session_maker,
    RequestLogRead as RequestLog,
    ApiKey,
)
from services.analysis_store import (
    start_analysis_task,
    upsert_analysis_record,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_SUCCESS,
    ANALYSIS_STATUS_FAILED,
)

ANALYSIS_TYPE_USAGE_REPORT = "usage_report"
REPORT_ROOT = Path("reports") / "usage"

_TOKEN_EXPR = func.coalesce(
    RequestLog.tokens["total_tokens"].as_integer(),
    RequestLog.tokens["estimated"].as_integer(),
    0,
)


async def _get_api_key_name_map(
    session, api_key_ids: list[int]
) -> dict[int, str]:
    from core.config import api_keys_cache

    names: dict[int, str] = {}
    for kid in api_key_ids:
        for cached_key, cached_info in api_keys_cache.items():
            if cached_info.get("id") == kid:
                names[kid] = cached_info.get("name", f"Key-{kid}")
                break
    missing = [kid for kid in api_key_ids if kid not in names]
    if missing:
        result = await session.execute(select(ApiKey).where(ApiKey.id.in_(missing)))
        names.update({k.id: k.name for k in result.scalars()})
    return names


async def query_usage_stats(
    start_date: str,
    end_date: str,
    exclude_api_key_ids: list[int] | None = None,
) -> dict:
    start_dt = datetime.datetime.fromisoformat(start_date + "T00:00:00")
    end_dt = datetime.datetime.fromisoformat(end_date + "T23:59:59")

    async with async_session_maker() as session:
        base_filter = and_(
            RequestLog.created_at >= start_dt,
            RequestLog.created_at <= end_dt,
        )
        if exclude_api_key_ids:
            base_filter = and_(base_filter, RequestLog.api_key_id.notin_(exclude_api_key_ids))

        key_result = await session.execute(
            select(RequestLog.api_key_id)
            .where(base_filter)
            .where(RequestLog.api_key_id.isnot(None))
            .distinct()
        )
        api_key_ids = [row[0] for row in key_result.fetchall()]
        if not api_key_ids:
            return {"keys": [], "start_date": start_date, "end_date": end_date}

        name_map = await _get_api_key_name_map(session, api_key_ids)

        keys_data = []
        for kid in api_key_ids:
            kid_filter = and_(base_filter, RequestLog.api_key_id == kid)

            totals = await session.execute(
                select(
                    func.count(RequestLog.id).label("total_requests"),
                    func.sum(_TOKEN_EXPR).label("total_tokens"),
                    func.avg(RequestLog.latency_ms).label("avg_latency"),
                ).where(kid_filter)
            )
            t = totals.one()

            status_counts = await session.execute(
                select(
                    RequestLog.status,
                    func.count(RequestLog.id).label("count"),
                )
                .where(kid_filter)
                .group_by(RequestLog.status)
            )
            status_map = {row.status: row.count for row in status_counts.fetchall()}

            model_dist = await session.execute(
                select(
                    RequestLog.model,
                    func.count(RequestLog.id).label("count"),
                    func.sum(_TOKEN_EXPR).label("tokens"),
                )
                .where(kid_filter)
                .group_by(RequestLog.model)
                .order_by(func.count(RequestLog.id).desc())
            )
            models = [
                {"model": row.model, "count": row.count, "tokens": row.tokens or 0}
                for row in model_dist.fetchall()
            ]

            hour_dist = await session.execute(
                select(
                    extract("hour", RequestLog.created_at).label("hour"),
                    func.count(RequestLog.id).label("count"),
                )
                .where(kid_filter)
                .group_by("hour")
                .order_by("hour")
            )
            hours = {int(row.hour): row.count for row in hour_dist.fetchall()}

            daily_dist = await session.execute(
                select(
                    func.date(RequestLog.created_at).label("day"),
                    func.count(RequestLog.id).label("count"),
                )
                .where(kid_filter)
                .group_by("day")
                .order_by("day")
            )
            daily = {str(row.day): row.count for row in daily_dist.fetchall()}

            keys_data.append({
                "id": kid,
                "name": name_map.get(kid, f"Key-{kid}"),
                "total_requests": t.total_requests or 0,
                "total_tokens": int(t.total_tokens or 0),
                "avg_latency": round(t.avg_latency or 0, 1),
                "status": status_map,
                "models": models,
                "hours": hours,
                "daily": daily,
            })

        keys_data.sort(key=lambda x: x["total_requests"], reverse=True)

        return {
            "keys": keys_data,
            "start_date": start_date,
            "end_date": end_date,
        }
```

- [ ] **Step 2: Commit**

```bash
git add services/usage_report.py
git commit -m "feat: add usage report data aggregation service"
```

---

### Task 3: Add AI analysis generation

**Files:**
- Modify: `services/usage_report.py`

- [ ] **Step 1: Add AI analysis function to `services/usage_report.py`**

Append after `query_usage_stats()`:

```python
def _choose_analysis_model() -> tuple[Optional[str], Optional[str]]:
    preferred_models = ("glm-5-turbo", "glm-5", "glm-4.6", "glm-4.7")
    preferred_providers = ("zhipu", "deepseek", "minimax", "ollama")
    for provider_name in preferred_providers:
        provider_config = providers_cache.get(provider_name)
        if not provider_config:
            continue
        models = provider_config.get("models") or []
        for preferred in preferred_models:
            for model in models:
                actual = model.get("actual_model_name") or model.get("model_name")
                if actual == preferred:
                    return provider_name, actual
        for model in models:
            actual = model.get("actual_model_name") or model.get("model_name")
            if actual:
                return provider_name, actual
    for provider_name, provider_config in providers_cache.items():
        for model in provider_config.get("models") or []:
            actual = model.get("actual_model_name") or model.get("model_name")
            if actual:
                return provider_name, actual
    return None, None


async def _call_llm_analysis(stats_data: dict) -> tuple[Optional[str], Optional[str]]:
    from services.proxy import call_internal_model_via_proxy

    provider_name, actual_model = _choose_analysis_model()
    if not provider_name or not actual_model:
        return None, "No analysis model available"

    keys = stats_data["keys"]
    if not keys:
        return "无数据可供分析。", None

    summary_lines = []
    for k in keys:
        hour_str = ", ".join(f"{h}时:{c}次" for h, c in sorted(k["hours"].items()))
        model_str = ", ".join(f"{m['model']}({m['count']}次)" for m in k["models"][:5])
        summary_lines.append(
            f"- {k['name']}: {k['total_requests']}次请求, "
            f"{k['total_tokens']} tokens, 平均延迟{k['avg_latency']}ms, "
            f"模型: {model_str}, 时段: {hour_str}"
        )

    prompt = (
        "你是一位风趣幽默的数据分析师。根据以下API Key使用数据，用中文写一份趣味分析报告。\n\n"
        "请评选以下奖项（每个奖项给出Key名称、具体数据支撑和一句话趣味评语）：\n"
        "1. 🏆 最勤奋奖 — 总请求数最多\n"
        "2. 🦉 夜猫子奖 — 凌晨0-6点请求占比最高\n"
        "3. 🐦 早起鸟奖 — 早6-9点请求占比最高\n"
        "4. 🔥 输出狂人奖 — 总Token消耗最多\n"
        "5. 🎯 模型尝鲜者 — 使用模型种类最多\n"
        "6. 📊 稳定输出奖 — 日均请求波动最小（排除总请求少于5次的Key）\n"
        "7. ⚡ 效率之王 — 平均延迟最低（排除总请求少于5次的Key）\n\n"
        "最后写一段总体趋势评语。\n\n"
        f"数据范围: {stats_data['start_date']} ~ {stats_data['end_date']}\n\n"
        "各Key使用数据:\n" + "\n".join(summary_lines)
    )

    body_json = {
        "model": f"{provider_name}/{actual_model}",
        "temperature": 0.3,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": "你是数据分析师，用中文写趣味分析报告。"},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        result = await call_internal_model_via_proxy(
            requested_model=f"{provider_name}/{actual_model}",
            body_json=body_json,
            purpose="usage-report",
            timeout_seconds=120.0,
        )
        if not result.get("ok"):
            return None, str(result.get("error") or f"HTTP {result.get('status_code')}")

        payload = result.get("payload")
        if not isinstance(payload, dict):
            return None, "invalid_payload"

        message = ((payload.get("choices") or [{}])[0]).get("message") or {}
        content = message.get("content") or ""
        if not content:
            content = message.get("reasoning_content") or ""
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        if not content:
            return None, "empty_response"
        return content.strip(), None
    except Exception as exc:
        return None, str(exc)
```

- [ ] **Step 2: Commit**

```bash
git add services/usage_report.py
git commit -m "feat: add AI analysis generation for usage reports"
```

---

### Task 4: Add docx generation

**Files:**
- Modify: `services/usage_report.py`

- [ ] **Step 1: Add docx generation function to `services/usage_report.py`**

Append after `_call_llm_analysis()`:

```python
def _generate_docx(stats_data: dict, ai_analysis: str, output_path: Path) -> str:
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
        "宋体",
    )

    title = doc.add_heading("ModelGate API Key 使用报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.size = Pt(22)
        run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7F)

    doc.add_paragraph(f"时间范围：{stats_data['start_date']} ~ {stats_data['end_date']}")
    doc.add_paragraph(f"生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph("")

    doc.add_heading("一、概览", level=1)
    keys = stats_data["keys"]

    table = doc.add_table(rows=1, cols=6)
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    hdr[0].text = "API Key"
    hdr[1].text = "请求数"
    hdr[2].text = "Token 用量"
    hdr[3].text = "成功率"
    hdr[4].text = "平均延迟"
    hdr[5].text = "最常用模型"

    for k in keys:
        row = table.add_row().cells
        row[0].text = k["name"]
        row[1].text = str(k["total_requests"])
        row[2].text = f"{k['total_tokens']:,}"
        success = k["status"].get("success", 0)
        total = k["total_requests"] or 1
        row[3].text = f"{success / total * 100:.1f}%"
        row[4].text = f"{k['avg_latency']}ms"
        row[5].text = k["models"][0]["model"] if k["models"] else "-"

    doc.add_paragraph("")

    doc.add_heading("二、各 API Key 详细统计", level=1)
    for k in keys:
        doc.add_heading(k["name"], level=2)
        p = doc.add_paragraph()
        p.add_run(f"总请求: {k['total_requests']} 次 | ").bold = False
        p.add_run(f"总 Token: {k['total_tokens']:,} | ").bold = False
        p.add_run(f"平均延迟: {k['avg_latency']}ms").bold = False

        if k["models"]:
            doc.add_paragraph("模型使用分布:", style="List Bullet")
            mt = doc.add_table(rows=1, cols=3)
            mt.style = "Light Grid Accent 1"
            mt.rows[0].cells[0].text = "模型"
            mt.rows[0].cells[1].text = "请求数"
            mt.rows[0].cells[2].text = "Token"
            for m in k["models"][:10]:
                r = mt.add_row().cells
                r[0].text = m["model"]
                r[1].text = str(m["count"])
                r[2].text = f"{m['tokens']:,}"

        if k["hours"]:
            doc.add_paragraph("时段分布:", style="List Bullet")
            active = sorted(k["hours"].items(), key=lambda x: x[1], reverse=True)[:8]
            hour_str = "、".join(f"{h}时({c}次)" for h, c in active)
            doc.add_paragraph(hour_str)

        if k["daily"]:
            doc.add_paragraph("每日请求:", style="List Bullet")
            days = sorted(k["daily"].items())
            if len(days) <= 14:
                daily_str = "、".join(f"{d}({c}次)" for d, c in days)
                doc.add_paragraph(daily_str)
            else:
                for d, c in days:
                    doc.add_paragraph(f"  {d}: {c} 次", style="List Bullet 2")

        doc.add_paragraph("")

    if ai_analysis:
        doc.add_heading("三、AI 趣味分析", level=1)
        for line in ai_analysis.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                doc.add_heading(line.lstrip("# "), level=2)
            else:
                doc.add_paragraph(line)

    doc.add_heading("四、附录", level=1)
    doc.add_paragraph(f"报告生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph(f"数据时间范围：{stats_data['start_date']} ~ {stats_data['end_date']}")
    doc.add_paragraph(f"包含 API Key 数量：{len(keys)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return str(output_path).replace("\\", "/")
```

- [ ] **Step 2: Commit**

```bash
git add services/usage_report.py
git commit -m "feat: add docx generation for usage reports"
```

---

### Task 5: Add async task orchestration

**Files:**
- Modify: `services/usage_report.py`

- [ ] **Step 1: Add the main orchestration function and public API to `services/usage_report.py`**

Append after `_generate_docx()`:

```python
async def generate_usage_report(
    start_date: str,
    end_date: str,
    exclude_api_key_ids: list[int] | None = None,
) -> None:
    scope_key = f"{start_date}:{end_date}"

    await upsert_analysis_record(
        ANALYSIS_TYPE_USAGE_REPORT,
        scope_key,
        status=ANALYSIS_STATUS_RUNNING,
    )

    try:
        stats_data = await query_usage_stats(start_date, end_date, exclude_api_key_ids)

        if not stats_data["keys"]:
            await upsert_analysis_record(
                ANALYSIS_TYPE_USAGE_REPORT,
                scope_key,
                status=ANALYSIS_STATUS_FAILED,
                error="所选时间范围内没有数据",
            )
            return

        ai_analysis, ai_error = await _call_llm_analysis(stats_data)
        if ai_error:
            logger.warning("Usage report AI analysis failed: %s", ai_error)

        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{start_date}_{end_date}_{ts}.docx"
        output_path = REPORT_ROOT / filename

        file_path = _generate_docx(stats_data, ai_analysis or "", output_path)

        await upsert_analysis_record(
            ANALYSIS_TYPE_USAGE_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_SUCCESS,
            content=file_path,
        )
    except Exception as exc:
        logger.exception("Usage report generation failed")
        await upsert_analysis_record(
            ANALYSIS_TYPE_USAGE_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_FAILED,
            error=str(exc),
        )


def start_usage_report(
    start_date: str,
    end_date: str,
    exclude_api_key_ids: list[int] | None = None,
) -> bool:
    scope_key = f"{start_date}:{end_date}"

    async def task_factory():
        await generate_usage_report(start_date, end_date, exclude_api_key_ids)

    return start_analysis_task(ANALYSIS_TYPE_USAGE_REPORT, scope_key, task_factory)


async def get_usage_report_status(
    start_date: str, end_date: str
) -> Optional[dict]:
    from services.analysis_store import get_analysis_record

    scope_key = f"{start_date}:{end_date}"
    record = await get_analysis_record(ANALYSIS_TYPE_USAGE_REPORT, scope_key)
    if not record:
        return None

    result = {
        "task_id": record.id,
        "status": record.status,
        "start_date": start_date,
        "end_date": end_date,
    }
    if record.status == ANALYSIS_STATUS_SUCCESS and record.content:
        result["download_url"] = f"/admin/api/reports/usage/{record.id}/download"
        result["file_path"] = record.content
    if record.status == ANALYSIS_STATUS_FAILED and record.error:
        result["error"] = record.error
    return result


async def list_usage_reports(limit: int = 10) -> list[dict]:
    from sqlalchemy import desc

    async with async_session_maker() as session:
        result = await session.execute(
            select("analysis_records")
            .where(
                AnalysisRecord.__table__.c.analysis_type == ANALYSIS_TYPE_USAGE_REPORT
            )
            .order_by(AnalysisRecord.__table__.c.created_at.desc())
            .limit(limit)
        )
        from core.database import AnalysisRecord as AR
        result = await session.execute(
            select(AR)
            .where(AR.analysis_type == ANALYSIS_TYPE_USAGE_REPORT)
            .order_by(AR.created_at.desc())
            .limit(limit)
        )
        records = result.scalars().all()
        reports = []
        for r in records:
            parts = r.scope_key.split(":")
            item = {
                "task_id": r.id,
                "status": r.status,
                "start_date": parts[0] if len(parts) >= 1 else "",
                "end_date": parts[1] if len(parts) >= 2 else "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            if r.status == ANALYSIS_STATUS_SUCCESS and r.content:
                item["download_url"] = f"/admin/api/reports/usage/{r.id}/download"
            if r.error:
                item["error"] = r.error
            reports.append(item)
        return reports
```

- [ ] **Step 2: Commit**

```bash
git add services/usage_report.py
git commit -m "feat: add async task orchestration for usage reports"
```

---

### Task 6: Create API routes

**Files:**
- Create: `routes/reports.py`

- [ ] **Step 1: Create `routes/reports.py`**

```python
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path

from core.config import validate_session
from services.usage_report import (
    start_usage_report,
    get_usage_report_status,
    list_usage_reports,
)

router = APIRouter(prefix="/admin/api", tags=["reports"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class UsageReportRequest(BaseModel):
    start_date: str
    end_date: str
    exclude_api_key_ids: list[int] = []


@router.post("/reports/usage")
async def create_usage_report(
    body: UsageReportRequest, _: bool = Depends(require_admin)
):
    started = start_usage_report(
        body.start_date,
        body.end_date,
        body.exclude_api_key_ids or None,
    )
    if not started:
        return JSONResponse(
            {"error": "该时间范围的报告正在生成中，请稍候"},
            status_code=409,
        )

    status = await get_usage_report_status(body.start_date, body.end_date)
    return {"task_id": status["task_id"] if status else None, "status": "pending"}


@router.get("/reports/usage/status")
async def get_usage_report_status_api(
    start_date: str,
    end_date: str,
    _: bool = Depends(require_admin),
):
    result = await get_usage_report_status(start_date, end_date)
    if not result:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return result


@router.get("/reports/usage/{task_id}/download")
async def download_usage_report(
    task_id: int, _: bool = Depends(require_admin)
):
    from core.database import async_session_maker, AnalysisRecord
    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord).where(
                AnalysisRecord.id == task_id,
                AnalysisRecord.analysis_type == "usage_report",
            )
        )
        record = result.scalar_one_or_none()

    if not record or record.status != "success" or not record.content:
        return JSONResponse({"error": "Report not found or not ready"}, status_code=404)

    file_path = Path(record.content)
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path
    if not file_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)

    filename = f"usage_report_{record.scope_key.replace(':', '_')}.docx"
    return FileResponse(
        str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.get("/reports/usage/history")
async def get_usage_report_history(
    limit: int = 10, _: bool = Depends(require_admin)
):
    reports = await list_usage_reports(limit)
    return {"reports": reports}
```

- [ ] **Step 2: Commit**

```bash
git add routes/reports.py
git commit -m "feat: add usage report API routes"
```

---

### Task 7: Register router and page route

**Files:**
- Modify: `main.py`
- Modify: `routes/pages.py`

- [ ] **Step 1: Add `reports` to router imports in `main.py`**

In `main.py`, find the deferred router import block (around line 149) and add `reports` to the import and include_router:

Add `reports,` to the import:
```python
from routes import (
    proxy,
    auth,
    providers,
    models,
    provider_models,
    keys,
    stats,
    logs,
    pages,
    user,
    opencode,
    reports,
)
```

Add after `app.include_router(opencode.router)`:
```python
app.include_router(reports.router)
```

- [ ] **Step 2: Add page route in `routes/pages.py`**

Append at the end of `routes/pages.py`:

```python


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/reports.html"))
```

Note: there needs to be a blank line before the function to separate from the previous function.

- [ ] **Step 3: Commit**

```bash
git add main.py routes/pages.py
git commit -m "feat: register usage report router and page route"
```

---

### Task 8: Add nav link for Usage Report

**Files:**
- Modify: `templates/components/nav.html`

- [ ] **Step 1: Add "Usage Report" nav link**

After the "Usage Guide" link (around line 29, before the closing `</div>` of the nav links section), add:

```html
        <a href="{{ app_base_path }}/admin/reports" class="nav-link {{ 'active' if active_page == 'reports' else '' }} flex items-center px-4 py-3 text-gray-700">
            <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
            {{ _('Usage Report') }}
        </a>
```

- [ ] **Step 2: Commit**

```bash
git add templates/components/nav.html
git commit -m "feat: add Usage Report nav link"
```

---

### Task 9: Create admin reports page

**Files:**
- Create: `templates/admin/reports.html`

- [ ] **Step 1: Create `templates/admin/reports.html`**

Create the full admin page with date picker, exclude-key modal, progress indicator, and report history list. Follow the existing admin page patterns (TailwindCSS CDN, dark theme support, `fetchJsonOrRedirect`, i18n `_()` function):

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    {% include 'components/site_head_meta.html' %}
    <title>{{ _('Usage Report') }} - ModelGate</title>
    <link rel="icon" href="{{ app_base_path }}/favicon.ico" sizes="any">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .nav-link { transition: all 0.2s; }
        .nav-link:hover { background: rgba(59, 130, 246, 0.1); }
        .nav-link.active { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-right: 3px solid #3b82f6; }
        body.theme-dark { background: #020617 !important; color: #e2e8f0; }
        body.theme-dark nav, body.theme-dark .bg-white { background: #0f172a !important; }
        body.theme-dark .bg-gray-50 { background: #111827 !important; }
        body.theme-dark .bg-gray-100 { background: #020617 !important; }
        body.theme-dark .border-gray-200 { border-color: #334155 !important; }
        .modal-overlay { background: rgba(0,0,0,0.5); }
        .spinner { border: 3px solid #e5e7eb; border-top-color: #3b82f6; border-radius: 50%; width: 24px; height: 24px; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    {% set active_page = 'reports' %}
    {% include 'components/nav.html' %}

    <div class="ml-56 p-8">
        <h1 class="text-2xl font-bold text-gray-800 mb-6">{{ _('Usage Report') }}</h1>

        <div class="bg-white rounded-lg shadow p-6 mb-6">
            <h2 class="text-lg font-semibold mb-4">{{ _('Generate Report') }}</h2>
            <div class="flex items-end gap-4 flex-wrap">
                <div>
                    <label class="block text-sm text-gray-600 mb-1">{{ _('Start Date') }}</label>
                    <input type="date" id="start-date" class="border rounded px-3 py-2 text-sm">
                </div>
                <div>
                    <label class="block text-sm text-gray-600 mb-1">{{ _('End Date') }}</label>
                    <input type="date" id="end-date" class="border rounded px-3 py-2 text-sm">
                </div>
                <button onclick="openExcludeModal()" class="bg-gray-500 text-white px-4 py-2 rounded text-sm hover:bg-gray-600">
                    {{ _('Exclude Keys') }} <span id="exclude-count" class="ml-1"></span>
                </button>
                <button onclick="generateReport()" id="btn-generate" class="bg-blue-600 text-white px-6 py-2 rounded text-sm hover:bg-blue-700">
                    {{ _('Generate') }}
                </button>
            </div>
            <div id="progress-area" class="mt-4 hidden">
                <div class="flex items-center gap-3">
                    <div class="spinner"></div>
                    <span id="progress-text" class="text-sm text-gray-600">{{ _('Generating report...') }}</span>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg shadow p-6">
            <h2 class="text-lg font-semibold mb-4">{{ _('Report History') }}</h2>
            <div id="report-history">
                <p class="text-gray-400 text-sm">{{ _('No reports yet') }}</p>
            </div>
        </div>
    </div>

    <div id="exclude-modal" class="fixed inset-0 modal-overlay z-50 hidden flex items-center justify-center">
        <div class="bg-white rounded-lg shadow-xl w-96 max-h-[70vh] flex flex-col">
            <div class="p-4 border-b font-semibold">{{ _('Select API Keys to Exclude') }}</div>
            <div id="key-list" class="p-4 overflow-y-auto flex-1 space-y-2"></div>
            <div class="p-4 border-t flex justify-end gap-2">
                <button onclick="closeExcludeModal()" class="px-4 py-2 text-sm border rounded hover:bg-gray-50">{{ _('Cancel') }}</button>
                <button onclick="confirmExclude()" class="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{{ _('Confirm') }}</button>
            </div>
        </div>
    </div>

    <script>
        const BASE = {{ app_base_path | tojson }};
        let excludeIds = [];
        let allKeys = [];
        let pollTimer = null;

        function applyTheme() {
            const t = localStorage.getItem('theme');
            if (t === 'dark') document.body.classList.add('theme-dark');
            else document.body.classList.remove('theme-dark');
        }
        applyTheme();

        function toggleTheme() {
            document.body.classList.toggle('theme-dark');
            localStorage.setItem('theme', document.body.classList.contains('theme-dark') ? 'dark' : 'light');
        }

        async function fetchJsonOrRedirect(url, opts) {
            const r = await fetch(url, opts);
            if (r.status === 401) { window.location.href = BASE + '/admin/login'; return null; }
            return r.json();
        }

        async function loadKeys() {
            const data = await fetchJsonOrRedirect(BASE + '/admin/api/keys');
            if (!data) return;
            allKeys = data.api_keys || [];
        }

        function openExcludeModal() {
            const list = document.getElementById('key-list');
            list.innerHTML = '';
            allKeys.forEach(k => {
                const checked = excludeIds.includes(k.id) ? 'checked' : '';
                list.innerHTML += `
                    <label class="flex items-center gap-2 text-sm">
                        <input type="checkbox" class="exclude-cb" data-id="${k.id}" ${checked}>
                        <span>${k.name}</span>
                        <span class="text-gray-400 text-xs ml-auto">ID: ${k.id}</span>
                    </label>`;
            });
            document.getElementById('exclude-modal').classList.remove('hidden');
        }

        function closeExcludeModal() {
            document.getElementById('exclude-modal').classList.add('hidden');
        }

        function confirmExclude() {
            excludeIds = [...document.querySelectorAll('.exclude-cb:checked')].map(cb => parseInt(cb.dataset.id));
            const cnt = document.getElementById('exclude-count');
            cnt.textContent = excludeIds.length > 0 ? `(${excludeIds.length})` : '';
            closeExcludeModal();
        }

        async function generateReport() {
            const startDate = document.getElementById('start-date').value;
            const endDate = document.getElementById('end-date').value;
            if (!startDate || !endDate) { alert('Please select start and end dates'); return; }

            document.getElementById('btn-generate').disabled = true;
            document.getElementById('progress-area').classList.remove('hidden');
            document.getElementById('progress-text').textContent = "{{ _('Generating report...') }}";

            const data = await fetchJsonOrRedirect(BASE + '/admin/api/reports/usage', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    start_date: startDate,
                    end_date: endDate,
                    exclude_api_key_ids: excludeIds,
                }),
            });
            if (!data || data.error) {
                alert(data?.error || 'Failed to start report generation');
                document.getElementById('btn-generate').disabled = false;
                document.getElementById('progress-area').classList.add('hidden');
                return;
            }
            startPolling(startDate, endDate);
        }

        function startPolling(startDate, endDate) {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(async () => {
                const data = await fetchJsonOrRedirect(
                    BASE + `/admin/api/reports/usage/status?start_date=${startDate}&end_date=${endDate}`
                );
                if (!data) return;
                if (data.status === 'running') {
                    document.getElementById('progress-text').textContent = "{{ _('Generating report...') }}";
                } else if (data.status === 'success') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    document.getElementById('progress-area').classList.add('hidden');
                    document.getElementById('btn-generate').disabled = false;
                    loadHistory();
                    if (data.download_url) {
                        window.location.href = BASE + data.download_url;
                    }
                } else if (data.status === 'failed') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    document.getElementById('progress-area').classList.add('hidden');
                    document.getElementById('btn-generate').disabled = false;
                    alert(data.error || 'Report generation failed');
                    loadHistory();
                }
            }, 3000);
        }

        async function loadHistory() {
            const data = await fetchJsonOrRedirect(BASE + '/admin/api/reports/usage/history?limit=10');
            if (!data || !data.reports || data.reports.length === 0) {
                document.getElementById('report-history').innerHTML = '<p class="text-gray-400 text-sm">{{ _('No reports yet') }}</p>';
                return;
            }
            let html = '<div class="space-y-3">';
            data.reports.forEach(r => {
                const statusBadge = r.status === 'success'
                    ? '<span class="text-green-600 text-xs">{{ _('Completed') }}</span>'
                    : r.status === 'running'
                    ? '<span class="text-blue-600 text-xs">{{ _('Running') }}</span>'
                    : r.status === 'failed'
                    ? '<span class="text-red-600 text-xs">{{ _('Failed') }}</span>'
                    : '<span class="text-yellow-600 text-xs">{{ _('Pending') }}</span>';
                const downloadBtn = r.download_url
                    ? `<a href="${BASE}${r.download_url}" class="text-blue-600 text-sm hover:underline">{{ _('Download') }}</a>`
                    : '';
                html += `
                    <div class="flex items-center justify-between p-3 bg-gray-50 rounded">
                        <div>
                            <span class="text-sm font-medium">${r.start_date} ~ ${r.end_date}</span>
                            <span class="text-xs text-gray-400 ml-2">${r.created_at || ''}</span>
                        </div>
                        <div class="flex items-center gap-3">
                            ${statusBadge}
                            ${downloadBtn}
                        </div>
                    </div>`;
            });
            html += '</div>';
            document.getElementById('report-history').innerHTML = html;
        }

        loadKeys();
        loadHistory();
    </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/admin/reports.html
git commit -m "feat: add admin usage report page with exclude modal"
```

---

### Task 10: Add i18n translations

**Files:**
- Modify: `locales/en/LC_MESSAGES/messages.po`
- Modify: `locales/zh/LC_MESSAGES/messages.po`

- [ ] **Step 1: Add English translations**

Add the following entries to `locales/en/LC_MESSAGES/messages.po` in the `msgid/msgstr` section (before the final empty section):

```
msgid "Usage Report"
msgstr "Usage Report"

msgid "Generate Report"
msgstr "Generate Report"

msgid "Start Date"
msgstr "Start Date"

msgid "End Date"
msgstr "End Date"

msgid "Exclude Keys"
msgstr "Exclude Keys"

msgid "Generate"
msgstr "Generate"

msgid "Generating report..."
msgstr "Generating report..."

msgid "Report History"
msgstr "Report History"

msgid "No reports yet"
msgstr "No reports yet"

msgid "Select API Keys to Exclude"
msgstr "Select API Keys to Exclude"

msgid "Confirm"
msgstr "Confirm"

msgid "Cancel"
msgstr "Cancel"

msgid "Download"
msgstr "Download"

msgid "Completed"
msgstr "Completed"

msgid "Running"
msgstr "Running"

msgid "Failed"
msgstr "Failed"

msgid "Pending"
msgstr "Pending"
```

- [ ] **Step 2: Add Chinese translations**

Add the same `msgid` entries to `locales/zh/LC_MESSAGES/messages.po` with Chinese translations:

```
msgid "Usage Report"
msgstr "使用报告"

msgid "Generate Report"
msgstr "生成报告"

msgid "Start Date"
msgstr "开始日期"

msgid "End Date"
msgstr "结束日期"

msgid "Exclude Keys"
msgstr "排除 Key"

msgid "Generate"
msgstr "生成"

msgid "Generating report..."
msgstr "正在生成报告..."

msgid "Report History"
msgstr "报告历史"

msgid "No reports yet"
msgstr "暂无报告"

msgid "Select API Keys to Exclude"
msgstr "选择要排除的 API Key"

msgid "Confirm"
msgstr "确认"

msgid "Cancel"
msgstr "取消"

msgid "Download"
msgstr "下载"

msgid "Completed"
msgstr "已完成"

msgid "Running"
msgstr "生成中"

msgid "Failed"
msgstr "失败"

msgid "Pending"
msgstr "等待中"
```

- [ ] **Step 3: Compile translations**

Run: `pybabel compile -d locales`

- [ ] **Step 4: Commit**

```bash
git add locales/
git commit -m "feat: add i18n translations for usage report feature"
```

---

### Task 11: Smoke test

- [ ] **Step 1: Start the server**

Run: `python main.py`

Expected: Server starts without import errors on `http://localhost:8765`

- [ ] **Step 2: Verify page loads**

Open `http://localhost:8765/admin/reports` (after logging in). Expected: Report page renders with date pickers, Generate button, and empty history.

- [ ] **Step 3: Verify API responds**

```bash
curl -b "session=<your_session_cookie>" http://localhost:8765/admin/api/reports/usage/history
```

Expected: `{"reports": []}`

- [ ] **Step 4: Verify nav link**

Navigate to any admin page. Expected: "Usage Report" link visible in sidebar.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete usage report export feature"
```
