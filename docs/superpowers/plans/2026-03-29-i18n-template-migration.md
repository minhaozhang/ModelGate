# i18n Template Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

 **Goal:** Migrate all inline HTML templates strings from Python `.py files constants to Jinja2 `.html template files with `{{ _() }} i18n markers for en/zh support.

 **Architecture:** Convert 11 Python template files to Jinja2 HTML. Wrap all user-visible text in `{{ _('text') }}`. Extract strings via babel, Create .po/. files file for en/zh translations. Add language switcher dropdown to admin pages. Inject JS-side i18n via a global `window.I18N` object. Update routes handlers to to call `render()` instead of returning raw string constants.

 **Tech Stack:** Jinja2, Babel, FastAPI

 existing infrastructure: `core/i18n.py`, babel.cfg, `locales/` directory

 **Branch:** `feat/i18n`

---

## File Structure

| File | Responsibility |
|------|------|
| `core/i18n.py` | Jinja2 environment, locale detection, render helper (DONE) |
| `templates/admin/login.html` | Admin login page |
| `templates/admin/home.html` | Admin dashboard |
| `templates/admin/config.html` | Provider/model config |
| `templates/admin/api_keys.html` | API key management |
| `templates/admin/monitor.html` | Statistics monitor |
| `templates/admin/usage.html` | Usage guide |
| `templates/admin/mobile.html` | Mobile login + dashboard (2 templates in 1 file) |
| `templates/user/login.html` | User login page |
| `templates/user/dashboard.html` | User dashboard |
| `templates/public/opencode.html` | OpenCode config generator |
| `templates/public/query.html` | API key query page (already a route in file) |
| `locales/en/LC_MESSAGES/messages.po` | English translations |
| `locales/zh/LC_MESSAGES/messages.po` | Chinese translations |

---

## Key Decisions: JS in templates

The templates use Python `.format()` with `{{` / `}}` for which clash with Jinja2's `{{ }}`. The templates that use `.format()` need special handling:

 to escape double braces for Jinja2 templates files, Files that DON'T use `.format()` (most of them) can be converted by simply extracting HTML from the Python string constant and wrapping text in `{{ _() }}`.

### Conventions

- Admin pages `<title>` follows pattern: `Page Name - API Proxy`
- Nav links are identical across all admin pages (Home, Config, API Keys, Monitor, Usage Guide, Logout)
- All pages have theme toggle (Dark Mode / Light Mode)
- Chinese text appears in 4 files: config.py, api_keys.py, dashboard.py, opencode.py

---

### Task 1: Create Shared Nav + Layout Components Jinja2 Macros

 **Files:**
- Create: `templates/components/nav.html` (shared admin nav sidebar with language dropdown)
- Create: `templates/components/head_nav.html` (shared nav component)

- [x] **Step 1: Create `templates/components/nav.html`**

Extract the nav section from any admin template (e.g., home.py). Make it `{{ _() }}` wrapper for i18n for nav text. Add language dropdown before Logout. Make `active_page` a parameter.

```html
<nav class="w-56 bg-white shadow-lg min-h-screen fixed">
    <div class="p-4 border-b">
        <h1 class="text-xl font-bold text-gray-800">API Proxy</h1>
    </div>
    <div class="py-2">
        <a href="/admin/home" class="nav-link {{ 'active' if active_page == 'home' else '' }} flex items-center px-4 py-3 text-gray-700">
            <svg ...>...</svg>
            {{ _('Home') }}
        </a>
        <a href="/admin/config" class="nav-link {{ 'active' if active_page == 'config' else '' }} flex items-center px-4 py-3 text-gray-700">
            <svg ...>...</svg>
            {{ _('Config') }}
        </a>
        <a href="/admin/api-keys" class="nav-link {{ 'active' if active_page == 'api-keys' else '' }} flex items-center px-4 py-3 text-gray-700">
            <svg ...>...</svg>
            {{ _('API Keys') }}
        </a>
        <a href="/admin/monitor" class="nav-link {{ 'active' if active_page == 'monitor' else '' }} flex items-center px-4 py-3 text-gray-700">
            <svg ...>...</svg>
            {{ _('Monitor') }}
        </a>
        <a href="/admin/usage" class="nav-link {{ 'active' if active_page == 'usage' else '' }} flex items-center px-4 py-3 text-gray-700">
            <svg ...>...</svg>
            {{ _('Usage Guide') }}
        </a>
    </div>
    <div class="absolute bottom-0 w-full p-4 border-t">
        <div class="mb-2">
            <select id="lang-select" onchange="switchLang(this.value)" class="w-full border rounded px-2 py-1 text-sm">
                <option value="en">English</option>
                <option value="zh">中文</option>
            </select>
        </div>
        <button onclick="logout()" class="w-full text-left text-gray-600 hover:text-red-600 flex items-center">
            <svg ...>...</svg>
            {{ _('Logout') }}
        </button>
    </div>
