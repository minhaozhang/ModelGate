import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import QN
from sqlalchemy import select, func, and_, literal_column

from core.config import providers_cache, proxy_logger as logger, api_keys_cache
from core.database import (
    async_session_maker,
    RequestLogRead as RequestLog,
    ApiKey,
    AnalysisRecord,
)
from services.analysis_store import (
    start_analysis_task,
    upsert_analysis_record,
    get_analysis_record,
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_SUCCESS,
    ANALYSIS_STATUS_FAILED,
)
from services.proxy import call_internal_model_via_proxy

ANALYSIS_TYPE_USAGE_REPORT = "usage_report"
REPORT_ROOT = Path("reports") / "usage"

_TOKEN_EXPR = func.coalesce(
    RequestLog.tokens["total_tokens"].as_integer(),
    RequestLog.tokens["estimated"].as_integer(),
    literal_column("0"),
)


async def query_usage_stats(
    start_date: str,
    end_date: str,
    exclude_api_key_ids: list[int] | None = None,
) -> dict:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    )

    async with async_session_maker() as session:
        base_filter = and_(
            RequestLog.created_at >= start_dt,
            RequestLog.created_at <= end_dt,
        )
        if exclude_api_key_ids:
            base_filter = and_(
                base_filter, RequestLog.api_key_id.notin_(exclude_api_key_ids)
            )

        keys_data: dict[int, dict] = {}

        agg_result = await session.execute(
            select(
                RequestLog.api_key_id,
                func.count().label("total_requests"),
                func.sum(_TOKEN_EXPR).label("total_tokens"),
                func.avg(RequestLog.latency_ms).label("avg_latency"),
            )
            .where(base_filter)
            .where(RequestLog.api_key_id.isnot(None))
            .group_by(RequestLog.api_key_id)
        )
        for row in agg_result:
            keys_data[row.api_key_id] = {
                "api_key_id": row.api_key_id,
                "total_requests": row.total_requests or 0,
                "total_tokens": int(row.total_tokens or 0),
                "avg_latency": round(row.avg_latency, 2) if row.avg_latency else 0,
                "status_distribution": {},
                "model_distribution": [],
                "hourly_distribution": {},
                "daily_distribution": {},
            }

        status_result = await session.execute(
            select(
                RequestLog.api_key_id,
                RequestLog.status,
                func.count().label("count"),
            )
            .where(base_filter)
            .where(RequestLog.api_key_id.isnot(None))
            .group_by(RequestLog.api_key_id, RequestLog.status)
        )
        for row in status_result:
            if row.api_key_id in keys_data:
                keys_data[row.api_key_id]["status_distribution"][row.status] = row.count

        model_result = await session.execute(
            select(
                RequestLog.api_key_id,
                RequestLog.model,
                func.count().label("count"),
                func.sum(_TOKEN_EXPR).label("tokens"),
            )
            .where(base_filter)
            .where(RequestLog.api_key_id.isnot(None))
            .group_by(RequestLog.api_key_id, RequestLog.model)
        )
        raw_model_data: dict[int, list] = defaultdict(list)
        for row in model_result:
            raw_model_data[row.api_key_id].append(
                {
                    "model": row.model,
                    "count": row.count or 0,
                    "tokens": int(row.tokens or 0),
                }
            )
        for key_id, models in raw_model_data.items():
            if key_id in keys_data:
                sorted_models = sorted(models, key=lambda m: m["count"], reverse=True)
                keys_data[key_id]["model_distribution"] = sorted_models[:10]

        hourly_result = await session.execute(
            select(
                RequestLog.api_key_id,
                func.extract("hour", RequestLog.created_at).label("hour"),
                func.count().label("count"),
            )
            .where(base_filter)
            .where(RequestLog.api_key_id.isnot(None))
            .group_by(
                RequestLog.api_key_id, func.extract("hour", RequestLog.created_at)
            )
        )
        for row in hourly_result:
            if row.api_key_id in keys_data:
                keys_data[row.api_key_id]["hourly_distribution"][str(int(row.hour))] = (
                    row.count
                )

        daily_result = await session.execute(
            select(
                RequestLog.api_key_id,
                func.date(RequestLog.created_at).label("day"),
                func.count().label("count"),
            )
            .where(base_filter)
            .where(RequestLog.api_key_id.isnot(None))
            .group_by(RequestLog.api_key_id, func.date(RequestLog.created_at))
        )
        for row in daily_result:
            if row.api_key_id in keys_data:
                day_str = str(row.day)
                keys_data[row.api_key_id]["daily_distribution"][day_str] = row.count

    api_key_names: dict[int, str] = {}
    for key_data in api_keys_cache.values():
        if isinstance(key_data, dict) and "id" in key_data:
            api_key_names[key_data["id"]] = key_data.get(
                "name", f"Key-{key_data['id']}"
            )

    missing_ids = [kid for kid in keys_data if kid not in api_key_names]
    if missing_ids:
        async with async_session_maker() as session:
            db_result = await session.execute(
                select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(missing_ids))
            )
            for row in db_result:
                api_key_names[row.id] = row.name

    for key_id, data in keys_data.items():
        data["api_key_name"] = api_key_names.get(key_id, f"Key-{key_id}")

    sorted_keys = sorted(
        keys_data.values(), key=lambda k: k["total_requests"], reverse=True
    )

    return {
        "keys": sorted_keys,
        "start_date": start_date,
        "end_date": end_date,
    }


