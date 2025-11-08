import re
from typing import List, Dict

from agents.dto import CoreAgentContext
from .base_guardrail import Guardrail


class RegexGuardrail(Guardrail):
    """Regex-based guardrail.

    For now, performs detection only; does not modify input.
    Emits match details in the end event.
    """

    def validate(self, context: CoreAgentContext, user_input: str) -> str:
        self._emit_start(context, user_input)
        matches: List[Dict] = []
        pattern = getattr(self.config, "pattern", None) or ""
        if pattern:
            try:
                rx = re.compile(pattern, flags=re.IGNORECASE | re.MULTILINE)
                for m in rx.finditer(user_input):
                    matches.append({"start": m.start(), "end": m.end(), "value": m.group(0)})
            except re.error:
                pass
        self._emit_end(context, user_input, user_input, details={"type": "regex", "matches": matches})
        return user_input
