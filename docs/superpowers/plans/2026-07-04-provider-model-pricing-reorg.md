# 供应商模型/价目重组与用户端价格查询 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在模型目录看到价格，管理员在清晰的 tab 结构下管理绑定与价目。

**Architecture:** 后端在 `/user/api/catalog` 聚合 `provider_models` 价格返回 min 代表价（不暴露供应商）；管理端把「模型路由」+「模型计费」重组为「供应商模型」+「价目总览」两个 tab，后者支持筛选/对比/批改/复制/同步/导出。

**Tech Stack:** Python (FastAPI + SQLAlchemy async) + Jinja2 HTML + vanilla JS + unittest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-04-provider-model-pricing-reorg-design.md`

**Test runner:** `python -m unittest tests.<module> -v`（本仓库 tests 用 unittest.TestCase；CI 才有 pytest，本地用 unittest）

---

## File Structure

**新增文件:**
- `tests/test_user_catalog_pricing.py` — catalog 价格聚合单元测试
- `tests/test_provider_model_pricing_admin.py` — 管理端价目 API 测试

**修改文件:**
- `app/routes/user.py` — `serialize_provider_models` 加价格聚合 (~line 1448)
- `app/routes/provider_models.py` — 新增 batch/copy/sync/export 端点 (~line 130 后插入)
- `web/templates/user/dashboard.html` — 卡片价格徽章 + 查价弹窗 (~line 687, 700-763)
- `web/templates/admin/config.html` — tab 重组 + 价目总览页 (~line 145-152, 275-308)
- `web/locales/zh/LC_MESSAGES/messages.po` — 中文翻译键
- `web/locales/en/LC_MESSAGES/messages.po` — 英文翻译键

---

## Chunk 1: 后端 catalog 价格聚合（最低风险，独立可测）

### Task 1.1: 抽取价格聚合纯函数（TDD）

**Files:**
- Create: `tests/test_user_catalog_pricing.py`
- Modify: `app/routes/user.py` (新增模块级函数 `aggregate_model_pricing`)

**理由:** 把聚合逻辑从 `serialize_provider_models` 的闭包里抽出来，便于单元测试，无需 Request/DB fixture。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_user_catalog_pricing.py`：

```python
import unittest

from app.routes.user import aggregate_model_pricing


class AggregateModelPricingTests(unittest.TestCase):
    def test_returns_none_when_no_prices(self):
        result = aggregate_model_pricing([])
        self.assertIsNone(result["min_input_price"])
        self.assertIsNone(result["min_output_price"])
        self.assertIsNone(result["min_cached_price"])
        self.assertEqual(result["tier_samples"], [])

    def test_takes_min_across_multiple_provider_models(self):
        pms = [
            {"input": 8.0, "output": 28.0, "cached": 2.0, "tiers": []},
            {"input": 5.0, "output": 30.0, "cached": None, "tiers": []},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(result["min_input_price"], 5.0)
        self.assertEqual(result["min_output_price"], 28.0)
        self.assertEqual(result["min_cached_price"], 2.0)

    def test_cached_falls_back_to_input_price_when_null(self):
        pms = [
            {"input": 10.0, "output": 20.0, "cached": None, "tiers": []},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(result["min_cached_price"], 10.0)

    def test_ignores_none_input_prices(self):
        pms = [
            {"input": None, "output": 20.0, "cached": None, "tiers": []},
            {"input": 8.0, "output": None, "cached": None, "tiers": []},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(result["min_input_price"], 8.0)
        self.assertEqual(result["min_output_price"], 20.0)

    def test_merges_and_sorts_tier_samples_by_min_context(self):
        pms = [
            {"input": 4.2, "output": 16.8, "cached": 0.84, "tiers": [
                {"min_context_tokens": 128001, "max_context_tokens": None,
                 "input_price_cny_per_million": 4.2, "output_price_cny_per_million": 16.8},
            ]},
            {"input": 2.1, "output": 8.4, "cached": 0.42, "tiers": [
                {"min_context_tokens": 0, "max_context_tokens": 128000,
                 "input_price_cny_per_million": 2.1, "output_price_cny_per_million": 8.4},
            ]},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(len(result["tier_samples"]), 2)
        self.assertEqual(result["tier_samples"][0]["min_context_tokens"], 0)
        self.assertEqual(result["tier_samples"][1]["min_context_tokens"], 128001)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_user_catalog_pricing -v`
Expected: FAIL — `ImportError: cannot import name 'aggregate_model_pricing'`

- [ ] **Step 3: 实现纯函数**