def _choose_analysis_model() -> tuple[str | None, str | None]:
    preferred_models = ("glm-5-turbo", "glm-5", "glm-4.6", "glm-4.7")
    preferred_providers = ("zhipu", "deepseek", "minimax", "ollama")

    for provider_name in preferred_providers:
        provider = providers_cache.get(provider_name)
        if not provider:
            continue
        for model_info in provider.get("models", []):
            actual_name = model_info.get("actual_model_name", "")
            if actual_name in preferred_models:
                return provider_name, actual_name

    for provider_name, provider in providers_cache.items():
        for model_info in provider.get("models", []):
            actual_name = model_info.get("actual_model_name", "")
            if actual_name:
                return provider_name, actual_name

    return None, None


def _build_analysis_prompt(stats_data: dict) -> str:
    keys_summary = []
    for key_info in stats_data.get("keys", []):
        hourly = key_info.get("hourly_distribution", {})
        night_requests = sum(hourly.get(str(h), 0) for h in range(0, 6))
        morning_requests = sum(hourly.get(str(h), 0) for h in range(6, 9))
        daily = key_info.get("daily_distribution", {})
        daily_values = list(daily.values())

        keys_summary.append(
            {
                "name": key_info.get("api_key_name", "Unknown"),
                "total_requests": key_info.get("total_requests", 0),
                "total_tokens": key_info.get("total_tokens", 0),
                "avg_latency": key_info.get("avg_latency", 0),
                "model_count": len(key_info.get("model_distribution", [])),
                "status_distribution": key_info.get("status_distribution", {}),
                "hourly_distribution": hourly,
                "night_requests": night_requests,
                "morning_requests": morning_requests,
                "daily_distribution": daily,
                "daily_variance": (
                    _variance(daily_values) if len(daily_values) > 1 else 0
                ),
            }
        )

    return f"""你是一个有趣的AI分析师。请根据以下API Key使用数据，给出趣味分析和颁奖。
请用中文回复，包含以下奖项（每个奖项给一个API Key并说明理由）：

🏆 最勤奋奖 - 请求数最多的API Key
🦉 夜猫子奖 - 0-6点请求占比最高的API Key
🐦 早起鸟奖 - 6-9点请求占比最高的API Key
🔥 输出狂人奖 - Token用量最多的API Key
🎯 模型尝鲜者 - 使用模型种类最多的API Key
📊 稳定输出奖 - 日请求量方差最小的API Key（排除请求数<5的）
⚡ 效率之王 - 平均延迟最低的API Key（排除请求数<5的）

每个奖项格式：
## 🏆 奖项名
**获得者**: API Key名称
**理由**: 有趣的分析理由（1-2句话）

最后给出一段总结，用轻松幽默的语气概括整体使用情况。

API Key数据（JSON格式）：
{json.dumps(keys_summary, ensure_ascii=False, indent=2)}

日期范围: {stats_data.get("start_date")} 至 {stats_data.get("end_date")}
"""


