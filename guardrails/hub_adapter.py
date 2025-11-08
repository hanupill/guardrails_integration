# Module-level guarded import with diagnostics
try:
    import guardrails  # noqa: F401

    GUARDRAILS_AVAILABLE = True
except Exception as e:
    import logging, sys, importlib.util

    logging.getLogger(__name__).warning(
        "Guardrails import failed; Hub unavailable. exe=%s err=%s dateutil_spec=%s",
        sys.executable, e, importlib.util.find_spec("dateutil"),
    )
    for p in sys.path[:10]:
        logging.getLogger(__name__).warning("sys.path sample: %s", p)
    GUARDRAILS_AVAILABLE = False

import warnings

warnings.filterwarnings(
    "ignore",
    message=r"Could not obtain an event loop.*",
    module="guardrails.validator_service"
)

import logging

logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)


class GuardrailsHubAdapter:
    def __init__(self) -> None:
        self.available = GUARDRAILS_AVAILABLE

    def is_available(self) -> bool:
        return self.available

    def has_validate(self) -> bool:
        try:
            from guardrails import Guard  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, text: str, validators_config: list, scope=None) -> tuple[str, dict]:
        if not self.available:
            return text, {}

        import logging, importlib
        lg = logging.getLogger(__name__)
        lg.setLevel(logging.INFO)
        lg.info("Guardrails Hub adapter invoked; validators=%s", validators_config)

        # Ensure an asyncio event loop exists to avoid guardrails warnings
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        violations = []
        sanitized_text = text
        invalid_flags = []  # track per-validator validity booleans

        def _scope_matches(v_scope: str, runtime_scope: str) -> bool:
            v = (v_scope or "both").strip().lower()
            rs = (runtime_scope or "both").strip().lower()
            return v == "both" or v == rs

        def _resolve_hub_cls(v: dict):
            try:
                hub_mod = importlib.import_module("guardrails.hub")
            except Exception:
                hub_mod = None
            try:
                validators_mod = importlib.import_module("guardrails.validators")
            except Exception:
                validators_mod = None

            type_raw = (v.get("type") or "").strip().lower()
            hub_id = (v.get("hub_id") or "").strip().lower()

            def candidates_for(slug_or_type: str):
                s = (slug_or_type or "").strip().lower().replace("-", "_")
                last = s.split("/")[-1]
                base = last.split(":")[-1]
                parts = base.split("_")
                pascal = "".join(p.capitalize() for p in parts if p)
                cands = [pascal]
                # Built-in mappings and variants
                if base in {"regex_match", "regex"}:
                    cands[:0] = ["RegexMatch", "Regex"]
                if base in {"valid_json", "json"}:
                    cands[:0] = ["ValidJSON", "ValidJson"]
                if base in {"valid_url", "url"}:
                    cands[:0] = ["ValidURL", "ValidUrl"]
                if base in {"toxic_language"}:
                    cands.insert(0, "ToxicLanguage")
                if base in {"competitor_check"}:
                    cands.insert(0, "CompetitorCheck")
                if base in {"unusual_prompt"}:
                    cands.insert(0, "UnusualPrompt")
                if base in {"guardrails_pii"}:
                    cands.insert(0, "GuardrailsPII")
                if base in {"detect_pii"}:
                    cands.insert(0, "DetectPII")
                if base in {"pii", "contains_pii", "personal_data"}:
                    cands[:0] = ["PII", "Pii"]
                if base in {"blocklist", "blacklist", "denylist", "block_list"}:
                    cands.insert(0, "Blocklist")
                return cands

            names = candidates_for(hub_id) if hub_id else candidates_for(type_raw)
            for mod in (hub_mod, validators_mod):
                if mod:
                    for name in names:
                        cls = getattr(mod, name, None)
                        if cls:
                            return cls

            # Direct plugin import fallback (if package is present locally)
            try:
                base_slug = (hub_id or type_raw or "").strip().lower().split("/")[-1].replace("-", "_")
                plugin_mod_name = f"guardrails_grhub_{base_slug}"
                plugin_mod = importlib.import_module(plugin_mod_name)
                for name in names:
                    cls = getattr(plugin_mod, name, None)
                    if cls:
                        return cls
            except Exception:
                pass

            # Dynamic load via Guardrails Hub (requires GUARDRAILS_API_KEY)
            if hub_mod and (hub_id or type_raw):
                try:
                    loader = getattr(hub_mod, "load", None)
                    if callable(loader):
                        target = hub_id or f"guardrails/{base_slug}"
                        loaded = loader(target) or loader(f"hub://{target}")
                        if loaded:
                            return loaded
                except Exception as e:
                    lg.warning("Dynamic Hub load failed for %s: %s", (hub_id or type_raw), e)

            return None

        try:
            from guardrails import Guard
        except Exception as e:
            lg.warning("Guardrails core not available: %s", e)
            return text, {"error": str(e)}

        runtime_scope = (scope or "both")
        for v in (validators_config or []):
            if not _scope_matches(v.get("scope"), runtime_scope):
                continue

            cls = _resolve_hub_cls(v)
            if not cls:
                lg.warning(
                    "Hub validator not found or unsupported in runtime: type=%s hub_id=%s",
                    v.get("type"), v.get("hub_id")
                )
                continue

            # 1) Forward generic params + extras
            params = dict(v.get("params") or {})
            t = (v.get("type") or "").strip().lower()

            # Normalize regex pattern -> 'regex' param
            if t == "regex":
                pattern = v.get("pattern") or params.get("regex") or ""
                if not pattern:
                    continue
                params["regex"] = pattern

            params.setdefault("on_fail", (v.get("on_fail") or "exception"))

            reserved = {"type", "scope", "hub_id", "pattern", "on_fail", "params"}
            for k, val in v.items():
                if k not in reserved and k not in params:
                    params[k] = val
            try:
                guard = Guard().use(cls, **params)
                # Log the specific Hub validator being executed
                lg.info(
                    "Hub Guardrail execution: class=%s, type=%s, hub_id=%s, scope=%s",
                    getattr(cls, "__name__", str(cls)),
                    t or "(unknown)",
                    v.get("hub_id") or "(none)",
                    v.get("scope") or "both"
                )
                result = guard.validate(sanitized_text)
                # Parse sanitized text and validity
                is_valid = True
                try:
                    if isinstance(result, tuple):
                        # Common pattern: (text, is_valid, metadata?)
                        if len(result) >= 2 and isinstance(result[1], bool):
                            is_valid = result[1]
                        # Text in first item
                        if len(result) >= 1 and isinstance(result[0], str):
                            sanitized_text = result[0]
                    elif isinstance(result, dict):
                        sanitized_text = (
                                result.get("text")
                                or result.get("validated_text")
                                or result.get("output")
                                or sanitized_text
                        )
                        for key in ("valid", "is_valid", "passed", "ok", "success"):
                            if key in result:
                                is_valid = bool(result.get(key))
                                break
                    elif isinstance(result, str):
                        sanitized_text = result
                except Exception as parse_err:
                    lg.debug("Result parse issue; keeping original: %s", parse_err)
                invalid_flags.append(not bool(is_valid))
            except Exception as err:
                violations.append({
                    "type": (v.get("type") or "unknown"),
                    "scope": (v.get("scope") or "both"),
                    "params": params,
                    "error": str(err),
                })
                # Treat exceptions as invalid unless on_fail explicitly 'noop'
                invalid_flags.append(params.get("on_fail", "exception") != "noop")

        lg.info("Guardrails Hub processed; violations=%d", len(violations))
        # Removed noisy prints to keep logs clean and avoid confusing output
        return sanitized_text, {"violations": violations}
