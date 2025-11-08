# Top of file imports
import logging
from typing import List, Dict

from .dto import CoreAgentContext
from .base_guardrail import Guardrail


class PIIGuardrail(Guardrail):
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
