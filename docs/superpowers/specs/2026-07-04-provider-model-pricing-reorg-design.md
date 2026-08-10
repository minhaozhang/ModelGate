# 供应商模型/价目重组与用户端价格查询

## 需求

### 用户故事

**作为管理员**，配置页的「模型路由」tab 名不副实 —— 它实际管的是"标准模型↔供应商模型绑定"，跟「Auto 路由」「路由预览」撞名。而「模型计费」tab 又跟它操作的是同一张 `provider_models` 表，两个 tab 来回切才能完成"加绑定 + 配价格"这件连续的事。我希望绑定和价格管理更连贯，同时价格运营（批改、对比、同步）有专门的页面。

**作为用户**，我在「模型目录」页看不到价格，只能等到调用完从账单 CSV 里反推。我希望在模型卡片上一眼看到"贵不贵"，点一下能看到完整档位（输入/输出/缓存）。

### 功能需求

| # | 需求 | 优先级 |
|---|------|--------|
| R1 | 管理端删除「模型路由」+「模型计费」两个 tab，重组为「供应商模型」+「价目总览」两个职责清晰的 tab | P0 |
| R2 | 「供应商模型」tab：上区绑定矩阵（CRUD/优先级/同步），下区每条绑定的基础价格内联快编 | P0 |
| R3 | 「价目总览」tab：筛选（供应商/模型/是否配价）+ 多供应商同模型价格并排对比 | P0 |
| R4 | 「价目总览」批量改价：勾选多条统一设置输入/输出/缓存价 | P1 |
| R5 | 「价目总览」运营动作：复制价格到另一供应商；按标准模型同步价格到该模型下所有绑定 | P1 |
| R6 | 「价目总览」导出 CSV（含 tiers） | P1 |
| R7 | 用户端 `/user/api/catalog` 返回每个聚合模型的代表价（min input/output/cached price） | P0 |
| R8 | 用户端模型卡片显示「¥X 起 / 输入」徽章；无配价显示「价格未配置」 | P0 |
| R9 | 用户端卡片新增「查价」按钮，弹窗展示完整档位（输入/输出/缓存 + tiers 提示），不暴露供应商 | P0 |
| R10 | 用户端全程不返回/显示供应商名（保持现有隐藏设计） | P0 |

### 非目标

- 不改 `provider_models` 表结构（价格字段已齐全：`input_price_cny_per_million` 等）
- 不改计费计算逻辑（`pricing.py` 的 `enrich_tokens_with_billing` 保持不变）
- 不动「Auto 路由」「路由预览」「标准模型」tab
- 不暴露供应商名给普通用户
- 不做用户端价格历史/趋势（本次只做当前价快照）

---

## 背景

### 现状问题

1. **tab 命名混乱**：`config.html:149` 的「模型路由」tab 实际内容是绑定矩阵（`config.html:280-281`「一行就是一个标准模型→供应商模型绑定」），与「Auto 路由」「路由预览」语义重叠，新管理员难以定位。
2. **同源数据双 tab**：「模型路由」管绑定、「模型计费」管价格，都操作 `provider_models` 表，完成"加绑定+配价"要切两次 tab。
3. **价格运营缺位**：现有「模型计费」只能逐条编辑，无法批量改、无法对比同模型多供应商、无法复制价格、无法导出。
4. **用户价格不透明**：`/user/api/catalog`（`user.py:1448-1474`）刻意隐藏供应商且不返回价格字段；前端 `dashboard.html:708-724` 卡片只显示 context/output/多模态/别名，用户无从判断调用成本。
5. **隐藏设计需保持**：虽然 catalog API 返回了 `providers` 数组（`user.py:1460`），但前端刻意不渲染 —— 本次价格查询必须延续此原则。

### 数据源

价格数据全部在 `provider_models` 表（`database.py:215-219`）：

| 字段 | 说明 |
|------|------|
| `input_price_cny_per_million` | 输入价（元/百万 tokens） |
| `output_price_cny_per_million` | 输出价 |
| `cached_input_price_cny_per_million` | 缓存输入价 |
| `default_cache_hit_ratio` | 默认缓存命中比（%) |
| `pricing_tiers` | 长上下文分档（JSONB，含 min/max_context_tokens + 各档价格） |

