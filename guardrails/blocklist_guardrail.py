import logging
import re
from typing import List, Dict

from agents.dto import CoreAgentContext
from .base_guardrail import Guardrail


def _parse_words(prompt: str) -> List[str]:
    return [w.strip().lower() for w in re.split(r"[,\n]", prompt or "") if w.strip()]


class BlocklistGuardrail(Guardrail):
    """Blocklist-based guardrail.

    For now, performs detection only; does not modify input.
    Emits match details in the end event.
    """

    def validate(self, context: CoreAgentContext, user_input: str) -> str:
        self._emit_start(context, user_input)
        words = _parse_words(getattr(self.config, "pattern", ""))
        scope_str = (
            self.config.scope.value if hasattr(self.config.scope, "value") else str(self.config.scope or "both")
        ).strip().lower()
        # Log which guardrail is running
        logging.getLogger(__name__).info(
            "Executing BlocklistGuardrail: words=%d, scope=%s", len(words), scope_str
        )
        matches: List[Dict] = []
        lower_text = user_input.lower()
        for w in words:
            # Word boundary search
            pattern = re.compile(rf"\b{re.escape(w)}\b", flags=re.IGNORECASE)
            for m in pattern.finditer(user_input):
                matches.append({"start": m.start(), "end": m.end(), "value": m.group(0)})
            # Fallback substring search
            if w in lower_text and not any(s["value"].lower() == w for s in matches):
                idx = lower_text.find(w)
                matches.append({"start": idx, "end": idx + len(w), "value": user_input[idx: idx + len(w)]})
        self._emit_end(context, user_input, user_input, details={"type": "blocklist", "matches": matches})
        return user_input
