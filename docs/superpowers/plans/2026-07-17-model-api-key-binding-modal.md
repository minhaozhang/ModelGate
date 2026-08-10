# 标准模型 → API Key 绑定弹框 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在标准模型表格每行加一个"Key 绑定"按钮，点击弹出卡片式 modal，可一次性勾选/取消多个 API Key 对该模型的访问权（model-level `ApiKeyModelAccess` 表）。

**Architecture:** 新增两个后端路由 `GET /admin/api/models/{id}/api-keys` 和 `PUT /admin/api/models/{id}/api-keys`（Set 语义）。前端新增一个 modal 容器 + 一组 JS 函数，操作复用现有 `mgFetch` / `fetchJsonOrRedirect` / `escapeHtml` / `loadModels`。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy async / Pydantic；前端纯内联 JS + Tailwind，无构建。测试用 `unittest`（`python -m unittest`）。

**Spec:** `docs/superpowers/specs/2026-07-17-model-api-key-binding-modal-design.md`

## Global Constraints

- 权限：新接口用 `model.update`（与 `PUT /models/{id}` 一致）。
- 写库后必须 `await load_api_keys()` 刷新运行时权限缓存。
- `ApiKeyModelAccess(api_key_id, model_id)` 是 Set 语义；保存时空列表合法（= 关闭所有访问）。
- 空目标列表时**不可**生成 `NOT IN ()`（SQL 语义为恒真），必须用 `delete().where(model_id==...)` 分支。
- 前端 modal 结构参照 `web/templates/admin/config.html` 现有 modal：`max-h-[calc(100dvh-4rem)] flex min-h-0 flex-col overflow-hidden`，body `overflow-y-auto`，footer `border-t shrink-0`。
- 颜色约定：路由配置=紫，编辑=蓝，删除=红，Key 绑定=amber 黄。
- 测试命令：`python -m unittest tests.test_admin_models tests.test_admin_ui_static -v`
- 提交时不要 `git add .`，只 stage 本任务涉及的文件。

---

### Task 1: 后端 GET 接口 — 列出 Key 与已绑定集合

**Files:**
- Modify: `app/routes/models.py`（顶部 imports + 文件末尾新增路由）
- Test: `tests/test_admin_models.py`（新增测试方法）

**Interfaces:**
- Produces: `GET /admin/api/models/{model_id}/api-keys` → `{"model_id": int, "api_keys": [{"id","name","email","is_active","is_expired","tags"}], "bound_key_ids": [int]}`

- [ ] **Step 1: 加 imports 和 datetime**

修改 `app/routes/models.py:1-7`，在现有 import 基础上加 `datetime`、`ApiKey`、`ApiKeyTag`、`delete`。

把文件开头改成：
```python
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from typing import Optional, Union
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import (
    async_session_maker,
    Model,
    ApiKey,
    ApiKeyModel,
    ApiKeyModelAccess,
    ApiKeyTag,
    ProviderModel,
)
```

- [ ] **Step 2: 写失败的后端测试**

在 `tests/test_admin_models.py` 的 `AdminModelListTests` 类里，紧跟 `test_auto_model_config_maps_provider_model_candidates_to_standard_models` 方法之后，加三个测试方法。需要先在文件顶部 import 里加 `get_model_api_keys`：

```python
from app.routes.models import (
    AutoModelConfigUpdate,
    get_auto_model_config,
    get_model_api_keys,
    list_all_models,
    update_auto_model_config,
)
```

