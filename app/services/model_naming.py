"""Model-name conventions for usage statistics.

Two different model names are tracked per request:

- user level: the model the user asked for (``requested_model``), with any
  explicit ``provider/`` routing prefix stripped and ``auto`` kept as-is.
- provider level: the model name that actually went out upstream
  (``actual_model``), i.e. the upstream model name configured on the
  provider model entry.
"""

from sqlalchemy import func


def user_stats_model_name(requested_model, model):
    name = requested_model or model or ""
    if "/" in name:
        name = name.split("/", 1)[1] or name
    return name or None


def provider_stats_model_name(actual_model, model):
    return actual_model or model


def user_stats_model_expr(model_col, requested_col):
    requested = func.nullif(requested_col, "")
    base = func.coalesce(requested, model_col)
    stripped = func.nullif(func.substr(base, func.strpos(base, "/") + 1), "")
    return func.coalesce(stripped, base)


def provider_stats_model_expr(model_col, actual_col):
    return func.coalesce(func.nullif(actual_col, ""), model_col)