</nav>
```

- [x] **Step 2: Create `templates/components/lang_switch.html`**

```html
<script>
function switchLang(lang) {
    document.cookie = "lang=" + lang + ";path=/;max-age=31536000";
    window.location.reload();
}
// Auto-select current language
(function() {
    const cookies = document.cookie.split(';').map(c => c.trim());
    const langCookie = cookies.find(c => c.startsWith('lang='));
    if (langCookie) {
        const select = document.getElementById('lang-select');
        if (select) select.value = langCookie.split('=')[1];
    }
})();
</script>
```

- [ ] **Step 3: Commit**

```bash
git add templates/components/
git commit -m "feat(i18n): add shared nav component with language dropdown"
```

---

### Task 2: Convert Static Templates (no `.format()`) — 7 files

 These templates have no Python `.format()` calls. Extract HTML from Python string, wrap text with `{{ _() }}`, save as `.html`.

**Files:**
- `templates/admin/login.py` → `templates/admin/login.html`
- `templates/admin/home.py` → `templates/admin/home.html`
- `templates/admin/config.py` → `templates/admin/config.html`
- `templates/admin/api_keys.py` → `templates/admin/api_keys.html`
- `templates/admin/monitor.py` → `templates/admin/monitor.html`
- `templates/admin/usage.py` → `templates/admin/usage.html`
- `templates/public/opencode.py` → `templates/public/opencode.html`

For each file:
- [ ] **Step 1:** Copy HTML content from `.py` file, strip `VARIABLE_NAME = """` wrapper and trailing `"""`
- [ ] **Step 2:** Replace admin nav sidebar with `{% include 'components/nav.html' %}` (passing `active_page`)
- [ ] **Step 3:** Wrap all user-visible text in `{{ _() }}`. Key strings per file:

**admin/login.html:**
- `Login - API Proxy` → `<title>{{ _('Login') }} - API Proxy</title>`
- `API Proxy Login` → `{{ _('API Proxy Login') }}`
- `Username` → `{{ _('Username') }}`
- `Password` → `{{ _('Password') }}`
- `Enter username` → `{{ _('Enter username') }}`
- `Enter admin password` → `{{ _('Enter admin password') }}`
- `Login` (button) → `{{ _('Login') }}`
- `Login failed` → `{{ _('Login failed') }}`
- `Connection error` → `{{ _('Connection error') }}`

**admin/home.html:**
- `Dashboard - API Proxy` → `<title>{{ _('Dashboard') }} - API Proxy</title>`
- `Home`, `Config`, `API Keys`, `Monitor`, `Usage Guide`, `Logout` (nav)
- `Dashboard` → `{{ _('Dashboard') }}`
- `Dark Mode` / `Light Mode` → `{{ _('Dark Mode') }}` / `{{ _('Light Mode') }}`
- `Today`, `This Week`, `This Month`, `This Year`
- `Total Requests`, `Total Tokens`, `Req/sec`, `Tokens/sec`, `Errors`, `Error Rate`
- `Active Sessions`, `Slow Requests`, `Provider Usage`, `API Key Usage`
- `No active sessions`, `No slow requests`, `No data`
- `Request Trend`
- All JS alert/confirm strings: `'Copied!'`, `'Login failed'`, etc.

**admin/config.html:**
- Same nav items as home
- `Config - API Proxy` → `<title>{{ _('Config') }} - API Proxy</title>`
- `Provider & Model Configuration` → `{{ _('Provider & Model Configuration') }}`
- `Providers`, `Models`, `Provider-Model Bindings`
- `+ Add`, `Sync`, `Sync from API`, `Syncing...`
- `Add Provider`, `Edit Provider`, `Name`, `Base URL`, `API Key`, `Active`
- `合并连续相同角色消息` → `{{ _('Merge consecutive same-role messages') }}`
- `MiniMax等要求角色交替的供应商` → `{{ _('Providers like MiniMax that require role alternation') }}`
- `Add Model`, `Edit Model`, `Model Name`, `Display Name`, `Max Tokens`, `Multimodal`
- `Save`, `Cancel`
- All modal titles, alert/confirm strings

**admin/api_keys.html:**
- Same nav items
- `API Keys - API Proxy` → `<title>{{ _('API Keys') }} - API Proxy</title>`
- `API Keys` → `{{ _('API Keys') }}`
- `Add API Key`, `Edit API Key`, `Name`, `Allowed Models`, `Leave empty to allow all models`
- `Save`, `Cancel`, `Delete`, `Copy`, `Edit`, `Search by name or key...`
- `OpenCode配置.md` → `{{ _('OpenCode Config') }}`
- Chinese copy instructions text (lines 361-367 in .py):
  ```
  `使用说明：` → `{{ _('Usage Instructions') }}`
  `在页面中粘贴上面的 API Key 进行登录` → `{{ _('Paste the API Key above to log in') }}`
  `配置 OpenCode：` → `{{ _('Configure OpenCode:') }}`
  `让智能体读取配置文档：` → `{{ _('Let the agent read the config doc:') }}`
  `API Key 和使用说明已复制!` → `{{ _('API Key and usage instructions copied!') }}`
  ```
- All alert/confirm/pagination strings

**admin/monitor.html:**
- Same nav items
- `Statistics Monitor` → `{{ _('Statistics Monitor') }}`
- `Day`, `Week`, `Month`, `Year`
- `Total Requests`, `Total Tokens`, `Errors`, `Error Rate`
- `Request Trend`, `Provider Usage`, `API Key Usage`, `Model Usage`
- `Traffic Concentration`, `Error Hotspots`, `Active Footprint`
- JS strings: `No data`, `No hotspots`, `Others`, etc.

**admin/usage.html:**
- Same nav items
- `How to Configure API Clients` → `{{ _('How to Configure API Clients') }}`
- `Basic Information`, `Proxy URL`, `API Endpoint`, `Auth Header`
- `Model Name Format`, `With Provider Prefix`, `Without Prefix`
- Section titles: `ChatGPT-Next-Web / LobeChat`, `Python (OpenAI SDK)`, etc.
- `Tips`, all tip items
- `Copy` button, `Copied!` alert

**public/opencode.html:**
- Same nav items (has extra `OpenCode Config` link)
- `OpenCode Configuration` → `{{ _('OpenCode Configuration') }}`
- `Generate opencode.json config for this proxy`
- `Enter your API Key to generate config`
- `Generate`, `Copy`, `Copied!`
- `opencode.json`, `Available Models`
- `How to use` section and its list items
- `Please enter an API Key`, `Failed to generate config`
- Chinese prompt text (line 139)

- [ ] **Step 4:** For each file, remove the corresponding `.py` file

- [ ] **Step 5:** Commit after every 2-3 files converted

---

### Task 3: Convert Dynamic Templates (with `.format()`) — 2 files

These templates use Python `.format()` with `{{`/`}}` which clash with Jinja2.

**Files:**
- `templates/user/login.py` → `templates/user/login.html` (no `.format()`, static)
- `templates/user/dashboard.py` → `templates/user/dashboard.html` (has `.format(name, api_key_id)`)
- `templates/admin/mobile.py` → `templates/admin/mobile_login.html` + `templates/admin/mobile_home.html` (2 templates in 1 file, has no `.format()`)
- `templates/public/query.py` → `templates/public/query.html` (has `.format(name, key_id)`, BUT this file also contains route logic - need to separate)

**Strategy for `.format()` templates:**
- `dashboard.py`: The `{{` and `}}` in the template are ALREADY Jinja2-escaped Python format braces. We need to:
  1. Replace `{name}` with `{{ name }}` (Jinja2 variable)
  2. The existing `{{ }}` become `{% raw %}{{ }}{% endraw %}` or just keep as-is since Jinja2 uses the same syntax
- `query.py`: Split into route (stays in routes/) + template (goes to templates/). Replace `{name}` and `{key_id}` with `{{ name }}` and `{{ key_id }}`.

- [ ] **Step 1:** Convert `dashboard.py`
  - Remove `USER_DASHBOARD_HTML = """` wrapper
  - Replace `{name}` with `{{ name }}` (in title and subtitle)
  - The existing `{{ }}` Python escapes in JS code stay as-is (they're already valid Jinja2)
  - Wrap all user-visible text in `{{ _() }}`
  - Delete `dashboard.py`

- [ ] **Step 2:** Convert `mobile.py` - split into 2 files
  - Extract `MOBILE_LOGIN_HTML` → `templates/admin/mobile_login.html`
  - Extract `MOBILE_HOME_HTML` → `templates/admin/mobile_home.html`
  - Wrap text with `{{ _() }}`
  - Delete `mobile.py`

- [ ] **Step 3:** Convert `query.py` - split route from template
  - Move HTML to `templates/public/query.html` with `{{ name }}` and `{{ key_id }}` variables
  - Keep route logic in `routes/query.py` (rename from current file or update)
  - Wrap text with `{{ _() }}`

- [ ] **Step 4:** Convert `login.py` (user) - no `.format()`, simple extraction
  - Same as Task 2 approach
  - Wrap text with `{{ _() }}`

- [ ] **Step 5:** Commit

---

### Task 4: Update Route Handlers

**Files:**
- Modify: `routes/pages.py`
- Modify: `routes/user.py`
- Create: `routes/query.py` (extract from templates/public/query.py)

- [ ] **Step 1: Update `routes/pages.py`**

Replace all `from templates.admin.xxx import XXX_PAGE_HTML` + `HTMLResponse(content=XXX_PAGE_HTML)` with:

```python
from core.i18n import render
from fastapi import Request

# In each route handler:
async def login_page(request: Request, session: Optional[str] = Cookie(None)):
    if _is_mobile(request):
        return RedirectResponse(url="/admin/m/login")
    if _check_auth(session):
        return RedirectResponse(url="/admin/home")
    html = render(request, "admin/login.html")
    return HTMLResponse(content=html)
```

Apply this pattern to ALL route handlers in pages.py. Pass `request` object to `render()`. Note: routes that currently don't receive `request` need it added as parameter.

- [ ] **Step 2: Update `routes/user.py`**

```python
# Remove old imports:
# from templates.user.login import USER_LOGIN_HTML
# from templates.user.dashboard import USER_DASHBOARD_HTML

# Add:
from core.i18n import render

# user_login_page:
async def user_login_page(request: Request):
    html = render(request, "user/login.html")
    return HTMLResponse(content=html)

# user_dashboard:
async def user_dashboard(request: Request, api_key_id: int = Depends(get_user_session)):
    ...
    html = render(request, "user/dashboard.html", name=key.name, api_key_id=api_key_id)
    return HTMLResponse(content=html)
```

- [ ] **Step 3: Create `routes/query.py` (or update templates/public/query.py)**

Extract route code from `templates/public/query.py`. Update to use Jinja2:

```python
from core.i18n import render

@router.get("/api-keys/{key_id}/query", response_class=HTMLResponse)
async def api_key_query_page(request: Request, key_id: int, ...):
    ...
    html = render(request, "public/query.html", name=key.name, key_id=key_id)
    return HTMLResponse(content=html)
```

- [ ] **Step 4: Commit

---

### Task 5: Create Translation Files

**Files:**
- Modify: `locales/en/LC_MESSAGES/messages.po`
- Modify: `locales/zh/LC_MESSAGES/messages.po`

- [ ] **Step 1:** Extract all strings using babel

```bash
pip install jinja2 babel
pybabel extract -F babel.cfg -o locales/messages.pot templates/
```

- [ ] **Step 2:** Create English .po file

Initialize with `pybabel init -i locales/messages.pot -d locales -l en` (if not already), then fill in English translations (mostly identity - same as msgid).

- [ ] **Step 3:** Create Chinese .po file

Initialize with `pybabel init -i locales/messages.pot -d locales -l zh` (if not already), then translate all strings to Chinese.

Key translations (Chinese):
```
msgid "Login" → msgstr "登录"
msgid "Username" → msgstr "用户名"
msgid "Password" → msgstr "密码"
msgid "Dashboard" → msgstr "仪表盘"
msgid "Config" → msgstr "配置"
msgid "API Keys" → msgstr "API 密钥"
msgid "Monitor" → msgstr "监控"
msgid "Usage Guide" → msgstr "使用指南"
msgid "Logout" → msgstr "退出登录"
msgid "Dark Mode" → msgstr "深色模式"
msgid "Light Mode" → msgstr "浅色模式"
msgid "Total Requests" → msgstr "总请求数"
msgid "Total Tokens" → msgstr "总 Token 数"
msgid "Errors" → msgstr "错误数"
msgid "Error Rate" → msgstr "错误率"
msgid "Providers" → msgstr "供应商"
msgid "Models" → msgstr "模型"
msgid "Save" → msgstr "保存"
msgid "Cancel" → msgstr "取消"
msgid "Delete" → msgstr "删除"
msgid "Edit" → msgstr "编辑"
msgid "Add" → msgstr "添加"
msgid "Copy" → msgstr "复制"
msgid "Copied!" → msgstr "已复制!"
msgid "No data" → msgstr "暂无数据"
msgid "No active sessions" → msgstr "无活跃会话"
msgid "Search by name or key..." → msgstr "按名称或密钥搜索..."
msgid "API Key and usage instructions copied!" → msgstr "API Key 和使用说明已复制!"
msgid "Merge consecutive same-role message" → msgstr "合并连续相同角色消息"
msgid "Providers like MiniMax that require role alternation" → msgstr "MiniMax等要求角色交替的供应商"
msgid "Active" → msgstr "启用"
msgid "Inactive" → msgstr "停用"
msgid "Today" → msgstr "今天"
msgid "This Week" → msgstr "本周"
msgid "This Month" → msgstr "本月"
msgid "This Year" → msgstr "今年"
```

- [ ] **Step 4:** Compile .mo files

```bash
pybabel compile -d locales
```

- [ ] **Step 5: Commit

---

### Task 6: Cleanup + Verification

- [ ] **Step 1:** Delete all old `.py` template files (only if the Jinja2 `.html` version works)

```bash
rm templates/admin/login.py templates/admin/home.py templates/admin/config.py
rm templates/admin/api_keys.py templates/admin/monitor.py templates/admin/usage.py
rm templates/admin/mobile.py templates/user/login.py templates/user/dashboard.py
rm templates/public/opencode.py
# Keep templates/public/query.py only if it still has route code
```

- [ ] **Step 2:** Remove old `__init__.py` imports if any reference the old `.py` templates

- [ ] **Step 3:** Verify all routes work by starting the server and visiting each page

- [ ] **Step 4:** Test language switching via the dropdown

- [ ] **Step 5:** Final commit

```bash
git add -A
git commit -m "feat(i18n): complete i18n migration with Jinja2 templates and en/zh translations"
```
