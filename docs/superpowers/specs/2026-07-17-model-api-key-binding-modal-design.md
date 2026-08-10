# 标准模型 → API Key 绑定弹框

## 背景

当前标准模型表格的"绑定 Key"列只显示数量，没有直接管理入口。要给一个模型配多个 Key 的访问权，必须逐个打开每个 API Key 的编辑弹框去勾选模型，方向反了，效率低。

历史上 commit `cf9189d` 曾实现过单模型 → 弹框 → 卡片式批量勾选 Keys 的功能（针对 provider-model 级别的 `ApiKeyModel` 表），后来在 `7781951` 重构路由 UI 时被移除。

## 目标

为标准模型表格的每一行加一个"Key 绑定"入口，点击弹出一个卡片式弹框，可一次性勾选/取消多个 API Key 对该模型的访问权。典型场景：新增一个模型后，立即把若干 API Key 接入。

## 非目标

- 不做"多选模型 → 批量绑定"（真正的多对多批量）。每次只针对一个模型。
- 不改动 provider-model 级别的 `ApiKeyModel` 绑定关系。新弹框只操作 model-level 的 `ApiKeyModelAccess` 表，与现有 API Key 编辑弹框里的"标准模型多选"完全等价，只是入口方向反过来。
- 不动 Key 的其他模型绑定。

## 用户流程

1. 管理员在 `配置 → 标准模型` 表格的某一行，点击操作列新增的"Key 绑定"图标（钥匙图标，amber 黄色，紧挨紫色路由配置按钮；区别于紫色=路由、蓝色=编辑、红色=删除）。
2. 弹框打开，标题为 `<模型 display_name> · API Key 访问`。
3. 弹框顶部有搜索框（按名称/email/tag 模糊过滤）、`全选`、`清空`、计数器 `已选 X / 共 Y`。
4. 列表展示所有 API Key（不限 is_active，但停用/过期的用红色标记），每个 Key 一行：checkbox + 名称 + email + 状态标签 + tags。
5. 已绑定此模型的 Key 预勾选。
6. 用户增删勾选，点保存；后端用 **Set 语义**写库，弹框关闭，标准模型表格的"绑定 Key"列数字刷新。

## UI 细节

参照现有 admin modal 风格（`max-height: calc(100dvh - 4rem)`，固定底部 actions，可滚动 body）：

```
┌─────────────────────────────────────────────────┐
│ <模型名> · API Key 访问                    [×]  │  header (fixed)
├─────────────────────────────────────────────────┤
│ [搜索____________]  [全选] [清空]  已选 3 / 共 12│  toolbar (fixed)
├─────────────────────────────────────────────────┤
│ ☑ Key A    user@example.com   [active]  [vip]   │
│ ☑ Key B    alice@...          [active]          │  body (scroll)
│ ☐ Key C    bob@...            [停用]            │
│ ...                                              │
├─────────────────────────────────────────────────┤
│                          [取消]  [保存]          │  footer (fixed)
└─────────────────────────────────────────────────┘
```

弹框结构与 `apikey-modal`（`web/templates/admin/api_keys.html`）保持一致：外层 `fixed inset-0 bg-black bg-opacity-50`，卡片 `flex min-h-0 flex-1 flex-col overflow-hidden`，body `overflow-y-auto`，footer `border-t shrink-0`。

## 数据模型

只用 `ApiKeyModelAccess(api_key_id, model_id)` 表（已有 `idx_api_key_model_access_model_id` 索引）。该表的成员集合 = "这个模型被哪些 Key 访问"。

> 注：标准模型表格的 `bound_key_count` 已经聚合了 `ApiKeyModel`（PM 级）和 `ApiKeyModelAccess`（model 级）两类绑定，所以保存后 `loadModels()` 会自动反映变化。

## 后端接口

新增到 `app/routes/models.py`，权限 `model.update`（与现有 `PUT /models/{id}` 一致）。

### `GET /admin/api/models/{model_id}/api-keys`

返回：
```json
{
  "model_id": 42,
  "api_keys": [
    {
      "id": 1,
      "name": "Key A",
      "email": "user@example.com",
      "is_active": true,
      "is_expired": false,
      "tags": ["vip"]
    }
  ],
  "bound_key_ids": [1, 3]
}
```

实现：一次 `select(ApiKey)` 拿全部 Key（含 `is_active`、`expires_at`、关联 `ApiKeyTag`）；一次 `select(ApiKeyModelAccess.api_key_id).where(model_id=...)` 拿已绑定集合。`is_expired` 在 Python 里用 `expires_at < datetime.now()` 计算。