在 `app/routes/user.py` 顶部 import 区下方（`build_system_health_summary` 之前，约 line 200 附近）新增模块级函数：

```python
def aggregate_model_pricing(provider_model_dicts):
    input_prices = []
    output_prices = []
    cached_prices = []
    tier_samples = []
    for pm in provider_model_dicts or []:
        ip = pm.get("input")
        op = pm.get("output")
        cp = pm.get("cached")
        if ip is not None:
            input_prices.append(ip)
        if op is not None:
            output_prices.append(op)
        cp_eff = cp if cp is not None else ip
        if cp_eff is not None:
            cached_prices.append(cp_eff)
        for tier in pm.get("tiers") or []:
            if not isinstance(tier, dict):
                continue
            tier_samples.append({
                "min_context_tokens": tier.get("min_context_tokens"),
                "max_context_tokens": tier.get("max_context_tokens"),
                "input_price": tier.get("input_price_cny_per_million"),
                "output_price": tier.get("output_price_cny_per_million"),
            })
    tier_samples.sort(key=lambda t: (t["min_context_tokens"] is None, t["min_context_tokens"] or 0))
    return {
        "min_input_price": min(input_prices) if input_prices else None,
        "min_output_price": min(output_prices) if output_prices else None,
        "min_cached_price": min(cached_prices) if cached_prices else None,
        "tier_samples": tier_samples,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_user_catalog_pricing -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_user_catalog_pricing.py app/routes/user.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat: add aggregate_model_pricing helper for catalog price aggregation"
```

---

### Task 1.2: 在 serialize_provider_models 接入聚合

**Files:**
- Modify: `app/routes/user.py` (~line 1448, `serialize_provider_models` 内层循环)

- [ ] **Step 1: 改造 serialize_provider_models 收集价格并调用聚合**

在 `serialize_provider_models` 内层循环（约 line 1450-1474），把每个 `provider_model` 的价格字段收集到 `models_by_id[model.id]["_pm_prices"]` 列表，循环结束后调用 `aggregate_model_pricing`。

定位 `models_by_id[model.id] = {...}` 块（约 line 1461-1474），改造为：

```python
            existing = models_by_id.get(model.id)
            provider_names = set(existing.get("providers", [])) if existing else set()
            provider_names.add(provider_map[provider_model.provider_id].name)
            pm_prices = existing.get("_pm_prices", []) if existing else []
            pm_prices.append({
                "input": provider_model.input_price_cny_per_million,
                "output": provider_model.output_price_cny_per_million,
                "cached": provider_model.cached_input_price_cny_per_million,
                "tiers": provider_model.pricing_tiers or [],
            })
            models_by_id[model.id] = {
                "id": model.id,
                "name": model_name,
                "model_name": model_name,
                "display_name": display_name,
                "context": model.context_length or 0,
                "output": model.max_tokens or 0,
                "is_multimodal": bool(model.is_multimodal),
                "has_override": bool(
                    getattr(provider_model, "upstream_model_name", None)
                    or provider_model.model_name_override
                ),
                "providers": sorted(provider_names),
                "_pm_prices": pm_prices,
            }
```

然后在 `models_data = sorted(...)`（约 line 1479）之前，遍历 `models_by_id` 调用聚合并删除临时字段：

```python
        for model_entry in models_by_id.values():
            pricing = aggregate_model_pricing(model_entry.pop("_pm_prices", []))
            model_entry["min_input_price"] = pricing["min_input_price"]
            model_entry["min_output_price"] = pricing["min_output_price"]
            model_entry["min_cached_price"] = pricing["min_cached_price"]
            model_entry["tier_samples"] = pricing["tier_samples"]
```

虚拟模型（`serialize_virtual_models` 产出的，约 line 1476-1477 合并进 `models_by_id`）天然没有 `_pm_prices`，聚合返回全 None，符合预期。

- [ ] **Step 2: 手动验证 API 返回结构**

Run（本机无 pytest，用 python 直接请求或看日志）：
```bash
python -c "
from app.routes.user import aggregate_model_pricing
r = aggregate_model_pricing([{'input':8.0,'output':28.0,'cached':2.0,'tiers':[]}])
print(r)
"
```
Expected: `{'min_input_price': 8.0, 'min_output_price': 28.0, 'min_cached_price': 2.0, 'tier_samples': []}`

- [ ] **Step 3: 运行已有 catalog 相关测试（如有）+ 新聚合测试**

Run: `python -m unittest tests.test_user_catalog_pricing -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/routes/user.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat: expose aggregated min prices in user catalog API"
```