测试方法：
```python
    async def test_get_model_api_keys_returns_all_keys_and_bound_set(self):
        from datetime import datetime, timedelta

        key_a = SimpleNamespace(id=1, name="Key A", email="a@x.com",
                                is_active=True, expires_at=None)
        key_b = SimpleNamespace(id=2, name="Key B", email="b@x.com",
                                is_active=False, expires_at=datetime.now() - timedelta(days=1))
        key_c = SimpleNamespace(id=3, name="Key C", email=None,
                                is_active=True, expires_at=None)
        session = _FakeSession(
            [
                _FakeResult(one=SimpleNamespace(id=42)),  # model lookup
                _FakeResult(values=[key_a, key_b, key_c]),  # all api keys
                _FakeResult(rows=[(1,), (1,), (3,), (99,)]),  # ApiKeyTag rows (ak_id, tag)
                _FakeResult(rows=[(2,)]),  # bound api_key_ids for this model
            ]
        )

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            data = await get_model_api_keys(42, _=True)

        self.assertEqual(data["model_id"], 42)
        ids = [k["id"] for k in data["api_keys"]]
        self.assertEqual(ids, [1, 2, 3])
        b_key = next(k for k in data["api_keys"] if k["id"] == 2)
        self.assertFalse(b_key["is_active"])
        self.assertTrue(b_key["is_expired"])
        a_key = next(k for k in data["api_keys"] if k["id"] == 1)
        self.assertEqual(a_key["tags"], ["vip"])
        self.assertEqual(data["bound_key_ids"], [2])

    async def test_get_model_api_keys_returns_404_when_model_missing(self):
        session = _FakeSession([_FakeResult(one=None)])

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            data = await get_model_api_keys(999, _=True)

        self.assertIsInstance(data, JSONResponse)
        self.assertEqual(data.status_code, 404)
```

- [ ] **Step 3: 跑测试，确认 FAIL**

Run: `python -m unittest tests.test_admin_models.AdminModelListTests.test_get_model_api_keys_returns_all_keys_and_bound_set tests.test_admin_models.AdminModelListTests.test_get_model_api_keys_returns_404_when_model_missing -v`

Expected: ImportError on `get_model_api_keys`，或 NameError。

- [ ] **Step 4: 实现 GET 路由**

在 `app/routes/models.py` 文件**末尾**追加：

```python
@router.get("/models/{model_id}/api-keys")
async def get_model_api_keys(
    model_id: int,
    _: bool = Depends(permission_required("model.update")),
):
    async with async_session_maker() as session:
        model_result = await session.execute(select(Model).where(Model.id == model_id))
        if model_result.scalar_one_or_none() is None:
            return JSONResponse({"error": "Model not found"}, status_code=404)

        keys_result = await session.execute(select(ApiKey).order_by(ApiKey.name))
        keys = keys_result.scalars().all()

        tag_rows: list[tuple[int, str]] = []
        if keys:
            tag_result = await session.execute(
                select(ApiKeyTag.api_key_id, ApiKeyTag.tag).where(
                    ApiKeyTag.api_key_id.in_([k.id for k in keys])
                )
            )
            tag_rows = [(int(r[0]), str(r[1])) for r in tag_result.fetchall()]

        tags_by_key: dict[int, list[str]] = {}
        for ak_id, tag in tag_rows:
            tags_by_key.setdefault(ak_id, []).append(tag)

        bound_result = await session.execute(
            select(ApiKeyModelAccess.api_key_id).where(
                ApiKeyModelAccess.model_id == model_id
            )
        )
        bound_ids = [int(r[0]) for r in bound_result.fetchall()]

        now = datetime.now()
        api_keys_out = []
        for k in keys:
            api_keys_out.append({
                "id": k.id,
                "name": k.name,
                "email": k.email,
                "is_active": bool(k.is_active),
                "is_expired": bool(k.expires_at and k.expires_at < now),
                "tags": tags_by_key.get(k.id, []),
            })

        return {
            "model_id": model_id,
            "api_keys": api_keys_out,
            "bound_key_ids": bound_ids,
        }
```

- [ ] **Step 5: 跑测试，确认 PASS**

Run: `python -m unittest tests.test_admin_models.AdminModelListTests.test_get_model_api_keys_returns_all_keys_and_bound_set tests.test_admin_models.AdminModelListTests.test_get_model_api_keys_returns_404_when_model_missing -v`

Expected: 2 tests PASS。

如果失败：注意 `_FakeResult.rows` 的第三项（tag rows）顺序必须与 `(api_key_id, tag)` 元组对应；`fetchall()` 返回 `_rows`。

- [ ] **Step 6: Commit**

```bash
git add app/routes/models.py tests/test_admin_models.py
git commit -m "feat: add GET /admin/api/models/{id}/api-keys endpoint"
```

---

### Task 2: 后端 PUT 接口 — Set 语义写入