### `PUT /admin/api/models/{model_id}/api-keys`

Body：
```json
{ "api_key_ids": [1, 3, 5] }
```

Set 语义实现（伪码）：
```python
async with async_session_maker() as session:
    # 1. 校验 model 存在
    # 2. 删除不再勾选的
    await session.execute(
        delete(ApiKeyModelAccess)
        .where(ApiKeyModelAccess.model_id == model_id)
        .where(ApiKeyModelAccess.api_key_id.not_in(target_ids))
    )
    # 3. 拉取已存在的，算出要新增的
    existing = await session.execute(
        select(ApiKeyModelAccess.api_key_id)
        .where(ApiKeyModelAccess.model_id == model_id)
    )
    to_add = set(target_ids) - set(existing.scalars().all())
    for ak_id in to_add:
        session.add(ApiKeyModelAccess(api_key_id=ak_id, model_id=model_id))
    await session.commit()
await load_api_keys()  # 刷新运行时缓存
return {"model_id": model_id, "api_key_ids": target_ids}
```

`target_ids` 为空时第 2 步会删完所有绑定（合法：表示此模型对所有 Key 关闭）。空列表时 `not_in(...)` 在 SQLAlchemy 里要避免生成 `NOT IN ()`（恒真），需要分支处理：空集时直接 `delete().where(model_id == ...)`。

## 前端实现

### HTML（`web/templates/admin/config.html`）

1. 新增 modal 容器（紧跟 `model-routing-drawer` 之后）：
```html
<div id="model-apikeys-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
  <div class="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[calc(100dvh-4rem)] flex min-h-0 flex-col overflow-hidden">
    <div class="p-4 border-b flex justify-between items-center shrink-0">
      <h3 id="model-apikeys-title" class="font-semibold"></h3>
      <button onclick="closeModelApiKeysModal()" class="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
    </div>
    <div class="px-4 py-3 border-b shrink-0 flex items-center gap-2 flex-wrap">
      <input id="model-apikeys-search" type="text" placeholder="搜索名称/email/tag..."
             oninput="renderModelApiKeysList()" class="flex-1 min-w-[12rem] border rounded px-3 py-1.5 text-sm">
      <button onclick="selectAllModelApiKeys()" class="text-xs text-blue-500 hover:text-blue-700 px-2 py-1">全选</button>
      <button onclick="clearAllModelApiKeys()" class="text-xs text-gray-500 hover:text-gray-700 px-2 py-1">清空</button>
      <span id="model-apikeys-count" class="text-xs text-gray-400 ml-auto"></span>
    </div>
    <div id="model-apikeys-list" class="p-4 overflow-y-auto flex-1 space-y-1"></div>
    <div class="p-4 border-t shrink-0 flex justify-end gap-2">
      <button onclick="closeModelApiKeysModal()" class="px-4 py-2 border rounded text-sm hover:bg-gray-50">取消</button>
      <button onclick="saveModelApiKeys()" class="px-4 py-2 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">保存</button>
    </div>
  </div>
</div>
```

2. 在 `renderModelTable` 的操作列，紧挨 `openModelRoutingConfig` 按钮加：
```js
<button onclick="openModelApiKeysModal(${m.id})" class="icon-btn text-amber-500 hover:text-amber-700" title="API Key 绑定">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
  </svg>
</button>
```

### JS（`web/templates/admin/config.html` `<script>` 块）

```js
let modelApiKeysTarget = null;
let modelApiKeysCache = [];
let modelApiKeysBound = new Set();

async function openModelApiKeysModal(modelId) {
  modelApiKeysTarget = modelId;
  const m = allModels.find(x => x.id === modelId);
  const titleEl = document.getElementById('model-apikeys-title');
  titleEl.textContent = `${m ? (m.display_name || m.name) : '模型'} · API Key 访问`;
  document.getElementById('model-apikeys-search').value = '';
  document.getElementById('model-apikeys-list').innerHTML = '<div class="text-center text-gray-400 py-8">加载中...</div>';
  document.getElementById('model-apikeys-count').textContent = '';
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

function renderModelApiKeysList() {
  const term = (document.getElementById('model-apikeys-search')?.value || '').trim().toLowerCase();
  const list = document.getElementById('model-apikeys-list');
  const filtered = modelApiKeysCache.filter(k => {
    if (!term) return true;
    const hay = [k.name, k.email, (k.tags || []).join(' ')].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(term);
  });
  if (!filtered.length) {
    list.innerHTML = '<div class="text-center text-gray-400 py-8">没有匹配的 API Key</div>';
  } else {
    list.innerHTML = filtered.map(k => {
      const checked = modelApiKeysBound.has(Number(k.id));
      const statusPill = !k.is_active
        ? '<span class="text-xs text-red-500">停用</span>'
        : (k.is_expired ? '<span class="text-xs text-red-500">过期</span>' : '<span class="text-xs text-green-500">可用</span>');
      const tags = (k.tags || []).map(t => `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700">${escapeHtml(t)}</span>`).join(' ');
      return `<label class="flex items-center gap-3 py-2 px-3 rounded border hover:bg-gray-50 cursor-pointer">
        <input type="checkbox" class="model-ak-check" data-ak-id="${k.id}" ${checked ? 'checked' : ''} onchange="onModelApiKeyToggle(${k.id}, this.checked)">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-gray-800 truncate">${escapeHtml(k.name)}</span>
            ${statusPill}
          </div>
          <div class="text-xs text-gray-400 truncate">${escapeHtml(k.email || '')}${tags ? ' · ' + tags : ''}</div>
        </div>
      </label>`;
    }).join('');
  }
  const total = modelApiKeysCache.length;
  document.getElementById('model-apikeys-count').textContent = `已选 ${modelApiKeysBound.size} / 共 ${total}`;
}