---

## Chunk 2: 用户端价格徽章 + 查价弹窗

### Task 2.1: 卡片价格徽章

**Files:**
- Modify: `web/templates/user/dashboard.html` (~line 700-725 平台卡片, ~line 748-763 owned 卡片)
- Modify: `web/locales/zh/LC_MESSAGES/messages.po`, `web/locales/en/LC_MESSAGES/messages.po`

- [ ] **Step 1: 加 i18n 键**

在两个 `messages.po` 的 msgid 列表合适位置加：

zh:
```
msgid "Price from"
msgstr "¥%s 起 / 输入"

msgid "Price not configured"
msgstr "价格未配置"

msgid "View pricing"
msgstr "查价"
```

en:
```
msgid "Price from"
msgstr "from ¥%s / input"

msgid "Price not configured"
msgstr "Pricing N/A"

msgid "View pricing"
msgstr "Pricing"
```

编译: `pybabel compile -d web/locales`

- [ ] **Step 2: 卡片加价格徽章 + 查价按钮**

在 `renderPlatformGroups` 的 `modelsHtml`（~line 700-725），现有 badges div（~line 717-722）后追加：

```javascript
                        const priceBadge = model.min_input_price != null
                            ? `<span class="rounded-full bg-amber-50 px-2 py-1 text-amber-700">¥${model.min_input_price} 起 / 输入</span>`
                            : `<span class="rounded-full bg-black/5 px-2 py-1 text-gray-400">价格未配置</span>`;
                        const priceBtn = model.min_input_price != null
                            ? `<button onclick="showPriceDetail('${model.model_name}')" class="rounded-full bg-blue-50 px-2 py-1 text-blue-700 hover:bg-blue-100">查价</button>`
                            : '';
```

把 `priceBadge` 加入现有 `<div class="mt-3 flex flex-wrap gap-1.5 text-[11px]">` 内末尾，`priceBtn` 放卡片底部独立行。

对 `renderOwnedGroups`（~line 748-763）做同样改动（emerald 配色）。

- [ ] **Step 3: 静态测试校验文案存在**

在 `tests/test_admin_ui_static.py` 末尾加测试方法（或新建 `tests/test_user_ui_static.py`）：

```python
    def test_user_catalog_renders_price_badge(self):
        html = (ROOT / "web" / "templates" / "user" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("min_input_price", html)
        self.assertIn("价格未配置", html)
        self.assertIn("showPriceDetail", html)
```

Run: `python -m unittest tests.test_admin_ui_static -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/templates/user/dashboard.html web/locales/ tests/
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat(user): show min price badge and pricing button on model cards"
```

---

### Task 2.2: 查价弹窗

**Files:**
- Modify: `web/templates/user/dashboard.html` (新增 `showPriceDetail` 函数 + modal 容器)

- [ ] **Step 1: 加 modal 容器**

在 `dashboard.html` 末尾 body 区加：

```html
<div id="price-detail-modal" class="fixed inset-0 bg-black/40 hidden items-center justify-center z-50">
  <div class="bg-white rounded-2xl shadow-xl max-w-md w-full mx-4 p-6">
    <div class="flex justify-between items-start mb-4">
      <div>
        <div id="price-detail-name" class="text-lg font-semibold"></div>
        <div id="price-detail-model-name" class="text-xs text-gray-500"></div>
      </div>
      <button onclick="closePriceDetail()" class="text-gray-400 hover:text-gray-600">✕</button>
    </div>
    <div id="price-detail-body" class="space-y-2 text-sm"></div>
  </div>
</div>
```

- [ ] **Step 2: 加 showPriceDetail / closePriceDetail 函数**

缓存 catalog 数据供弹窗查询：