**Files:**
- Modify: `app/routes/models.py`（追加 PUT 路由 + Pydantic body）
- Test: `tests/test_admin_models.py`（追加测试方法）

**Interfaces:**
- Consumes: Task 1 的 imports（`delete`, `ApiKeyModelAccess`, `load_api_keys` 已就位）
- Produces: `PUT /admin/api/models/{model_id}/api-keys` body `{"api_key_ids": [int]}` → `{"model_id": int, "api_key_ids": [int]}`

- [ ] **Step 1: 写失败的 PUT 测试**

在 `tests/test_admin_models.py` 顶部 import 里加 `update_model_api_keys`：

```python
from app.routes.models import (
    AutoModelConfigUpdate,
    get_auto_model_config,
    get_model_api_keys,
    list_all_models,
    update_auto_model_config,
    update_model_api_keys,
)
```

在 `AdminModelListTests` 类末尾追加测试方法。`_FakeSession.execute` 在每条 SQL 上消费一个 result，所以要按顺序排好：
```python
    async def test_put_model_api_keys_set_semantics_diff_and_add(self):
        existing_model = SimpleNamespace(id=42)
        session = _FakeSession(
            [
                _FakeResult(one=existing_model),  # model exists
                _FakeResult(),                    # delete (not_in [1,3])
                _FakeResult(rows=[(3,)]),         # existing api_key_ids after delete
            ]
        )

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.routes.models.load_api_keys") as load_keys,
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(42, ModelApiKeysUpdate(api_key_ids=[1, 3]), _=True)

        self.assertEqual(data, {"model_id": 42, "api_key_ids": [1, 3]})
        added_ids = [obj.api_key_id for obj in session.added if isinstance(obj, ApiKeyModelAccess)]
        self.assertEqual(sorted(added_ids), [1])
        load_keys.assert_awaited_once()

    async def test_put_model_api_keys_empty_list_clears_all(self):
        existing_model = SimpleNamespace(id=42)
        session = _FakeSession(
            [
                _FakeResult(one=existing_model),  # model exists
                _FakeResult(),                    # delete all where model_id==42
            ]
        )

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.routes.models.load_api_keys"),
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(42, ModelApiKeysUpdate(api_key_ids=[]), _=True)

        self.assertEqual(data, {"model_id": 42, "api_key_ids": []})
        self.assertEqual(session.added, [])

    async def test_put_model_api_keys_returns_404_when_model_missing(self):
        session = _FakeSession([_FakeResult(one=None)])

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(999, ModelApiKeysUpdate(api_key_ids=[1]), _=True)

        self.assertIsInstance(data, JSONResponse)
        self.assertEqual(data.status_code, 404)
```

`_FakeResult()` 无参数 → `rows=[]`、`values=[]`、`one=None`，正好用于"消费掉 delete 语句的 execute"（delete 返回值不被使用）。

- [ ] **Step 2: 跑测试，确认 FAIL**

Run: `python -m unittest tests.test_admin_models.AdminModelListTests.test_put_model_api_keys_set_semantics_diff_and_add tests.test_admin_models.AdminModelListTests.test_put_model_api_keys_empty_list_clears_all tests.test_admin_models.AdminModelListTests.test_put_model_api_keys_returns_404_when_model_missing -v`

Expected: ImportError on `update_model_api_keys`。

- [ ] **Step 3: 实现 PUT 路由**

在 `app/routes/models.py` Task 1 的 GET 路由**之后**追加。注意：先在文件中找到 `class AutoPoolItem` 附近的位置（约第 52 行），在 `AutoModelConfigUpdate` 定义后追加 Pydantic body 类。最简单的做法是直接在 GET 路由之前加：

```python
class ModelApiKeysUpdate(BaseModel):
    api_key_ids: list[int] = Field(default_factory=list)
```

然后在 GET 路由之后追加路由函数：