现有 API：`GET /admin/api/provider-models`（`provider_models.py:339`）、`PUT /admin/api/provider-models/{pm_id}/pricing`（`provider_models.py:108`）。

---

## 一、管理端 tab 重组

### 1.1 新 tab 结构

删除：
- `config-tab-routing`（原「模型路由」）
- `config-tab-billing`（原「模型计费」）

新增：
- `config-tab-provider-models`（「供应商模型」）— 管绑定关系
- `config-tab-pricing`（「价目总览」）— 管价格运营

侧边栏按钮顺序（`config.html:145-152`）调整为：

```
概览 / 供应商 / 标准模型 / 供应商模型 / 价目总览 / Auto 路由 / 路由预览 / 策略模板
```

### 1.2 「供应商模型」tab

**上区：绑定矩阵**

迁移现有 `config-tab-routing` 的全部功能（`config.html:275-295`）：
- 标题：「标准模型↔供应商模型绑定」
- 操作栏：选 provider + 选 model + 添加绑定 + 从 API 同步（保留现有 `syncRoutingProvider()`）
- 矩阵表：每行一个绑定，列含标准模型名、供应商名、上游模型名、优先级、操作（编辑/解绑）

**下区：基础价格内联快编**

迁移现有 `renderModelPricing()`（`config.html:1834`）的精简版：
- 矩阵每行额外展示输入/输出/缓存三个内联可编辑输入框（复用现有 `modelPricingNumber()` 提交逻辑）
- 失焦或点「保存」调用现有 `PUT /provider-models/{pm_id}/pricing`
- `pricing_tiers` 此处只显示「N 档」徽章，编辑跳「价目总览」tab

### 1.3 「价目总览」tab（增强版）

**筛选栏**
- 按供应商下拉（含「全部」）
- 按标准模型下拉（含「全部」）
- 按状态：「全部 / 已配价 / 未配价」

**主表**
- 列：标准模型 / 供应商 / 上游模型 / 输入价 / 输出价 / 缓存价 / 缓存命中比 / 分档数 / 最后操作
- 同标准模型的多行强制相邻并排，便于横向对比价差
- 行内可勾选（复选框）

**批量改价**（R4）
- 勾选多行 → 点「批量改价」→ 弹窗输入 input/output/cached → 提交
- 后端新增 `POST /admin/api/provider-models/batch-pricing`，body：`{ids: [...], fields: {input_price_cny_per_million: ..., ...}}`，循环调用现有单条更新逻辑，单事务提交

**运营动作**（R5）

a) **复制价格到另一供应商**：
   - 选源 provider_model（行内「复制」按钮）→ 弹窗选目标 provider_model（同标准模型下）→ 确认
   - 后端新增 `POST /admin/api/provider-models/{pm_id}/copy-pricing`，body：`{target_pm_id: int}`，把源的全套价格字段（含 tiers）覆盖到目标

b) **按标准模型同步价格**（「价目总览」行操作）：
   - 选某标准模型下任一 provider_model 作为基准 → 点「同步到同模型」→ 把该模型下所有 provider_model 的价格拉平成基准值
   - 后端新增 `POST /admin/api/provider-models/{pm_id}/sync-to-siblings`
   - 二次确认弹窗（不可逆操作）

**导出 CSV**（R6）
- 按钮「导出 CSV」，复用 `_billing_rows_to_csv`（`user.py:240`）的 CSV 构造风格
- 列：provider, model, upstream_model, input_price, output_price, cached_price, cache_hit_ratio, tiers_json
- 后端新增 `GET /admin/api/provider-models/pricing-export.csv`

---

## 二、用户端价格查询

### 2.1 后端：catalog API 扩展

**改动文件**：`app/routes/user.py`，函数 `serialize_provider_models`（`user.py:1448`）

**改动**：在按 `model.id` 聚合时，收集该模型下所有 `provider_model` 的价格字段，计算代表价：