```javascript
        let _catalogCache = { platform: [], owned: [] };
        // 在 renderCatalogSections 末尾缓存：
        _catalogCache = { platform: data.platform_providers || [], owned: data.owned_providers || [] };

        function findModelInCache(modelName) {
            for (const group of [..._catalogCache.platform, ..._catalogCache.owned]) {
                const found = (group.models || []).find(m => m.model_name === modelName);
                if (found) return found;
            }
            return null;
        }

        function showPriceDetail(modelName) {
            const model = findModelInCache(modelName);
            if (!model) return;
            document.getElementById('price-detail-name').textContent = model.display_name || model.model_name;
            document.getElementById('price-detail-model-name').textContent = model.model_name;
            const body = document.getElementById('price-detail-body');
            const rows = [
                ['输入', model.min_input_price],
                ['输出', model.min_output_price],
                ['缓存', model.min_cached_price],
            ].filter(r => r[1] != null);
            let html = rows.map(r =>
                `<div class="flex justify-between"><span class="text-gray-500">${r[0]}</span><span>¥${r[1]} / 百万 tokens</span></div>`
            ).join('');
            if ((model.tier_samples || []).length) {
                html += `<div class="pt-2 mt-2 border-t"><div class="text-xs text-gray-400 mb-1">长上下文另有 ${model.tier_samples.length} 档定价</div>`;
                html += model.tier_samples.map(t => {
                    const lo = t.min_context_tokens != null ? formatCompactTokens(t.min_context_tokens) : '0';
                    const hi = t.max_context_tokens != null ? formatCompactTokens(t.max_context_tokens) : '∞';
                    return `<div class="flex justify-between text-xs text-gray-500"><span>${lo} - ${hi}</span><span>输入 ¥${t.input_price} / 输出 ¥${t.output_price}</span></div>`;
                }).join('');
                html += `</div>`;
            }
            body.innerHTML = html || '<div class="text-gray-400">价格未配置</div>';
            const modal = document.getElementById('price-detail-modal');
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }

        function closePriceDetail() {
            const modal = document.getElementById('price-detail-modal');
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        }
```

- [ ] **Step 3: 静态测试校验弹窗标识**

在 `tests/test_admin_ui_static.py` 加：

```python
    def test_user_price_detail_modal_exists(self):
        html = (ROOT / "web" / "templates" / "user" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('id="price-detail-modal"', html)
        self.assertIn('function showPriceDetail', html)
        self.assertIn('function closePriceDetail', html)
```

Run: `python -m unittest tests.test_admin_ui_static -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/templates/user/dashboard.html tests/test_admin_ui_static.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat(user): add pricing detail modal on model cards"
```

---

## Chunk 3: 管理端 tab 重组（纯 UI 迁移，无功能变更）

### Task 3.1: tab 按钮与面板 ID 改名

**Files:**
- Modify: `web/templates/admin/config.html` (~line 145-152 侧边栏, ~line 275-308 面板, ~line 665 switchConfigTab)

- [ ] **Step 1: 侧边栏按钮改名**

定位 `config.html:149-150`：
```html
                    <button class="config-tab-btn" data-config-tab="routing" onclick="switchConfigTab('routing')">模型路由</button>
                    <button class="config-tab-btn" data-config-tab="billing" onclick="switchConfigTab('billing')">模型计费</button>
```
替换为：
```html
                    <button class="config-tab-btn" data-config-tab="provider-models" onclick="switchConfigTab('provider-models')">供应商模型</button>
                    <button class="config-tab-btn" data-config-tab="pricing" onclick="switchConfigTab('pricing')">价目总览</button>
```

- [ ] **Step 2: 面板 ID 改名**

`config.html:275` `<div id="config-tab-routing"` → `<div id="config-tab-provider-models"`
`config.html:297` `<div id="config-tab-billing"` → `<div id="config-tab-pricing"`

panel 内容暂不动（Chunk 3 只改 ID，Chunk 4 再增强价目总览）。

- [ ] **Step 3: switchConfigTab 触发器改名**

定位 `config.html:676` `if (tab === 'billing') loadModelPricing();`
改为：
```javascript
            if (tab === 'provider-models') loadProviderModelRoutes();
            if (tab === 'pricing') loadModelPricing();
```

- [ ] **Step 4: 静态测试校验新 tab 标识**

在 `tests/test_admin_ui_static.py` 加：

```python
    def test_config_reorganized_tabs(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        self.assertIn('data-config-tab="provider-models"', html)
        self.assertIn('data-config-tab="pricing"', html)
        self.assertIn('id="config-tab-provider-models"', html)
        self.assertIn('id="config-tab-pricing"', html)
        self.assertNotIn('data-config-tab="routing"', html)
        self.assertNotIn('data-config-tab="billing"', html)
```

Run: `python -m unittest tests.test_admin_ui_static -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/templates/admin/config.html tests/test_admin_ui_static.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "refactor(admin): rename routing/billing tabs to provider-models/pricing"
```

---

### Task 3.2: 「供应商模型」tab 标题与说明文案更新

**Files:**
- Modify: `web/templates/admin/config.html` (~line 278-282 标题区)

- [ ] **Step 1: 改标题**

`config.html:280` `<h3 class="text-lg font-semibold">模型路由矩阵</h3>` → `供应商模型绑定`

