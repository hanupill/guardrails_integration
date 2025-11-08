from typing import Any, Dict
import types
import sys

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _install_fake_guard(monkeypatch, result: Any = ("", True)):
    """
    Monkeypatch the 'guardrails' module used by GuardrailsHubAdapter to a fake Guard.
    'result' can be a tuple or dict; it will be returned by FakeGuard.validate.
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
            # If a tag param is passed, append it to text to help assertions
            tag = self.params.get("tag")
            if isinstance(result, tuple):
                new_text = text + (f" [{tag}]" if tag else " [sanitized]")
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

    # Ensure adapter methods report availability
    from guardrails.hub_adapter import GuardrailsHubAdapter
    monkeypatch.setattr(GuardrailsHubAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(GuardrailsHubAdapter, "has_validate", lambda self: True)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_validate_success_with_regex(monkeypatch):
    # Fake hub returns tuple, treated as valid with sanitized text
    _install_fake_guard(monkeypatch, result=("ignored", True))

    payload = {
        "text": "Hello Alice",
        "scope": "input",
        "validators": [
            {"type": "regex", "scope": "input", "pattern": "Alice"}
        ],
        "use_local_first": False
    }
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["text"].endswith(" [sanitized]")


def test_validate_violation_returns_422(monkeypatch):
    # Fake hub returns dict with violations, causing 422
    _install_fake_guard(monkeypatch, result={"valid": False, "violations": [{"code": "x"}]})

    payload = {
        "text": "Sensitive content",
        "scope": "both",
        "validators": [
            {"type": "detect_pii", "scope": "both", "hub_id": "guardrails/detect_pii"}
        ],
        "use_local_first": False
    }
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Guardrail validation failed" in detail["message"]
    assert isinstance(detail.get("violations", []), list) and len(detail["violations"]) == 1


def test_scope_filtering_applies_only_matching(monkeypatch):
    # Fake hub appends tag to text for each applied validator
    _install_fake_guard(monkeypatch, result=("ignored", True))

    payload = {
        "text": "Check scope behavior",
        "scope": "input",
        "validators": [
            {"type": "regex", "scope": "input", "pattern": "Check", "params": {"tag": "IN"}},
            {"type": "regex", "scope": "output", "pattern": "behavior", "params": {"tag": "OUT"}}
        ],
        "use_local_first": False
    }
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # Only IN tag should be appended because runtime scope is 'input'
    assert data["text"].endswith(" [IN] [sanitized]") or data["text"].endswith(" [sanitized] [IN]")
    assert "OUT" not in data["text"]