```python
@router.put("/models/{model_id}/api-keys")
async def update_model_api_keys(
    model_id: int,
    data: ModelApiKeysUpdate,
    _: bool = Depends(permission_required("model.update")),
):
    target_ids = sorted({int(x) for x in data.api_key_ids if int(x) > 0})
    async with async_session_maker() as session:
        model_result = await session.execute(select(Model).where(Model.id == model_id))
        if model_result.scalar_one_or_none() is None:
            return JSONResponse({"error": "Model not found"}, status_code=404)

        if target_ids:
            await session.execute(
                delete(ApiKeyModelAccess)
                .where(ApiKeyModelAccess.model_id == model_id)
                .where(ApiKeyModelAccess.api_key_id.not_in(target_ids))
            )
            existing_result = await session.execute(
                select(ApiKeyModelAccess.api_key_id).where(
                    ApiKeyModelAccess.model_id == model_id
                )
            )
            existing_ids = {int(r[0]) for r in existing_result.fetchall()}
            for ak_id in target_ids:
                if ak_id not in existing_ids:
                    session.add(ApiKeyModelAccess(api_key_id=ak_id, model_id=model_id))
        else:
            await session.execute(
                delete(ApiKeyModelAccess).where(
                    ApiKeyModelAccess.model_id == model_id
                )
            )
        await session.commit()
    await load_api_keys()
    return {"model_id": model_id, "api_key_ids": target_ids}
```

关键点：
- `target_ids` 为空时走 else 分支，避免 `NOT IN ()` 恒真 bug。
- 用 `existing_ids` 计算差集，避免重复 INSERT（虽然表上有 unique 约束兜底）。
- 末尾 `await load_api_keys()` 刷新运行时权限缓存。

- [ ] **Step 4: 跑全部 admin_models 测试，确认 PASS**

Run: `python -m unittest tests.test_admin_models -v`

Expected: 所有测试 PASS（包括 Task 1 的 2 个）。

- [ ] **Step 5: Commit**

```bash
git add app/routes/models.py tests/test_admin_models.py
git commit -m "feat: add PUT /admin/api/models/{id}/api-keys endpoint with set semantics"
```

---

### Task 3: 前端 — Modal HTML 容器 + 表格行入口按钮

**Files:**
- Modify: `web/templates/admin/config.html`（两处：① 紧跟 `model-routing-drawer` 后加 modal 容器；② `renderModelTable` 操作列加按钮）
- Test: `tests/test_admin_ui_static.py`（追加断言）

**Interfaces:**
- Produces: DOM 元素 `#model-apikeys-modal`、`#model-apikeys-title`、`#model-apikeys-search`、`#model-apikeys-count`、`#model-apikeys-list`；函数 `openModelApiKeysModal`、`closeModelApiKeysModal`、`saveModelApiKeys`、`renderModelApiKeysList`、`selectAllModelApiKeys`、`clearAllModelApiKeys`、`onModelApiKeyToggle`。这些函数在 Task 4 实现。

- [ ] **Step 1: 写失败的静态测试**

在 `tests/test_admin_ui_static.py` 的 `AdminUiStaticTests` 类里，紧跟 `test_auto_virtual_model_delete_button_is_hidden` 方法之后追加：

```python
    def test_model_apikeys_modal_has_required_dom_and_handlers(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn('id="model-apikeys-modal"', html)
        self.assertIn('id="model-apikeys-title"', html)
        self.assertIn('id="model-apikeys-search"', html)
        self.assertIn('id="model-apikeys-count"', html)
        self.assertIn('id="model-apikeys-list"', html)
        self.assertIn("openModelApiKeysModal", html)
        self.assertIn("closeModelApiKeysModal", html)
        self.assertIn("saveModelApiKeys", html)
        self.assertIn("renderModelApiKeysList", html)
        self.assertIn("selectAllModelApiKeys", html)
        self.assertIn("clearAllModelApiKeys", html)
        self.assertIn("onModelApiKeyToggle", html)

    def test_model_table_row_has_apikeys_button(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        table_start = html.index("function renderModelTable(models)")
        table_end = html.index("function isProtectedAutoModel", table_start)
        table_body = html[table_start:table_end]

        self.assertIn("openModelApiKeysModal(${m.id})", table_body)
        self.assertIn("text-amber-500", table_body)
```

- [ ] **Step 2: 跑测试，确认 FAIL**

Run: `python -m unittest tests.test_admin_ui_static.AdminUiStaticTests.test_model_apikeys_modal_has_required_dom_and_handlers tests.test_admin_ui_static.AdminUiStaticTests.test_model_table_row_has_apikeys_button -v`