`config.html:281` 说明 `<p>` 改为：
```
一行就是一个"标准模型 -> 供应商模型"绑定；上方添加绑定/同步，下方内联编辑价格。优先级越大越靠前。
```

- [ ] **Step 2: Commit**

```bash
git add web/templates/admin/config.html
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "ui(admin): update provider-models tab heading and description"
```

---

## Chunk 4: 管理端价目总览增强

### Task 4.1: 批量改价 API

**Files:**
- Create: `tests/test_provider_model_pricing_admin.py`
- Modify: `app/routes/provider_models.py` (~line 130 后)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_provider_model_pricing_admin.py`：

```python
import unittest


class BatchPricingTests(unittest.TestCase):
    def test_batch_pricing_route_exists(self):
        from app.routes import provider_models
        import inspect
        funcs = [name for name, _ in inspect.getmembers(provider_models, inspect.iscoroutinefunction)]
        self.assertIn("batch_update_provider_model_pricing", funcs)


if __name__ == "__main__":
    unittest.main()
```

Run: `python -m unittest tests.test_provider_model_pricing_admin -v`
Expected: FAIL — `batch_update_provider_model_pricing` not in funcs

- [ ] **Step 2: 实现批量端点**

在 `app/routes/provider_models.py` `update_provider_model_pricing`（~line 130）后加：

```python
class ProviderModelBatchPricingUpdate(BaseModel):
    ids: list[int]
    input_price_cny_per_million: Optional[float] = None
    output_price_cny_per_million: Optional[float] = None
    cached_input_price_cny_per_million: Optional[float] = None
    default_cache_hit_ratio: Optional[float] = None


@router.post("/provider-models/batch-pricing")
async def batch_update_provider_model_pricing(
    data: ProviderModelBatchPricingUpdate,
    _: bool = Depends(permission_required("provider_model.update")),
):
    if not data.ids:
        return JSONResponse({"error": "ids is empty"}, status_code=400)
    fields = {}
    for fname in (
        "input_price_cny_per_million",
        "output_price_cny_per_million",
        "cached_input_price_cny_per_million",
        "default_cache_hit_ratio",
    ):
        val = getattr(data, fname)
        if val is not None:
            fields[fname] = val
    if not fields:
        return JSONResponse({"error": "no fields to update"}, status_code=400)
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.id.in_(data.ids))
        )
        pms = result.scalars().all()
        found_ids = {pm.id for pm in pms}
        missing = set(data.ids) - found_ids
        if missing:
            return JSONResponse({"error": f"not found: {sorted(missing)}"}, status_code=404)
        for pm in pms:
            for fname, val in fields.items():
                setattr(pm, fname, val)
        await session.commit()
    return {"updated": sorted(found_ids)}
```

确保文件顶部已 import `BaseModel`, `Optional`, `async_session_maker`, `JSONResponse`（多数已存在）。

- [ ] **Step 3: 运行测试确认通过**

Run: `python -m unittest tests.test_provider_model_pricing_admin -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_provider_model_pricing_admin.py app/routes/provider_models.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat(admin): add batch pricing update endpoint"
```

---

### Task 4.2: 复制价格 / 同步到同模型 API

**Files:**
- Modify: `app/routes/provider_models.py`
- Modify: `tests/test_provider_model_pricing_admin.py`

- [ ] **Step 1: 扩展测试**

在 `tests/test_provider_model_pricing_admin.py` 加：

```python
    def test_copy_and_sync_routes_exist(self):
        from app.routes import provider_models
        import inspect
        funcs = [name for name, _ in inspect.getmembers(provider_models, inspect.iscoroutinefunction)]
        self.assertIn("copy_provider_model_pricing", funcs)
        self.assertIn("sync_pricing_to_siblings", funcs)
```

Run: 确认 FAIL。

- [ ] **Step 2: 实现两个端点**

在 `app/routes/provider_models.py` batch 端点后加：

```python
class CopyPricingPayload(BaseModel):
    target_pm_id: int