```python
def serialize_provider_models(items, virtual_model_ids=None):
    models_by_id = {}
    for provider_model in items:
        model = model_map[provider_model.model_id]
        ...  # 现有逻辑
        existing = models_by_id.get(model.id)
        
        # 收集价格（新增）
        ip = provider_model.input_price_cny_per_million
        op = provider_model.output_price_cny_per_million
        cp = provider_model.cached_input_price_cny_per_million
        if ip is not None or op is not None or cp is not None:
            existing_prices = existing.get("_prices") if existing else None
            prices = existing_prices or {"input": [], "output": [], "cached": []}
            if ip is not None: prices["input"].append(ip)
            if op is not None: prices["output"].append(op)
            # 缓存价未配时回退用 input 价（与 pricing.py:95 一致）
            cp_eff = cp if cp is not None else ip
            if cp_eff is not None: prices["cached"].append(cp_eff)
        
        models_by_id[model.id] = {
            ...  # 现有字段
            "min_input_price": min(prices["input"]) if prices["input"] else None,
            "min_output_price": min(prices["output"]) if prices["output"] else None,
            "min_cached_price": min(prices["cached"]) if prices["cached"] else None,
            "_prices": prices,  # 临时字段，序列化前移除
        }
```

**代表价取值规则**（写入 spec 供实现参考）：
- `min_input_price` = min(所有 provider_model 的 `input_price_cny_per_million`，忽略 null)
- `min_output_price` = min(所有 `output_price_cny_per_million`，忽略 null)
- `min_cached_price` = min(缓存价；缓存价为 null 时回退用该条 input 价)
- 三档各自独立取 min，可能来自不同供应商 —— 可接受，因为不暴露供应商
- `pricing_tiers` **不纳入代表价计算**（避免长上下文档把"起价"拉高），仅在查价弹窗里展示

**输出前清理**：序列化完成后删除 `_prices` 临时字段。

**权限**：沿用 `get_user_catalog` 现有的 `api_key_id` session 校验 + `owned_provider_models` 过滤，价格只在用户有权访问的 provider_model 范围内计算（避免泄露无权模型的价格）。

**无新接口**：复用 `/user/api/catalog`，前端零额外 RTT。

### 2.2 前端：模型卡片价格徽章

**改动文件**：`web/templates/user/dashboard.html`，函数 `renderCatalogSections`（`dashboard.html:687`）

**改动 `modelsHtml` 渲染**（`dashboard.html:700-725` 和 `748-763`）：在现有 badges 行下方加价格徽章：

```javascript
const priceBadge = model.min_input_price != null
    ? `<span class="rounded-full bg-amber-50 px-2 py-1 text-amber-700">¥${model.min_input_price} 起 / 输入</span>`
    : `<span class="rounded-full bg-black/5 px-2 py-1 text-gray-400">价格未配置</span>`;
```

放在现有 ctx/output/multimodal 徽章同一行（`dashboard.html:717-722`）。

### 2.3 前端：「查价」弹窗

**改动文件**：`web/templates/user/dashboard.html`

**新增**：卡片右下角加「查价」按钮，点击渲染弹窗（复用现有 modal 风格，参考 `request_logs.html` 的 detail overlay）：

弹窗内容（不显示供应商，纯价格档位）：
```
模型：{display_name}
─────────────────
输入    ¥{min_input_price} / 百万 tokens
输出    ¥{min_output_price} / 百万 tokens
缓存    ¥{min_cached_price} / 百万 tokens

[长上下文另有 N 档定价 ▼]   ← 仅当任一 provider_model 有 pricing_tiers 时显示
  展开：列出每档 min/max context 区间 + 价格
```

**tiers 展示数据来源**：catalog API 额外返回每个模型的 `tier_samples`（去重后的档位列表，去掉供应商标识），字段结构：
```python
"tier_samples": [
    {"min_context_tokens": 0, "max_context_tokens": 128000, "input_price": 2.1, "output_price": 8.4},
    {"min_context_tokens": 128001, "max_context_tokens": None, "input_price": 4.2, "output_price": 16.8},
]
```
取所有 provider_model 的 tiers 并集，按 min_context_tokens 排序去重。

---