Expected: 2 tests FAIL（找不到 `id="model-apikeys-modal"` / `openModelApiKeysModal`）。

- [ ] **Step 3: 在 `model-routing-drawer` 之后加 modal 容器**

在 `web/templates/admin/config.html` 中找到 `</div>` 结束 `model-routing-drawer` 的位置（约第 427 行），紧跟其后插入：

```html

    <div id="model-apikeys-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50 p-3">
        <div class="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[calc(100dvh-4rem)] flex min-h-0 flex-col overflow-hidden">
            <div class="p-4 border-b flex justify-between items-center shrink-0">
                <h3 id="model-apikeys-title" class="font-semibold"></h3>
                <button onclick="closeModelApiKeysModal()" class="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
            </div>
            <div class="px-4 py-3 border-b shrink-0 flex items-center gap-2 flex-wrap">
                <input id="model-apikeys-search" type="text" placeholder="搜索名称/email/tag..." oninput="renderModelApiKeysList()" class="flex-1 min-w-[12rem] border rounded px-3 py-1.5 text-sm">
                <button onclick="selectAllModelApiKeys()" class="text-xs text-blue-500 hover:text-blue-700 px-2 py-1">全选</button>
                <button onclick="clearAllModelApiKeys()" class="text-xs text-gray-500 hover:text-gray-700 px-2 py-1">清空</button>
                <span id="model-apikeys-count" class="text-xs text-gray-400 ml-auto"></span>
            </div>
            <div id="model-apikeys-list" class="p-4 overflow-y-auto flex-1 min-h-0"></div>
            <div class="p-4 border-t shrink-0 flex justify-end gap-2">
                <button onclick="closeModelApiKeysModal()" class="px-4 py-2 border rounded text-sm hover:bg-gray-50">取消</button>
                <button onclick="saveModelApiKeys()" class="px-4 py-2 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">保存</button>
            </div>
        </div>
    </div>
```

- [ ] **Step 4: 在 `renderModelTable` 操作列加按钮**

在 `web/templates/admin/config.html` 中找到这段（约 1794 行）：
```js
<button onclick="openModelRoutingConfig(${m.id})" class="icon-btn text-purple-500 hover:text-purple-700" title="路由配置">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.59 13.51 15.42 17.49"/><path d="M15.41 6.51 8.59 10.49"/></svg>
</button>
```

紧跟其**后**插入：
```js
                                        <button onclick="openModelApiKeysModal(${m.id})" class="icon-btn text-amber-500 hover:text-amber-700" title="API Key 绑定">
                                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                                        </button>
```

注意保持与同级按钮相同的缩进（同级 `<button>` 在模板字符串中缩进 40 个空格）。

- [ ] **Step 5: 跑测试，确认 Task 3 两个测试 PASS**

Run: `python -m unittest tests.test_admin_ui_static.AdminUiStaticTests.test_model_apikeys_modal_has_required_dom_and_handlers tests.test_admin_ui_static.AdminUiStaticTests.test_model_table_row_has_apikeys_button -v`

Expected: 2 tests PASS。

- [ ] **Step 6: Commit**

```bash
git add web/templates/admin/config.html tests/test_admin_ui_static.py
git commit -m "feat(ui): add model api key binding modal container and table button"
```

---

### Task 4: 前端 — JS 函数实现

**Files:**
- Modify: `web/templates/admin/config.html`（`<script>` 块内追加 JS 函数，紧跟 `isProtectedAutoModel` 之后）
- Test: `tests/test_admin_ui_static.py`（更细的字符串断言）

**Interfaces:**
- Consumes: 已存在的全局：`allModels`、`APP_BASE_PATH`、`fetchJsonOrRedirect`、`mgFetch`、`escapeHtml`、`loadModels`。后端 Task 1+2 的接口。

- [ ] **Step 1: 写失败的 JS 行为测试**

在 `tests/test_admin_ui_static.py` 顶部 `test_model_apikeys_modal_has_required_dom_and_handlers` 后追加更具体的断言：

