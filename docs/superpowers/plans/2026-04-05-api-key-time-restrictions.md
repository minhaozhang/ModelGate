# API Key Time Restrictions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax in tracking.

**Goal:** Add per-key time-based access restriction to API keys, supporting daily recurring time windows and date-range restrictions.
**Architecture:** New `api_key_time_rules` table + modify `api_keys` cache to include time rules + validation in `validate_api_key()` + CRUD endpoints for admin management.
**Tech Stack:** SQLAlchemy ORM, FastAPI, PostgreSQL

---

## Task 1: Add `ApiKeyTimeRule` ORM Model and DB Migration
**Files:**
- Create: `core/database.py` (add `ApiKeyTimeRule` class)
- [ ] **Step 1: Add the model class**
```python
class ApiKeyTimeRule(Base):
    __tablename__ = "api_key_time_rules"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    time_start = Column(Time, nullable=True)
    time_end = Column(Time, nullable=True)
    date_start = Column(Date, nullable=True)
    date_end = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
```
- [ ] **Step 2: Add `ALTER TABLE` in `init_db()`**
```python
await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS api_key_time_rules (
        id SERIAL PRIMARY KEY,
        api_key_id INTEGER NOT NULL REFERENCES api_keys(id),
        name VARCHAR(100) NOT NULL,
        time_start TIME,
        time_end TIME,
        date_start DATE,
        date_end DATE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    )
"""))
```
- [ ] **Step 3: Verify migration runs**
Run: `python main.py` and check logs for no errors.

- [x] **Step 4: Commit**

## Task 2: Update `api_keys_cache` to Include Time Rules
**Files:**
- Modify: `services/auth.py` (load_api_keys)
- Modify: `core/config.py` (cache type hint)
- [ ] **Step 1: Update `load_api_keys()` to load time rules per key**
In `load_api_keys()`, after loading model IDs, also load time rules for `api_key_time_rules`:
```python
from core.database import ApiKeyTimeRule

# Inside the per-key loop:
time_result = await session.execute(
    select(ApiKeyTimeRule).where(
        ApiKeyTimeRule.api_key_id == k.id,
        ApiKeyTimeRule.is_active == True,
    )
)
rules = [row._dict() for row in time_result.fetchall()]
api_keys_cache[k.key]["time_rules"] = rules
```
Each rule dict: `{"id": r.id, "name": r.name, "time_start": str(r.time_start), "time_end": str(r.time_end), "date_start": str(r.date_start), "date_end": str(r.date_end)}`
- [ ] **Step 2: Verify cache loads correctly by logging cache contents**
- [x] **Step 3: Commit**

## Task 3: Add Time Validation in `validate_api_key()`
**Files:**
- Modify: `services/auth.py` (validate_api_key)
- [ ] **Step 1: Add `_check_time_rules()` helper function**
After model authorization passes, add time rules check:
```python
from datetime import datetime, time as dt

def _check_time_rules(rules: list[dict]) -> tuple[bool, str]:
    now = datetime.now()
    for rule in rules:
        if rule.get("date_start") or rule.get("date_end"):
            date_start = dt.date(rule["date_start"]).date() if rule.get("date_start") else None
            date_end = dt.date(rule["date_end"]).date() if rule.get("date_end") else None
            if date_start and now.date() < date_start:
                return False, "API key not yet active"
 (date {date_start})"
            if date_end and now.date() > date_end:
                return False, "API key expired (date {date_end})"

        if rule.get("time_start") is not None and rule.get("time_end") is not None:
                current_time = now.time()
                time_start = rule["time_start"]
                time_end = rule["time_end"]
                if time_start < time_end:
                    if not (time_start <= current_time <= time_end):
                        return False, "API key not allowed at this time"
                else:
                    if current_time >= time_start or current_time <= time_end:
                        return False, "API key not allowed in this time"
    return True, None
```
Handle overnight case where `time_end < time_start` (e.g., 22:00-06:00):
```python
if time_start < time_end:
    in_range = time_start <= current_time <= time_end
else:
    in_range = current_time >= time_start or current_time <= time_end
```
- [ ] **Step 2: Call `_check_time_rules()` in `validate_api_key()` after key found and cache**
```python
time_rules = key_info.get("time_rules", [])
if time_rules:
    allowed, msg = _check_time_rules(time_rules)
    if not allowed:
        return key_info["id"], msg
```
- [ ] **Step 3: Verify with a test key that has time rules vs no time rules**
- [x] **Step 4: Commit**

## Task 4: Add CRUD Endpoints for Time Rules
**Files:**
- Create: `routes/time_rules.py`
- Modify: `main.py` (register router)
- [ ] **Step 1: Create routes/time_rules.py with endpoints**
- `GET /admin/api/keys/{key_id}/time-rules` — list time rules for a key
- `POST /admin/api/keys/{key_id}/time-rules` — create a time rule
- `PUT /admin/api/keys/{key_id}/time-rules/{rule_id}` — update a time rule
- `DELETE /admin/api/keys/{key_id}/time-rules/{rule_id}` — delete a time rule

