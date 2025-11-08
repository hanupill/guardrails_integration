from typing import List
from .dto import AgentGuardrail, GuardrailsScope
from .hub_adapter import GuardrailsHubAdapter

class GuardrailsApiService:
    def validate(self, agent_context, guardrails: List[AgentGuardrail], text: str, scope: GuardrailsScope) -> str:
        # First apply local adapters via GuardrailsService (Regex, Blocklist, PII, Hub-mapped)
        from .guardrails_service import GuardrailsService
        service = GuardrailsService()

        # Normalize scope
        sc_enum = scope if hasattr(scope, "value") else GuardrailsScope[str(scope).strip().upper()]
        processed_text = service.validate(agent_context, guardrails, text or "", sc_enum)

        # Then, optionally apply Hub validators if available, based on guardrail config
        from .hub_adapter import GuardrailsHubAdapter
        hub = GuardrailsHubAdapter()
        import logging
        logging.getLogger(__name__).info(
            "GuardrailsApiService: hub availability is_available=%s has_validate=%s",
            hub.is_available(), hub.has_validate()
        )
        if not hub.is_available() or not hub.has_validate():
            return processed_text

        validators_config = []
        scope_str = (sc_enum.value if hasattr(sc_enum, "value") else str(sc_enum)).lower()

        for gr in guardrails or []:
            t_raw = getattr(gr, "type", "")
            t_lower = (t_raw.value.lower() if hasattr(t_raw, "value") else str(t_raw).strip().lower())
            if "." in t_lower:
                t_lower = t_lower.split(".")[-1]

            sc_val = getattr(gr, "scope", "both")
            sc_str = (sc_val.value if hasattr(sc_val, "value") else str(sc_val)).lower()

            v = {"type": t_lower, "scope": sc_str}
            hub_id = getattr(gr, "hub_id", None)
            if hub_id:
                v["hub_id"] = hub_id

            pattern = getattr(gr, "pattern", None)
            if pattern and t_lower == "regex":
                v["pattern"] = pattern

            on_fail = getattr(gr, "on_fail", None)
            if on_fail:
                v["on_fail"] = on_fail

            params = getattr(gr, "params", None)
            if isinstance(params, dict):
                for k, val in params.items():
                    v[k] = val

            validators_config.append(v)

        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            "GuardrailsApiService: prepared hub validators count=%d scope=%s hub_ids=%s",
            len(validators_config),
            scope_str,
            [v.get("hub_id") for v in validators_config if v.get("hub_id")]
        )

        logger.info("GuardrailsApiService: invoking hub.run with %d validators", len(validators_config))
        sanitized_text, _details = hub.run(text or "", validators_config=validators_config, scope=scope_str)
        logger.info(
            "GuardrailsApiService: hub.run returned details keys=%s",
            list((_details or {}).keys())
        )

        # If hub reports violations, raise to caller with details
        is_valid = True
        try:
            if isinstance(_details, dict):
                is_valid = bool(_details.get("valid", True))
                violations = _details.get("violations", [])
                if isinstance(violations, list) and len(violations) > 0:
                    is_valid = False
        except Exception:
            is_valid = True
        if not is_valid:
            raise ValueError("Guardrail validation failed by Hub", _details)

        return sanitized_text