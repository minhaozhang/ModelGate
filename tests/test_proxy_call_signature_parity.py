"""Regression guard: proxy.py call sites must match handler signatures.

Incident (df7919c): the handle_streaming call passed log_id both positionally
and as a kwarg (plus a wait_ms kwarg the signature never had), so EVERY
streaming request raised TypeError before reaching the upstream; the
handle_normal call omitted log_id/wait_ms so waiting rows never finalized.
Unit tests mock these handlers, so signature drift is invisible to them.
This test re-checks the real call sites against the real signatures the way
Python itself would (inspect.signature.bind).
"""

import ast
import inspect
import unittest

import app.services.proxy as proxy_module
from app.services.proxy_runtime import normal as normal_runtime
from app.services.proxy_runtime import stream as stream_runtime


def _extract_calls(func_name):
    """Yield (positional_count, kwargs) for calls to func_name inside proxy_request."""
    tree = ast.parse(inspect.getsource(proxy_module))
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "proxy_request":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == func_name
                ):
                    kwargs = [k.arg for k in sub.keywords if k.arg]
                    calls.append((len(sub.args), kwargs))
    return calls


class ProxyCallSiteSignatureTests(unittest.TestCase):
    def test_streaming_call_site_binds_to_wrapper_signature(self):
        calls = _extract_calls("handle_streaming")
        self.assertTrue(calls, "proxy_request must call handle_streaming")
        sig = inspect.signature(proxy_module.handle_streaming)
        for n_pos, kwargs in calls:
            try:
                sig.bind(*[None] * n_pos, **dict.fromkeys(kwargs))
            except TypeError as exc:
                self.fail(
                    f"handle_streaming call site does not match signature: {exc}"
                )

    def test_normal_call_site_binds_to_wrapper_signature(self):
        calls = _extract_calls("handle_normal")
        self.assertTrue(calls, "proxy_request must call handle_normal")
        sig = inspect.signature(proxy_module.handle_normal)
        for n_pos, kwargs in calls:
            try:
                sig.bind(*[None] * n_pos, **dict.fromkeys(kwargs))
            except TypeError as exc:
                self.fail(
                    f"handle_normal call site does not match signature: {exc}"
                )

    def test_wrapper_signatures_cover_runtime_signatures(self):
        """Local wrappers must accept every kwarg the runtime handlers accept,
        otherwise forwarding a valid kwarg raises TypeError downstream."""
        for wrapper, runtime in (
            (proxy_module.handle_normal, normal_runtime.handle_normal),
            (proxy_module.handle_streaming, stream_runtime.handle_streaming),
        ):
            wrapper_params = set(inspect.signature(wrapper).parameters)
            runtime_params = set(inspect.signature(runtime).parameters)
            missing = runtime_params - wrapper_params
            self.assertFalse(
                missing,
                f"{wrapper.__name__} wrapper missing params vs runtime: {missing}",
            )

    def test_normal_call_site_passes_waiting_log_context(self):
        """The waiting-row promote contract: handle_normal must receive
        log_id/wait_ms so the pre-created waiting row reaches a final status."""
        calls = _extract_calls("handle_normal")
        for _, kwargs in calls:
            self.assertIn("log_id", kwargs, "handle_normal call missing log_id=")
            self.assertIn("wait_ms", kwargs, "handle_normal call missing wait_ms=")


if __name__ == "__main__":
    unittest.main()
