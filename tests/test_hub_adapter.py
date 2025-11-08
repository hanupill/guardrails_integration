from typing import Any, Dict
import types
import sys

from guardrails.hub_adapter import GuardrailsHubAdapter


def _install_fake_guard(result: Any = ("", True)):
    """
    Install a fake 'guardrails' module whose Guard returns 'result' from validate.
    """
    class FakeGuard:
        def __init__(self):
            self.cls = None
            self.params: Dict[str, Any] = {}

        def use(self, cls, **params):
            self.cls = cls
            self.params = params
            return self

        def validate(self, text: str):
            # Use tag param to append markers to text for clarity
            tag = self.params.get("tag")
            if isinstance(result, tuple):
                new_text = text + (f" [{tag}]" if tag else "")
                return (new_text, True)
            elif isinstance(result, dict):
                new_text = text + (f" [{tag}]" if tag else "")
                res = {"text": new_text}
                res.update(result)
                return res
            return (text, True)

    fake_module = types.ModuleType("guardrails")
    fake_module.Guard = FakeGuard
    sys.modules["guardrails"] = fake_module


def test_run_tuple_result_parses_sanitized_text_and_valid(monkeypatch):
    _install_fake_guard(result=("ignored", True))
    adapter = GuardrailsHubAdapter()
    # Force availability
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    monkeypatch.setattr(adapter, "has_validate", lambda: True)

    text, details = adapter.run(
        "hello",
        validators_config=[{"type": "regex", "scope": "both", "pattern": "hello", "tag": "HUB"}],
        scope="both"
    )
    assert text.endswith(" [HUB]")
    # details may be minimal; the adapter does not populate violations for fake guard
    assert isinstance(details, dict)


def test_run_dict_result_with_violations(monkeypatch):
    _install_fake_guard(result={"valid": False, "violations": [{"type": "test"}]})
    adapter = GuardrailsHubAdapter()
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    monkeypatch.setattr(adapter, "has_validate", lambda: True)

    text, details = adapter.run(
        "hello",
        validators_config=[{"type": "regex", "scope": "both", "pattern": "hello"}],
        scope="both"
    )
    # Text returned from dict path should be unchanged or appended
    assert isinstance(text, str)
    assert details.get("valid") in (False, True) or "violations" in details


def test_run_respects_scope(monkeypatch):
    _install_fake_guard(result=("ignored", True))
    adapter = GuardrailsHubAdapter()
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    monkeypatch.setattr(adapter, "has_validate", lambda: True)

    text, _ = adapter.run(
        "hello",
        validators_config=[
            {"type": "regex", "scope": "input", "pattern": "h", "tag": "IN"},
            {"type": "regex", "scope": "output", "pattern": "h", "tag": "OUT"},
        ],
        scope="input",
    )
    assert "IN" in text and "OUT" not in text