def _variance(values: list) -> float:
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    return sum((v - avg) ** 2 for v in values) / len(values)


async def _call_llm_analysis(stats_data: dict) -> tuple[str | None, str | None]:
    provider_name, model_name = _choose_analysis_model()
    if not provider_name or not model_name:
        logger.warning("[USAGE_REPORT] No available model for AI analysis")
        return None, None

    prompt = _build_analysis_prompt(stats_data)
    body_json = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "你是一个有趣的数据分析师，善于从数据中发现有趣的模式。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 2048,
    }

    try:
        result = await call_internal_model_via_proxy(
            requested_model=f"{provider_name}/{model_name}",
            body_json=body_json,
            purpose="usage-report",
            timeout_seconds=120.0,
        )

        payload = result.get("payload")
        if not payload:
            logger.warning(f"[USAGE_REPORT] No payload from LLM: {result.get('error')}")
            return None, None

        message = ((payload.get("choices") or [{}])[0]).get("message") or {}
        content = message.get("content") or ""
        if not content:
            content = message.get("reasoning_content") or ""
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )

        return content or None, f"{provider_name}/{model_name}"
    except Exception as e:
        logger.warning(f"[USAGE_REPORT] AI analysis failed: {e}")
        return None, None


def _generate_docx(stats_data: dict, ai_analysis: str | None, output_path: str) -> str:
    doc = Document()

    style = doc.styles["Normal"]
    font = style.font
    font.name = "宋体"
    font.size = Pt(11)
    style.element.rPr.rFonts.set(QN("w:eastAsia"), "宋体")

    title = doc.add_heading("", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("ModelGate API Key 使用报告")
    run.font.size = Pt(22)
    run.font.color.rgb = None
    run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x6E)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = subtitle.add_run(
        f"统计周期: {stats_data['start_date']} 至 {stats_data['end_date']}    生成时间: {now_str}"
    )
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_heading("一、概览", level=1)
    keys = stats_data.get("keys", [])
    if keys:
        table = doc.add_table(rows=1, cols=6)
        table.style = "Light Grid Accent 1"
        headers = [
            "API Key",
            "请求数",
            "Token用量",
            "成功率",
            "平均延迟(ms)",
            "最常用模型",
        ]
        for i, h in enumerate(headers):
            cell = table.rows[0].cells[i]
            cell.text = h

        for key_info in keys:
            row_cells = table.add_row().cells
            row_cells[0].text = key_info.get("api_key_name", "Unknown")
            row_cells[1].text = str(key_info.get("total_requests", 0))
            row_cells[2].text = str(key_info.get("total_tokens", 0))
            status_dist = key_info.get("status_distribution", {})
            total = sum(status_dist.values())
            success = status_dist.get("success", 0)
            rate = f"{(success / total * 100):.1f}%" if total > 0 else "N/A"
            row_cells[3].text = rate
            row_cells[4].text = str(key_info.get("avg_latency", 0))
            models = key_info.get("model_distribution", [])
            row_cells[5].text = models[0]["model"] if models else "N/A"
    else:
        doc.add_paragraph("暂无使用数据。")

    doc.add_heading("二、各API Key详细统计", level=1)
    for key_info in keys:
        doc.add_heading(key_info.get("api_key_name", "Unknown"), level=2)

        models = key_info.get("model_distribution", [])
        if models:
            doc.add_paragraph("模型分布：")
            mt = doc.add_table(rows=1, cols=3)
            mt.style = "Light Grid Accent 1"
            for i, h in enumerate(["模型", "请求数", "Token用量"]):
                mt.rows[0].cells[i].text = h
            for m in models:
                row_cells = mt.add_row().cells
                row_cells[0].text = m.get("model", "")
                row_cells[1].text = str(m.get("count", 0))
                row_cells[2].text = str(m.get("tokens", 0))

        hourly = key_info.get("hourly_distribution", {})
        if hourly:
            sorted_hours = sorted(hourly.items(), key=lambda x: int(x[0]))
            hour_str = ", ".join(f"{h}时: {c}" for h, c in sorted_hours)
            doc.add_paragraph(f"小时分布: {hour_str}")

        daily = key_info.get("daily_distribution", {})
        if daily:
            sorted_days = sorted(daily.items(), key=lambda x: x[0])
            day_str = ", ".join(f"{d}: {c}" for d, c in sorted_days)
            doc.add_paragraph(f"日期分布: {day_str}")

    doc.add_heading("三、AI趣味分析", level=1)
    if ai_analysis:
        for line in ai_analysis.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("# "):
                doc.add_heading(line[2:], level=2)
            elif line.startswith("## "):
                doc.add_heading(line[3:], level=3)
            else:
                doc.add_paragraph(line)
    else:
        doc.add_paragraph("AI分析未能生成。")

    doc.add_heading("四、附录", level=1)
    doc.add_paragraph(f"生成时间: {now_str}")
    doc.add_paragraph(
        f"统计周期: {stats_data['start_date']} 至 {stats_data['end_date']}"
    )
    doc.add_paragraph(f"API Key数量: {len(keys)}")
    total_requests = sum(k.get("total_requests", 0) for k in keys)
    total_tokens = sum(k.get("total_tokens", 0) for k in keys)
    doc.add_paragraph(f"总请求数: {total_requests}")
    doc.add_paragraph(f"总Token用量: {total_tokens}")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return str(path).replace("\\", "/")


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

        ai_analysis, model_used = await _call_llm_analysis(stats_data)
        if not ai_analysis:
            logger.warning(
                "[USAGE_REPORT] AI analysis failed or skipped, continuing without it"
            )

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{start_date}_{end_date}_{timestamp}.docx"
        output_path = str(REPORT_ROOT / filename)

        file_path = _generate_docx(stats_data, ai_analysis, output_path)

        await upsert_analysis_record(
            ANALYSIS_TYPE_USAGE_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_SUCCESS,
            content=file_path,
            model_used=model_used,
        )
    except Exception as e:
        logger.error(f"[USAGE_REPORT] Failed to generate report: {e}")
        await upsert_analysis_record(
            ANALYSIS_TYPE_USAGE_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_FAILED,
            error=str(e),
        )
        raise