```python
    def test_model_apikeys_js_uses_set_semantics_and_correct_endpoints(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        js_start = html.index("function openModelApiKeysModal")
        js_end = html.index("async function saveModelApiKeys", js_start)
        js_end = html.index("}", html.index("await loadModels()", js_end)) + 1
        js_body = html[js_start:js_end]

        self.assertIn("/admin/api/models/${modelId}/api-keys", js_body)
        self.assertIn("modelApiKeysBound = new Set", js_body)
        self.assertIn("api_key_ids: ids", js_body)
        self.assertIn("await loadModels()", js_body)
        self.assertIn("modelApiKeysBound.has(Number(k.id))", js_body)
        self.assertIn("modelApiKeysBound.add(Number(k.id))", js_body)
        self.assertIn("modelApiKeysBound.delete(Number(k.id))", js_body)
```

- [ ] **Step 2: 跑测试，确认 FAIL**

Run: `python -m unittest tests.test_admin_ui_static.AdminUiStaticTests.test_model_apikeys_js_uses_set_semantics_and_correct_endpoints -v`

Expected: ValueError: `function openModelApiKeysModal` is not in string（函数还没写）。

- [ ] **Step 3: 实现 JS 函数**

在 `web/templates/admin/config.html` 中找到 `function isProtectedAutoModel(model) { ... }` 这一段（约 1812 行），在其 `}` 结束后插入（与 `isProtectedAutoModel` 同级缩进，即 8 个空格）：

```js

        let modelApiKeysTarget = null;
        let modelApiKeysCache = [];
        let modelApiKeysBound = new Set();

        async function openModelApiKeysModal(modelId) {
            modelApiKeysTarget = modelId;
            const m = allModels.find(x => x.id === modelId);
            document.getElementById('model-apikeys-title').textContent = `${m ? (m.display_name || m.name) : '模型'} · API Key 访问`;
            document.getElementById('model-apikeys-search').value = '';
            document.getElementById('model-apikeys-count').textContent = '';
            document.getElementById('model-apikeys-list').innerHTML = '<div class="text-center text-gray-400 py-8">加载中...</div>';
            const modal = document.getElementById('model-apikeys-modal');
            modal.classList.remove('hidden'); modal.classList.add('flex');
            try {
                const data = await fetchJsonOrRedirect(`${APP_BASE_PATH}/admin/api/models/${modelId}/api-keys`);
                modelApiKeysCache = data.api_keys || [];
                modelApiKeysBound = new Set((data.bound_key_ids || []).map(Number));
                renderModelApiKeysList();
            } catch(e) {
                document.getElementById('model-apikeys-list').innerHTML = '<div class="text-center text-red-500 py-8">加载失败</div>';
            }
        }

        function _modelApiKeysSearchTerm() {
            return (document.getElementById('model-apikeys-search')?.value || '').trim().toLowerCase();
        }

        function _modelApiKeyMatches(k, term) {
            if (!term) return true;
            const hay = [k.name, k.email, (k.tags || []).join(' ')].filter(Boolean).join(' ').toLowerCase();
            return hay.includes(term);
        }

        function renderModelApiKeysList() {
            const list = document.getElementById('model-apikeys-list');
            const term = _modelApiKeysSearchTerm();
            const filtered = modelApiKeysCache.filter(k => _modelApiKeyMatches(k, term));
            if (!filtered.length) {
                list.innerHTML = '<div class="text-center text-gray-400 py-8">没有匹配的 API Key</div>';
            } else {
                list.innerHTML = filtered.map(k => {
                    const checked = modelApiKeysBound.has(Number(k.id)) ? 'checked' : '';
                    const statusPill = !k.is_active
                        ? '<span class="text-xs text-red-500">停用</span>'
                        : (k.is_expired ? '<span class="text-xs text-red-500">过期</span>' : '<span class="text-xs text-green-500">可用</span>');
                    const tags = (k.tags || []).map(tg => `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700">${escapeHtml(tg)}</span>`).join(' ');
                    return `<label class="flex items-center gap-3 py-2 px-3 rounded border hover:bg-gray-50 cursor-pointer">
                        <input type="checkbox" class="model-ak-check" data-ak-id="${k.id}" ${checked} onchange="onModelApiKeyToggle(${k.id}, this.checked)">
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="text-sm font-medium text-gray-800 truncate">${escapeHtml(k.name)}</span>
                                ${statusPill}
                            </div>
                            <div class="text-xs text-gray-400 truncate">${escapeHtml(k.email || '')}${tags ? ' · ' + tags : ''}</div>
                        </div>
                    </label>`;
                }).join('');
            }
            document.getElementById('model-apikeys-count').textContent = `已选 ${modelApiKeysBound.size} / 共 ${modelApiKeysCache.length}`;
        }

        function onModelApiKeyToggle(id, checked) {
            id = Number(id);
            if (checked) modelApiKeysBound.add(id); else modelApiKeysBound.delete(id);
            document.getElementById('model-apikeys-count').textContent = `已选 ${modelApiKeysBound.size} / 共 ${modelApiKeysCache.length}`;
        }

        function selectAllModelApiKeys() {
            const term = _modelApiKeysSearchTerm();
            modelApiKeysCache.forEach(k => {
                if (_modelApiKeyMatches(k, term)) modelApiKeysBound.add(Number(k.id));
            });
            renderModelApiKeysList();
        }

        function clearAllModelApiKeys() {
            const term = _modelApiKeysSearchTerm();
            if (!term) {
                modelApiKeysBound.clear();
            } else {
                modelApiKeysCache.forEach(k => {
                    if (_modelApiKeyMatches(k, term)) modelApiKeysBound.delete(Number(k.id));
                });
            }
            renderModelApiKeysList();
        }

        function closeModelApiKeysModal() {
            const modal = document.getElementById('model-apikeys-modal');
            modal.classList.add('hidden'); modal.classList.remove('flex');
            modelApiKeysTarget = null;
            modelApiKeysCache = [];
            modelApiKeysBound = new Set();
        }

        async function saveModelApiKeys() {
            if (!modelApiKeysTarget) return;
            const ids = [...modelApiKeysBound].map(Number);
            try {
                await mgFetch(`${APP_BASE_PATH}/admin/api/models/${modelApiKeysTarget}/api-keys`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key_ids: ids})
                }, {success: 'API Key 绑定已保存', error: '保存失败'});
                closeModelApiKeysModal();
                await loadModels();
            } catch(e) {}
        }