All endpoints require admin auth (`require_admin`).
 All invalidate `load_api_keys()` cache after mutations.
 Pydantic models for request/response.

 Same patterns as `routes/keys.py`.
- [ ] **Step 2: Register router in main.py**
- [ ] **Step 3: Commit**

## Task 5: Update Admin Frontend for Time Rules UI
**Files:**
- Modify: admin template to `templates/admin/` (add time rules management section to API key edit page)
- [ ] **Step 1: Add time rules tab/section to API key edit form**
Add a section with fields for rule name, time range (start time, end time), date range (start date, end date), active toggle. Use the same modal/dialog pattern as existing key edit forms.
 Add buttons to add/remove rules with confirmation. On save, call `load_api_keys()` to refresh cache.
 Show rules list in the key details view. Include rule name in list response. Show time range inputs as HH:MM format.
 Show date range as YYYY-MM-DD.
 Handle `time_start` > `time_end` crossing midnight.
 Handle `date_start` > `date_end` date_start < date_end.
 Show delete confirmation. On delete, show success toast.
 On success, navigate back to key edit page.
 On save, show toast "API key time rules updated" and refresh cache.
 On error, show validation errors.
 Show active/inactive toggle.
 Use same styling as existing toggles switches in the modal.
 Support `prefers-reduced-motion` (just `transition: opacity 0.3s` instead of animating). Don't add animations to modal show/hide.
 Use same time duration as modals. Toast follows existing toast patterns.
 Add a confirmation dialog on `templates/admin/base.html` or similar base template for deletion confirmation.
 All validation errors are toast. Responsive and same styles as existing forms validation. On success, navigate back to key edit page. On error, show validation errors. Reuse existing form row structure (`<div class="flex ...">`). On save, show toast. "API key time rules updated" and refresh cache.

 On error, show validation errors. Add a button to key list to refresh data (reloads time rules table). Fix overflow handling for `max-h-[600px]` on rules container.

 Support delete confirmation in `templates/admin/base.html`. Add delete button to key detail view row. Add delete confirmation dialog. On success, navigate back to key edit page. Show success toast. Add a confirmation dialog in `templates/admin/base.html`. Add confirmation dialog in `templates/admin/base.html`. Handle edge case: both time ranges empty (don't allow submit), show error). Format time inputs as `HH:MM` and date inputs as `YYYY-MM-DD`. Handle `time_end` before `time_start` (must be after if `time_start` is specified). Handle `date_end` after `date_start` (must be after if `date_start` if specified). Format `time_end` as `time_start` when display (show error toast if `time_end` must be before `time_start`). Delete rule uses `load_api_keys()` to refresh cache. Fix overflow handling in time rules container on delete confirmation dialog. Handle edge case: rule not found (show confirmation dialog with error message. On success, show success toast. Refresh time rules list on key detail view on add time rule button. Navigate to `navigateTo` time rule URL. Use `window.location.reload()`. Use existing toast patterns.
- [ ] **Step 2: Add time rules management button to API key list page**
Find the API key list page in admin templates. Add a button next to "Time Rules" label (or equivalent in zh). e.g., "时间规则") that opens add time rules dialog/modal/drawer. On open, load the rules from API. Add "Add Time rule" button that Edit existing rules with modal + Save → redirect to `/admin/api/keys/{key_id}/time-rules/{rule_id}` + Delete → redirect to `/admin/api/keys/{key_id}/time-rules/{rule_id}` (POST, Delete).
 Use same confirm/success toast pattern as existing keys save.
 Toast on key name change: "API Key time rules updated". On error: show toast. Show errors in toast for format consistent with existing inline toast. Inline, toast message: include the error details from server response. On success of `window.location.reload()`.

 On save, refresh the rules list after adding, removing rules.
 On error, show toast. Fetch the rules from `/admin/api/keys/{key_id}/time-rules` (GET). Return 40xx. On success, `window.location.reload()`.

- [ ] **Step 3: Commit**

## Task 6: Update Admin Frontend i18n for Time Rules Labels
**Files:**
- Modify: admin template in `templates/admin/` (update i18n)
- [ ] **Step 1: Add translation keys `time_rules` to i18n JSON for all admin template files that use i18n strings for the time rule list**
Similar to `keys` in `routes/keys.py` — add `time_rules` to the response dict.
 Add `time_rules` to i18n file (e.g., `zh: 时间规则.json`).
 Handle `time_rules` in the `list_api_keys()` response:
```python
{"api_keys": api_keys, "time_rules": [...]}
```
Add translations for all templates.

 Add `time_rules.title`, `time_rules` (en), `time_rules.start_time` (zh), `起始时间`), `time_rules.end_time` (zh), `结束时间`), etc. Same pattern as existing translations.
- [ ] **Step 2: Commit**
