# Top of file imports
import logging
from typing import Dict, Any
from .dto import CoreAgentContext
from .base_guardrail import Guardrail

HUB_ID_MAP = {
    "regex_match": "guardrails/regex_match",
    "valid_json": "guardrails/valid_json",
    "valid_url": "guardrails/valid_url",    
    "unusual_prompt": "guardrails/unusual_prompt",
    "detect_pii": "guardrails/detect_pii"
}


def _infer_type_from_hub_id(hub_id: str) -> str:
    base = (hub_id or "").strip().lower().split("/")[-1]
    if not base:
        return "unknown"
    if "regex_match" in base:
        return "regex_match"
    if "json" in base:
        return "valid_json"
    if "url" in base:
        return "valid_url"
    if "unusual_prompt" in base:
        return "unusual_prompt"
    if "detect_pii" in base:
        return "detect_pii"
    if any(term in base for term in ["blocklist", "blacklist", "denylist"]):
        return "blocklist"
    return base


class HubGuardrail(Guardrail):
    def validate(self, context: CoreAgentContext, user_input: str) -> str:
        self._emit_start(context, user_input)
        hub_id = getattr(self.config, "hub_id", None) or ""
        on_fail = getattr(self.config, "on_fail", None) or "exception"
        pattern = getattr(self.config, "pattern", None) or ""
        params = getattr(self.config, "params", None) or {}
        scope_str = (
            self.config.scope.value if hasattr(self.config.scope, "value") else str(self.config.scope or "both")
        ).strip().lower()

        details: Dict[str, Any] = {
            "type": "hub",
            "hub_id": hub_id,
            "scope": scope_str,
            "on_fail": on_fail,
            "params": params,
            "violations": [],
        }

        try:
            from .hub_adapter import GuardrailsHubAdapter
            hub = GuardrailsHubAdapter()

            if not hub.is_available():
                details["error"] = "guardrails_library_unavailable"
                self._emit_end(context, user_input, user_input, details=details)
                return user_input

            validator_type = _infer_type_from_hub_id(hub_id)
            # Log which guardrail is running
            logging.getLogger(__name__).info(
                "Executing HubGuardrail: validator=%s, hub_id=%s, scope=%s, on_fail=%s",
                validator_type, hub_id or "(none)", scope_str, on_fail
            )
            # Fallback to configured type when no hub_id provided
            if not hub_id:
                t_raw = getattr(self.config, "type", None)
                t_lower = (t_raw.value if hasattr(t_raw, "value") else str(t_raw or "")).strip().lower()
                if "." in t_lower:
                    t_lower = t_lower.split(".")[-1]
                if t_lower in {"json"}:
                    validator_type = "valid_json"
                elif t_lower in {"url"}:
                    validator_type = "valid_url"
                elif t_lower in {"competitor_check"}:
                    validator_type = "competitor_check"
                elif t_lower in {"regex_match"}:
                    validator_type = "regex_match"
                elif t_lower in {"unusual_prompt"}:
                    validator_type = "unusual_prompt"
                elif t_lower in {"detect_pii"}:
                    validator_type = "detect_pii"
                elif t_lower in {"regex_match", "pii", "blocklist", "valid_json", "valid_url", "competitor_check"}:
                    validator_type = t_lower

            validator_cfg: Dict[str, Any] = {
                **({"hub_id": hub_id or HUB_ID_MAP.get(
                    validator_type)} if hub_id or validator_type in HUB_ID_MAP else {}),
                "type": validator_type,
                "scope": scope_str,
                "on_fail": on_fail,
                **({"pattern": pattern} if validator_type == "regex" else {}),
                **(params or {}),
            }
            logging.getLogger(__name__).info(
                "HubGuardrail: prepared validator_cfg summary type=%s hub_id=%s scope=%s on_fail=%s keys=%s",
                validator_cfg.get("type"),
                validator_cfg.get("hub_id") or "(none)",
                validator_cfg.get("scope"),
                validator_cfg.get("on_fail"),
                sorted([k for k in validator_cfg.keys() if k not in {"type","scope","hub_id","on_fail"}])
            )
            _, hub_details = hub.run(user_input, [validator_cfg], scope=scope_str)

            if isinstance(hub_details, dict):
                for k, v in hub_details.items():
                    details[k] = v
                logging.getLogger(__name__).info(
                    "HubGuardrail: result valid=%s violations_count=%d",
                    bool(details.get("valid", True)),
                    len(details.get("violations", []) or [])
                )
        except Exception as e:
            details["error"] = f"hub_integration_error: {e}"

        self._emit_end(context, user_input, user_input, details=details)
        return user_input