## 三、API 变更汇总

### 管理端新增

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/admin/api/provider-models/batch-pricing` | 批量改价 | `provider_model.update` |
| POST | `/admin/api/provider-models/{pm_id}/copy-pricing` | 复制价格到目标 | `provider_model.update` |
| POST | `/admin/api/provider-models/{pm_id}/sync-to-siblings` | 按标准模型同步价 | `provider_model.update` |
| GET | `/admin/api/provider-models/pricing-export.csv` | 导出 CSV | `provider_model.view` |

所有写操作沿用现有 `provider_model.update`/`provider_model.view` 权限（已在 RBAC 中），无需新增权限项。

### 用户端

| 方法 | 路径 | 变更 |
|------|------|------|
| GET | `/user/api/catalog` | 响应新增 `min_input_price` / `min_output_price` / `min_cached_price` / `tier_samples` 字段（每条 model） |

不新增用户端接口。

---

## 四、UI/前端变更汇总

### 管理端 `config.html`

1. 侧边栏 tab 按钮（`config.html:145-152`）：删 routing/billing 两个按钮，加 provider-models/pricing 两个
2. tab 面板：删 `config-tab-routing` / `config-tab-billing`，加 `config-tab-provider-models` / `config-tab-pricing`
3. `switchConfigTab`（`config.html:665`）：更新 tab 加载触发（原 `if (tab === 'billing') loadModelPricing();` 改为新 tab 的 loader）
4. 新增 JS：`loadPricingOverview()` / `renderPricingTable()` / `batchUpdatePricing()` / `copyPricing()` / `syncPricingToSiblings()` / `exportPricingCsv()`

### 用户端 `dashboard.html`

1. `renderCatalogSections`（`dashboard.html:700-763`）：两处 modelsHtml 渲染加价格徽章 + 查价按钮
2. 新增 `showPriceDetail(modelId)` 函数 + modal 容器

### i18n

`web/locales/{zh,en}/LC_MESSAGES/messages.po` 新增翻译键：
- 「供应商模型」「价目总览」「批量改价」「复制价格」「同步到同模型」「导出 CSV」
- 「¥X 起 / 输入」「价格未配置」「查价」「长上下文另有 N 档定价」

---

## 五、测试策略

### 后端单元测试

1. **`tests/test_user_catalog_pricing.py`（新增）**
   - `serialize_provider_models` 多供应商聚合 min 计算
   - null 价格忽略
   - 缓存价 null 时回退 input 价
   - 无任何配价时返回 None
   - 权限过滤：仅计算 owned_provider_models 范围内的价格
   - tier_samples 去重排序

2. **`tests/test_provider_model_pricing.py`（扩展，沿用 `test_model_pricing.py` 风格）**
   - `batch-pricing` 端点：单事务、部分失败回滚
   - `copy-pricing`：字段完整复制（含 tiers）
   - `sync-to-siblings`：仅同 model_id 下生效、二次确认语义
   - `pricing-export.csv`：CSV 格式正确、含 tiers_json 列

### 前端静态测试

**`tests/test_admin_ui_static.py`（扩展，沿用现有 `test_admin_ui_static.py:392-404` 风格）**
- 校验 `config.html` 含新 tab 标识 `config-tab-provider-models` / `config-tab-pricing`
- 校验删掉了 `config-tab-routing` / `config-tab-billing`
- 校验新 API 路由字符串存在

### 回归

- 现有 `test_model_name_routing.py` / `test_provider_key_routing.py` 不受影响（路由逻辑不动）
- 现有 `test_model_pricing.py`（计费计算）不受影响（`pricing.py` 不动）

---

## 六、实现顺序建议

1. **后端先行**：用户端 catalog API 加价格字段（最低风险、独立可测）
2. **用户端 UI**：卡片徽章 + 查价弹窗（依赖步骤 1）
3. **管理端 tab 重组**：纯 UI 迁移，把 routing/billing 内容搬到新 tab（无功能变更）
4. **管理端价目增强**：筛选/对比/批量/复制/同步/导出（增量加，每功能可独立合并）

每步可独立 PR，互不阻塞。