function onModelApiKeyToggle(id, checked) {
  id = Number(id);
  if (checked) modelApiKeysBound.add(id); else modelApiKeysBound.delete(id);
  document.getElementById('model-apikeys-count').textContent = `已选 ${modelApiKeysBound.size} / 共 ${modelApiKeysCache.length}`;
}

function selectAllModelApiKeys() {
  const term = (document.getElementById('model-apikeys-search')?.value || '').trim().toLowerCase();
  modelApiKeysCache.forEach(k => {
    if (!term) { modelApiKeysBound.add(Number(k.id)); return; }
    const hay = [k.name, k.email, (k.tags || []).join(' ')].filter(Boolean).join(' ').toLowerCase();
    if (hay.includes(term)) modelApiKeysBound.add(Number(k.id));
  });
  renderModelApiKeysList();
}

function clearAllModelApiKeys() {
  // 在搜索框有内容时，"清空"只清当前过滤结果（更直觉）
  const term = (document.getElementById('model-apikeys-search')?.value || '').trim().toLowerCase();
  if (!term) { modelApiKeysBound.clear(); renderModelApiKeysList(); return; }
  modelApiKeysCache.forEach(k => {
    const hay = [k.name, k.email, (k.tags || []).join(' ')].filter(Boolean).join(' ').toLowerCase();
    if (hay.includes(term)) modelApiKeysBound.delete(Number(k.id));
  });
  renderModelApiKeysList();
}

function closeModelApiKeysModal() {
  const modal = document.getElementById('model-apikeys-modal');
  modal.classList.add('hidden'); modal.classList.remove('flex');
  modelApiKeysTarget = null; modelApiKeysCache = []; modelApiKeysBound.clear();
}

async function saveModelApiKeys() {
  if (!modelApiKeysTarget) return;
  const ids = [...modelApiKeysBound].map(Number);
  try {
    await mgFetch(`${APP_BASE_PATH}/admin/api/models/${modelApiKeysTarget}/api-keys`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({api_key_ids: ids})
    }, {success: 'API Key 绑定已保存', error: '保存失败'});
    closeModelApiKeysModal();
    await loadModels();
  } catch(e) {}
}
```

## 安全与边界

- 后端权限：`model.update`。
- `model_id` 不存在时返回 404。
- `api_key_ids` 中的 id 不存在：依赖外键约束，失败时回滚整个事务，返回 400 + 错误信息。
- 空列表合法（= 关闭所有访问），后端用 `if not target_ids: delete().where(model_id==...)` 分支。
- 调用 `load_api_keys()` 刷新运行时权限缓存，与 `update_api_key` 保持一致。

## 测试

后端单测（`tests/test_admin_models.py`）：
- `GET` 返回所有 Key + 正确的 `bound_key_ids`。
- `PUT` 新增/删除绑定：调一次 PUT，验证 `ApiKeyModelAccess` 行集合等于目标。
- `PUT []` 清空：所有相关行被删除。
- 不存在的 `model_id` → 404。

UI 静态测试（`tests/test_admin_ui_static.py`）：
- HTML 包含 `id="model-apikeys-modal"`、`openModelApiKeysModal`、`saveModelApiKeys`、`closeModelApiKeysModal`。
- `renderModelTable` 包含 `openModelApiKeysModal(${m.id})` 按钮。
- 移除老版遗留：无 `openModelKeys` / `model-keys-modal` 残留。