async def start_usage_report(
    start_date: str,
    end_date: str,
    exclude_api_key_ids: list[int] | None = None,
) -> bool:
    scope_key = f"{start_date}:{end_date}"

    return start_analysis_task(
        ANALYSIS_TYPE_USAGE_REPORT,
        scope_key,
        lambda: generate_usage_report(start_date, end_date, exclude_api_key_ids),
    )


async def get_usage_report_status(start_date: str, end_date: str) -> dict | None:
    scope_key = f"{start_date}:{end_date}"
    record = await get_analysis_record(ANALYSIS_TYPE_USAGE_REPORT, scope_key)
    if not record:
        return None

    result = {
        "status": record.status,
        "analysis_type": record.analysis_type,
        "scope_key": record.scope_key,
        "model_used": record.model_used,
        "error": record.error,
        "created_at": str(record.created_at) if record.created_at else None,
        "updated_at": str(record.updated_at) if record.updated_at else None,
    }

    if record.status == ANALYSIS_STATUS_SUCCESS and record.content:
        result["download_url"] = f"/reports/usage/{Path(record.content).name}"

    return result


async def list_usage_reports(limit: int = 10) -> list[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord)
            .where(AnalysisRecord.analysis_type == ANALYSIS_TYPE_USAGE_REPORT)
            .order_by(AnalysisRecord.created_at.desc())
            .limit(limit)
        )
        records = result.scalars().all()

    reports = []
    for record in records:
        entry = {
            "id": record.id,
            "scope_key": record.scope_key,
            "status": record.status,
            "model_used": record.model_used,
            "error": record.error,
            "created_at": str(record.created_at) if record.created_at else None,
            "updated_at": str(record.updated_at) if record.updated_at else None,
        }
        if record.status == ANALYSIS_STATUS_SUCCESS and record.content:
            entry["download_url"] = f"/reports/usage/{Path(record.content).name}"
        reports.append(entry)

    return reports