```

关键点：
- 用 `Set` 存当前选中（呼应后端 Set 语义）。
- 搜索框非空时"全选/清空"只作用于过滤结果（更直觉，避免清空时误删看不见的项）。
- 关闭 modal 时清空三个全局变量，避免下次打开看到旧数据。
- 复用 `mgFetch`（自带 toast 和 401 重定向）。

- [ ] **Step 4: 跑 Task 4 测试，确认 PASS**

Run: `python -m unittest tests.test_admin_ui_static.AdminUiStaticTests.test_model_apikeys_js_uses_set_semantics_and_correct_endpoints -v`

Expected: PASS。

- [ ] **Step 5: 跑整个相关测试套件，确认无回归**

Run: `python -m unittest tests.test_admin_models tests.test_admin_ui_static -v`

Expected: 全部新测试 PASS；原有测试除已知的 3 个失败（`test_saving_auto_model_config_with_provider_model_candidates_activates_auto_model`、`test_auto_model_picker_uses_compact_modal_not_tall_multiselect`、`test_model_routing_matrix_uses_compact_responsive_layout`，均与本特性无关）外都 PASS。

- [ ] **Step 6: Commit**

```bash
git add web/templates/admin/config.html tests/test_admin_ui_static.py
git commit -m "feat(ui): implement model api key binding modal logic"
```

---

## Self-Review Checklist

- [x] Spec 覆盖：GET 接口（Task 1）、PUT Set 语义含空列表分支（Task 2）、modal HTML+表格按钮（Task 3）、JS 函数含搜索/全选/清空/Set 语义（Task 4）— 全覆盖。
- [x] 无占位符：所有 step 都有完整代码。
- [x] 类型一致：`modelApiKeysBound` 在 Task 3 测试、Task 4 实现里都是 `Set`；`api_key_ids` 在 body 类、后端、前端一致。
- [x] 已知失败不算回归（在 Task 4 Step 5 注明）。