@router.post("/provider-models/{pm_id}/copy-pricing")
async def copy_provider_model_pricing(
    pm_id: int,
    data: CopyPricingPayload,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        src_result = await session.execute(select(ProviderModel).where(ProviderModel.id == pm_id))
        src = src_result.scalar_one_or_none()
        if not src:
            return JSONResponse({"error": "source not found"}, status_code=404)
        tgt_result = await session.execute(select(ProviderModel).where(ProviderModel.id == data.target_pm_id))
        tgt = tgt_result.scalar_one_or_none()
        if not tgt:
            return JSONResponse({"error": "target not found"}, status_code=404)
        for fname in (
            "input_price_cny_per_million",
            "output_price_cny_per_million",
            "cached_input_price_cny_per_million",
            "default_cache_hit_ratio",
            "pricing_tiers",
        ):
            setattr(tgt, fname, getattr(src, fname))
        await session.commit()
    return {"copied_from": pm_id, "copied_to": data.target_pm_id}


@router.post("/provider-models/{pm_id}/sync-to-siblings")
async def sync_pricing_to_siblings(
    pm_id: int,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        base_result = await session.execute(select(ProviderModel).where(ProviderModel.id == pm_id))
        base = base_result.scalar_one_or_none()
        if not base:
            return JSONResponse({"error": "base not found"}, status_code=404)
        siblings_result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.model_id == base.model_id,
                ProviderModel.id != pm_id,
            )
        )
        siblings = siblings_result.scalars().all()
        for sib in siblings:
            for fname in (
                "input_price_cny_per_million",
                "output_price_cny_per_million",
                "cached_input_price_cny_per_million",
                "default_cache_hit_ratio",
                "pricing_tiers",
            ):
                setattr(sib, fname, getattr(base, fname))
        await session.commit()
    return {"synced_to": [sib.id for sib in siblings]}
```

- [ ] **Step 3: 运行测试**

Run: `python -m unittest tests.test_provider_model_pricing_admin -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/routes/provider_models.py tests/test_provider_model_pricing_admin.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat(admin): add copy-pricing and sync-to-siblings endpoints"
```

---

### Task 4.3: CSV 导出 API

**Files:**
- Modify: `app/routes/provider_models.py`
- Modify: `tests/test_provider_model_pricing_admin.py`

- [ ] **Step 1: 测试**

```python
    def test_export_csv_route_exists(self):
        from app.routes import provider_models
        import inspect
        funcs = [name for name, _ in inspect.getmembers(provider_models, inspect.iscoroutinefunction)]
        self.assertIn("export_provider_model_pricing_csv", funcs)
```

- [ ] **Step 2: 实现导出**

```python
from fastapi.responses import Response
import csv
import io


