# Top of file imports
import logging

from typing import List

from .dto import AgentGuardrail, GuardrailsScope
from .guardrail_factory import get_default_factory


class GuardrailsService:
    def validate(self, agent_context, guardrails: List[AgentGuardrail], user_input: str, scope: GuardrailsScope) -> str:
        """Validate text against guardrails filtered by the provided scope.

        Runs only those guardrails whose `scope` matches the provided `scope` or is BOTH.
        Returns (potentially modified) text.
        """
        text = user_input
        for gr in guardrails or []:
            gr_scope = getattr(gr, "scope", GuardrailsScope.BOTH)
            if gr_scope in (scope, GuardrailsScope.BOTH):
                instance = self._create_guardrail(gr)
                text = instance.validate(agent_context, text)
        return text
