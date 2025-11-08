import re
from typing import List, Dict

from agents.dto import CoreAgentContext
from .base_guardrail import Guardrail


class PIIGuardrail(Guardrail):
    """PII detection guardrail.

    Minimal stub: detects common PII with simple regex examples when no prompt provided.
    If prompt is provided, it is treated as comma-separated PII types to check.
    Does not modify input; emits detection details.
    """

    DEFAULT_TYPES = ["email", "credit_card", "ip", "url", "api_key"]

    def _detect(self, text: str, types: List[str]) -> List[Dict]:
        spans: List[Dict] = []
        if "email" in types:
            rx = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
            for m in rx.finditer(text):
                spans.append({"start": m.start(), "end": m.end(), "value": m.group(0), "type": "email"})
        if "credit_card" in types:
            rx = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
            for m in rx.finditer(text):
                spans.append({"start": m.start(), "end": m.end(), "value": m.group(0), "type": "credit_card"})
        if "phone_number" in types or "phone" in types or "phonenumber" in types:
            rx = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){1}\d{3}[-.\s]?\d{4}\b")
            for m in rx.finditer(text):
                spans.append({"start": m.start(), "end": m.end(), "value": m.group(0), "type": "phone_number"})
        if "ip" in types:
            rx = re.compile(r"\b(?:(?:\d{1,3}\.){3}\d{1,3})\b")
            for m in rx.finditer(text):
                spans.append({"start": m.start(), "end": m.end(), "value": m.group(0), "type": "ip"})
        if "url" in types:
            rx = re.compile(r"\bhttps?://[^\s]+", flags=re.IGNORECASE)
            for m in rx.finditer(text):
                spans.append({"start": m.start(), "end": m.end(), "value": m.group(0), "type": "url"})
        if "api_key" in types:
            rx = re.compile(r"sk-[A-Za-z0-9]{32}")
            for m in rx.finditer(text):
                spans.append({"start": m.start(), "end": m.end(), "value": m.group(0), "type": "api_key"})
        return spans

    def validate(self, context: CoreAgentContext, user_input: str) -> str:
        self._emit_start(context, user_input)
        # Prefer params toggles over pattern string
        params = getattr(self.config, "params", None) or {}
        selected: List[str] = []
        try:
            if isinstance(params, dict):
                if params.get("email"): selected.append("email")
                if params.get("phone_number") or params.get("phone") or params.get("phonenumber"): selected.append("phone_number")
                if params.get("credit_card"): selected.append("credit_card")
                # Allow explicit list to override
                if isinstance(params.get("pii_types"), list) and params.get("pii_types"):
                    selected = [str(t).strip().lower() for t in params["pii_types"] if str(t).strip()]
        except Exception:
            pass

        pattern = getattr(self.config, "pattern", None) or ""
        if not selected:
            selected = [t.strip().lower() for t in pattern.split(",") if t.strip()] or self.DEFAULT_TYPES

        spans = self._detect(user_input, selected)
        details = {"type": "pii", "matches": spans, "pii_types": selected, "classification": "detect_pii"}
        self._emit_end(context, user_input, user_input, details=details)
        return user_input