@router.get("/provider-models/pricing-export.csv")
async def export_provider_model_pricing_csv(
    _: bool = Depends(permission_required("provider_model.view")),
):
    async with async_session_maker() as session:
        stmt = (
            select(ProviderModel, Provider, Model)
            .join(Provider, Provider.id == ProviderModel.provider_id)
            .join(Model, Model.id == ProviderModel.model_id)
            .order_by(Model.name, Provider.name)
        )
        result = await session.execute(stmt)
        rows = result.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "provider", "model", "upstream_model",
        "input_price_cny_per_million", "output_price_cny_per_million",
        "cached_input_price_cny_per_million", "default_cache_hit_ratio",
        "tiers_json",
    ])
    import json
    for pm, provider, model in rows:
        writer.writerow([
            provider.name, model.name,
            pm.upstream_model_name or pm.model_name_override or model.name,
            pm.input_price_cny_per_million,
            pm.output_price_cny_per_million,
            pm.cached_input_price_cny_per_million,
            pm.default_cache_hit_ratio,
            json.dumps(pm.pricing_tiers or [], ensure_ascii=False),
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=modelgate_pricing.csv"},
    )
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
python -m unittest tests.test_provider_model_pricing_admin -v
git add app/routes/provider_models.py tests/test_provider_model_pricing_admin.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat(admin): add pricing CSV export endpoint"
```

---

### Task 4.4: 价目总览前端（筛选/对比/批改/复制/同步/导出）

**Files:**
- Modify: `web/templates/admin/config.html` (`config-tab-pricing` 面板内容, ~line 297-308)

这是最大的前端任务。把现有 `model-pricing-list` 区升级为带筛选栏 + 操作栏的完整页面。

- [ ] **Step 1: 改造价目总览面板结构**

`config.html:297-308` `<div id="config-tab-pricing">` 内容替换为：

```html
            <div id="config-tab-pricing" class="config-tab-panel hidden">
                <div class="bg-white rounded-lg shadow">
                    <div class="p-4 border-b space-y-3">
                        <div class="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                            <div>
                                <h3 class="text-lg font-semibold">价目总览</h3>
                                <p class="text-xs text-gray-500 mt-1">按供应商模型绑定配置价格；支持筛选、对比、批量改价、复制与同步。</p>
                            </div>
                            <div class="flex flex-wrap gap-2">
                                <button onclick="exportPricingCsv()" class="px-4 py-2 border rounded text-sm hover:bg-gray-50">导出 CSV</button>
                                <button onclick="openBatchPricingModal()" class="px-4 py-2 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">批量改价</button>
                                <button onclick="loadModelPricing()" class="px-4 py-2 border rounded text-sm hover:bg-gray-50">刷新</button>
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-2 text-sm">
                            <select id="pricing-filter-provider" class="border rounded px-3 py-2" onchange="renderModelPricing()"></select>
                            <select id="pricing-filter-model" class="border rounded px-3 py-2 min-w-48" onchange="renderModelPricing()"></select>
                            <select id="pricing-filter-status" class="border rounded px-3 py-2" onchange="renderModelPricing()">
                                <option value="">全部</option>
                                <option value="priced">已配价</option>
                                <option value="unpriced">未配价</option>
                            </select>
                        </div>
                    </div>
                    <div id="model-pricing-list" class="p-4"></div>
                </div>
            </div>
```

- [ ] **Step 2: 实现 renderModelPricing 筛选 + 对比分组**

在 `config.html` JS 区改造 `renderModelPricing()`（~line 1834）：按 `model_name` 分组，同组多行相邻；应用三个 filter；行首加 checkbox。

```javascript
        function renderModelPricing() {
            const container = document.getElementById('model-pricing-list');
            if (!container) return;
            const providerFilter = document.getElementById('pricing-filter-provider')?.value || '';
            const modelFilter = document.getElementById('pricing-filter-model')?.value || '';
            const statusFilter = document.getElementById('pricing-filter-status')?.value || '';

            const providerOptions = [...new Set(allProviderModels.map(r => r.provider_name || ''))].sort();
            const modelOptions = [...new Set(allProviderModels.map(r => r.model_name || ''))].sort();
            const provSel = document.getElementById('pricing-filter-provider');
            const modSel = document.getElementById('pricing-filter-model');
            provSel.innerHTML = `<option value="">全部供应商</option>` + providerOptions.map(p => `<option value="${escapeAttr(p)}" ${p===providerFilter?'selected':''}>${escapeHtml(p)}</option>`).join('');
            modSel.innerHTML = `<option value="">全部模型</option>` + modelOptions.map(m => `<option value="${escapeAttr(m)}" ${m===modelFilter?'selected':''}>${escapeHtml(m)}</option>`).join('');

            let rows = [...allProviderModels];
            if (providerFilter) rows = rows.filter(r => r.provider_name === providerFilter);
            if (modelFilter) rows = rows.filter(r => r.model_name === modelFilter);
            if (statusFilter === 'priced') rows = rows.filter(r => r.input_price_cny_per_million != null || r.output_price_cny_per_million != null);
            if (statusFilter === 'unpriced') rows = rows.filter(r => r.input_price_cny_per_million == null && r.output_price_cny_per_million == null);
            rows.sort((a, b) => `${a.model_name||''}/${a.provider_name||''}`.localeCompare(`${b.model_name||''}/${b.provider_name||''}`));

            if (!rows.length) {
                container.innerHTML = '<div class="text-gray-400 text-center py-4">暂无数据</div>';
                return;
            }
            container.innerHTML = `<div class="config-table-wrap"><table class="config-table">
                <thead><tr>
                    <th class="w-8"><input type="checkbox" id="pricing-select-all" onchange="toggleAllPricing(this)"></th>
                    <th>标准模型</th><th>供应商</th><th>上游模型</th>
                    <th>输入价</th><th>输出价</th><th>缓存价</th><th>分档</th><th>操作</th>
                </tr></thead>
                <tbody>${rows.map(r => {
                    const priced = r.input_price_cny_per_million != null;
                    return `<tr>
                        <td><input type="checkbox" class="pricing-row-check" data-pm-id="${r.id}"></td>
                        <td>${escapeHtml(r.model_name||'')}</td>
                        <td>${escapeHtml(r.provider_name||'')}</td>
                        <td>${escapeHtml(r.upstream_model_name||r.model_name_override||r.model_name||'')}</td>
                        <td>${pricingValue(r.input_price_cny_per_million)}</td>
                        <td>${pricingValue(r.output_price_cny_per_million)}</td>
                        <td>${pricingValue(r.cached_input_price_cny_per_million)}</td>
                        <td>${(r.pricing_tiers||[]).length} 档</td>
                        <td class="space-x-1 whitespace-nowrap">
                            <button onclick="openCopyPricingModal(${r.id})" class="text-xs text-blue-600 hover:underline">复制</button>
                            <button onclick="syncPricingToSiblings(${r.id})" class="text-xs text-purple-600 hover:underline">同步</button>
                        </td>
                    </tr>`;
                }).join('')}</tbody></table></div>`;
        }
```

- [ ] **Step 3: 实现批量改价 / 复制 / 同步 / 导出 JS**

在 `config.html` JS 区加（用 fetchJsonOrRedirect / mgFetch 既有风格）：

```javascript
        function toggleAllPricing(el) {
            document.querySelectorAll('.pricing-row-check').forEach(c => c.checked = el.checked);
        }
        function selectedPricingIds() {
            return [...document.querySelectorAll('.pricing-row-check:checked')].map(c => parseInt(c.dataset.pmId, 10));
        }
        async function openBatchPricingModal() {
            const ids = selectedPricingIds();
            if (!ids.length) { alert('请先勾选要改价的行'); return; }
            const input = prompt('输入价（元/百万 tokens，留空跳过）:');
            if (input === null) return;
            const output = prompt('输出价（留空跳过）:');
            if (output === null) return;
            const cached = prompt('缓存价（留空跳过）:');
            if (cached === null) return;
            const body = { ids };
            if (input !== '') body.input_price_cny_per_million = parseFloat(input);
            if (output !== '') body.output_price_cny_per_million = parseFloat(output);
            if (cached !== '') body.cached_input_price_cny_per_million = parseFloat(cached);
            await mgFetch(`${APP_BASE_PATH}/admin/api/provider-models/batch-pricing`, {
                method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
            });
            await loadModelPricing();
        }
        async function openCopyPricingModal(pmId) {
            const sameModel = allProviderModels.filter(r => r.model_name === allProviderModels.find(x=>x.id===pmId)?.model_name && r.id !== pmId);
            if (!sameModel.length) { alert('同模型下没有其他供应商可复制'); return; }
            const opts = sameModel.map(r => `${r.id}:${r.provider_name}`).join('\n');
            const targetId = prompt(`选择目标（同模型其他供应商）:\n${opts}\n输入目标 id:`);
            if (!targetId) return;
            await mgFetch(`${APP_BASE_PATH}/admin/api/provider-models/${pmId}/copy-pricing`, {
                method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({target_pm_id: parseInt(targetId,10)})
            });
            await loadModelPricing();
        }
        async function syncPricingToSiblings(pmId) {
            if (!confirm('将该模型下其他供应商的价格同步为当前行的值？不可逆。')) return;
            await mgFetch(`${APP_BASE_PATH}/admin/api/provider-models/${pmId}/sync-to-siblings`, {method:'POST'});
            await loadModelPricing();
        }
        function exportPricingCsv() {
            window.location.href = `${APP_BASE_PATH}/admin/api/provider-models/pricing-export.csv`;
        }
```

注：批量改价/复制用 prompt 是 MVP；后续可升级为 modal 表单。

- [ ] **Step 4: 静态测试校验新元素**

在 `tests/test_admin_ui_static.py` 加：

```python
    def test_pricing_overview_has_filters_and_actions(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        self.assertIn('id="pricing-filter-provider"', html)
        self.assertIn('id="pricing-filter-model"', html)
        self.assertIn('openBatchPricingModal', html)
        self.assertIn('openCopyPricingModal', html)
        self.assertIn('syncPricingToSiblings', html)
        self.assertIn('exportPricingCsv', html)
```

Run: `python -m unittest tests.test_admin_ui_static -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/templates/admin/config.html tests/test_admin_ui_static.py
git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "feat(admin): pricing overview with filters, batch, copy, sync, export"
```

---

## 完成验证

- [ ] **全量测试**: `python -m unittest discover tests -v`
- [ ] **构建镜像**: `docker build -t 10.100.2.148:5002/modelgate:latest .`
- [ ] **推送**: `docker push 10.100.2.148:5002/modelgate:latest`

---

## Notes for executor

- 本地无 pytest/ruff（CI 才有），测试用 `python -m unittest`
- commit 时 git identity 未持久化，用 `git -c user.name='zmh' -c user.email='hzzmh@163.com' commit -m "..."`
- `escapeHtml` / `escapeAttr` / `mgFetch` / `fetchJsonOrRedirect` / `formatCompactTokens` 均为 `config.html` / `dashboard.html` 已有的全局函数，直接复用
- 所有新 API 复用现有 `provider_model.update` / `provider_model.view` 权限，无需改 RBAC 初始化数据
