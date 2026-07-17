# Cleanup Obsolete Test Report

## Summary

Removed `test_model_routing_matrix_has_no_bulk_api_key_configuration` from
`tests/test_admin_ui_static.py` because its core assertions conflict with the
new model-API-key binding feature (commits `f1a0b60`, `8472cab`).

## Original Test Location

`tests/test_admin_ui_static.py`, method `AdminUiStaticTests.test_model_routing_matrix_has_no_bulk_api_key_configuration`
(added by commit `7781951` when bulk-key-config was originally removed).

## Exact Assertions Made

The test asserted six negative facts across two source files:

```python
def test_model_routing_matrix_has_no_bulk_api_key_configuration(self):
    html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
    route = (ROOT / "app" / "routes" / "models.py").read_text(encoding="utf-8")

    self.assertNotIn('id="model-keys-modal"', html)            # 1. OLD modal id
    self.assertNotIn("openModelKeys", html)                     # 2. OLD helper name
    self.assertNotIn("openProviderModelKeys", html)             # 3. OLD bulk helper name
    self.assertNotIn("配置 Key", html)                          # 4. OLD button label
    self.assertNotIn("/models/{model_id}/api-keys", route)      # 5. ⚠️ NOW FAILS
    self.assertNotIn("ModelApiKeysUpdate", route)               # 6. ⚠️ NOW FAILS
```

## Why They Conflict With The New Feature

The new model-API-key binding feature (spec:
`docs/superpowers/specs/2026-07-17-model-api-key-binding-modal-design.md`)
deliberately reintroduces model-level API key configuration, but using a
different (non-bulk) pattern: **one model → many keys modal**, not the old
**many-models → many-keys matrix**.

### Assertions 5 and 6 are now directly violated

`app/routes/models.py` contains exactly what the test forbids:

| Line | Content | Conflicts With Assertion |
|------|---------|--------------------------|
| 68   | `class ModelApiKeysUpdate(BaseModel):` | #6 |
| 218  | `@router.get("/models/{model_id}/api-keys")` | #5 |
| 270  | `@router.put("/models/{model_id}/api-keys")` | #5 |
| 273  | `data: ModelApiKeysUpdate,` | #6 |

### Assertions 1–4 are obsolete but not violated

The new feature deliberately uses a **different naming scheme**:
- New modal id is `model-apikeys-modal` (assertion #1 forbid the OLD name `model-keys-modal`).
- New helper is `openModelApiKeysModal` (assertion #2 forbid the OLD name `openModelKeys`).
- The new feature does not introduce `openProviderModelKeys` (assertion #3 still passes).
- The new feature does not use the OLD label `配置 Key` (assertion #4 still passes).

These four are essentially "naming guards" for the removed UI and are no longer
worth keeping: they protect against a UI nobody would naturally reintroduce, and
they no longer describe a coherent feature boundary.

## Resolution: Full Removal

The test method's stated purpose ("no bulk API key configuration for models") is
now fundamentally false — model-level API key configuration is intentionally
present. Because two of six assertions now fail and the remaining four are
vestigial naming guards, the cleanest action is to remove the entire method.

The new feature's behavior is positively covered by three other tests in the
same file:

- `test_model_apikeys_modal_has_required_dom_and_handlers` (line 235)
- `test_model_apikeys_js_uses_set_semantics_and_correct_endpoints` (line 251)
- `test_model_table_row_has_apikeys_button` (line 266)

These tests verify the new modal's DOM, JS handlers, endpoints, set semantics,
and table-row button — full positive coverage of the new feature.

## What I Removed

One method (10 lines) from `tests/test_admin_ui_static.py`:

```python
def test_model_routing_matrix_has_no_bulk_api_key_configuration(self):
    html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
    route = (ROOT / "app" / "routes" / "models.py").read_text(encoding="utf-8")

    self.assertNotIn('id="model-keys-modal"', html)
    self.assertNotIn("openModelKeys", html)
    self.assertNotIn("openProviderModelKeys", html)
    self.assertNotIn("配置 Key", html)
    self.assertNotIn("/models/{model_id}/api-keys", route)
    self.assertNotIn("ModelApiKeysUpdate", route)
```

No other code or test changes.

## Test Command Output

Command: `python -m unittest tests.test_admin_ui_static -v`

### Before removal (pre-existing state on `dev` branch)

```
Ran 42 tests in 0.024s
FAILED (failures=3)
```

The 3 failures were:
1. `test_auto_model_picker_uses_compact_modal_not_tall_multiselect` (pre-existing, unrelated)
2. `test_model_routing_matrix_uses_compact_responsive_layout` (pre-existing, unrelated)
3. `test_model_routing_matrix_has_no_bulk_api_key_configuration` (the obsolete test)

### After removal

```
Ran 41 tests in 0.025s
FAILED (failures=2)
```

Remaining 2 failures are the same pre-existing failures from before; they are
unrelated to API-key configuration:

1. `test_auto_model_picker_uses_compact_modal_not_tall_multiselect`
   — fails on missing `id="auto-model-summary"`
2. `test_model_routing_matrix_uses_compact_responsive_layout`
   — fails on missing `.routing-priority-input { width: 4rem; ... }` CSS rule

These are caused by config.html refactors in the feature commits
(`f1a0b60`, `8472cab`) and are out of scope for this cleanup task.

### Delta

- Tests removed: 1
- Failures reduced: 1 (exactly the obsolete test)
- New failures introduced: 0
- New passes introduced: 0

The cleanup successfully removed the obsolete assertion with zero side effects
on the rest of the suite.
