# Top of file imports
import logging
from typing import Optional

# Module imports and event stubs
from .dto import AgentGuardrail, CoreAgentContext
try:
    from events.agent_event_spec import AgentEventSpec
    from events.event_util import EventUtil
except Exception:
    class AgentEventSpec:
        class EventType:
            on_guardrail_validate_start = "on_guardrail_validate_start"
            on_guardrail_validate_end = "on_guardrail_validate_end"

    class EventUtil:
        @staticmethod
        def emit(event_type, session_id=None, event_params=None):
            # No-op when events system is not present
            return

class Guardrail:
    def __init__(self, config: AgentGuardrail) -> None:
        self.config = config

    def _emit_start(self, context: CoreAgentContext, user_input: str) -> None:
        EventUtil.emit(
            AgentEventSpec.EventType.on_guardrail_validate_start,
            session_id=context.session_id,
            event_params={
                "agent_id": context.agent_metadata.id if getattr(context, "agent_metadata", None) else None,
                "guardrail": {
                    "id": getattr(self.config, "id", None),
                    "type": (self.config.type.value if hasattr(self.config.type, "value") else str(self.config.type)),
                    "scope": (
                        self.config.scope.value if hasattr(self.config.scope, "value") else str(self.config.scope)),
                    "pattern": getattr(self.config, "pattern", None),
                },
                "input": user_input,
            },
        )

    def _emit_end(self, context: CoreAgentContext, original_input: str, result_text: str,
                  details: Optional[dict] = None) -> None:
        EventUtil.emit(
            AgentEventSpec.EventType.on_guardrail_validate_end,
            session_id=context.session_id,
            event_params={
                "agent_id": context.agent_metadata.id if getattr(context, "agent_metadata", None) else None,
                "guardrail": {
                    "id": getattr(self.config, "id", None),
                    "type": (self.config.type.value if hasattr(self.config.type, "value") else str(self.config.type)),
                    "scope": (
                        self.config.scope.value if hasattr(self.config.scope, "value") else str(self.config.scope)),
                    "pattern": getattr(self.config, "pattern", None),
                },
                "input": original_input,
                "result": result_text,
                "details": details or {},
            },
        )

    def validate(self, context: CoreAgentContext, user_input: str) -> str:
        """Template method. Default: pass-through with events.

        Args:
            context: CoreAgentContext
            user_input: text to validate
        Returns:
            Possibly modified text (default unchanged)
        """
        self._emit_start(context, user_input)
        result = user_input
        self._emit_end(context, user_input, result, details={"action": "none"})
        return result

# Provide GuardrailConfig for modules that import it
GuardrailConfig = AgentGuardrail
