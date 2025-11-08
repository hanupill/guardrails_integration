# Module-level guarded import with diagnostics
try:
    import guardrails  # noqa: F401

    import logging, os, sys, importlib.util
    lg = logging.getLogger(__name__)

    # Log where 'guardrails' came from
    lg.info("HubAdapter: guardrails module loaded from: %s", getattr(guardrails, "__file__", "(unknown)"))

    # If local integration package is shadowing the external core, attempt site-packages fallback
    loaded_path = str(getattr(guardrails, "__file__", "") or "")
    if "guardrails_integration" in loaded_path.replace("/", "\\"):
        candidate_init = os.path.join(sys.prefix, "Lib", "site-packages", "guardrails", "__init__.py")
        if os.path.exists(candidate_init):
            lg.info("HubAdapter: attempting external guardrails from site-packages: %s", candidate_init)
            spec = importlib.util.spec_from_file_location("guardrails", candidate_init)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.modules["guardrails"] = mod
            guardrails = mod
            lg.info("HubAdapter: switched guardrails to: %s", getattr(guardrails, "__file__", "(unknown)"))

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

    # FIX: make `run` a method of the outer class (remove the nested class)
    def run(self, text: str, validators_config: list, scope=None) -> tuple[str, dict]:
        import logging, importlib
        lg = logging.getLogger(__name__)
        lg.setLevel(logging.INFO)
        lg.info("HubAdapter: input text=%s", text)
        logging.getLogger("gr_integration.app").info("[hub] adapter received text=%r scope=%s", text, (scope or "both"))
        lg.info("Guardrails Hub adapter invoked; validators=%s", validators_config)

        if not self.available:
            return text, {}

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
                return [
                    f"guardrails.validators.{base}",
                    f"guardrails.hub.{base}",
                    base,
                ]

            names = candidates_for(hub_id) if hub_id else candidates_for(type_raw)
            for mod in (hub_mod, validators_mod):
                if mod:
                    for name in names:
                        cls = getattr(mod, name, None)
                        if cls:
                            lg.info(
                                "HubAdapter: resolved class=%s from module=%s for type=%s hub_id=%s",
                                getattr(cls, "__name__", str(cls)),
                                getattr(mod, "__name__", "(unknown)"),
                                type_raw or "(none)",
                                hub_id or "(none)"
                            )
                            return cls

            # Direct plugin import fallback (if package is present locally)
            try:
                base_slug = (hub_id or type_raw or "").strip().lower().split("/")[-1].replace("-", "_")
                plugin_mod_name = f"guardrails_grhub_{base_slug}"
                plugin_mod = importlib.import_module(plugin_mod_name)
                for name in names:
                    cls = getattr(plugin_mod, name, None)
                    if cls:
                        lg.info(
                            "HubAdapter: resolved class=%s from plugin=%s for type=%s hub_id=%s",
                            getattr(cls, "__name__", str(cls)),
                            plugin_mod_name,
                            type_raw or "(none)",
                            hub_id or "(none)"
                        )
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
                            lg.info(
                                "HubAdapter: resolved via dynamic hub.load target=%s class=%s",
                                target,
                                getattr(loaded, "__name__", str(loaded))
                            )
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
            params = dict(v.get("params") or {})
            t = (v.get("type") or "").strip().lower()
            hub_id = (v.get("hub_id") or "").strip().lower()

            # Support regex by type OR hub_id suffix
            if t in {"regex", "regex_match"} or hub_id.endswith(("regex_match", "/regex", "regex")):
                pattern = v.get("pattern")  or v.get("Pattern") or params.get("pattern") or params.get("regex") or ""
                if not pattern:
                    lg.warning("Regex validator missing 'pattern'; skipping. type=%s hub_id=%s", t, hub_id or "(none)")
                    invalid_flags.append(True)
                    violations.append({
                        "type": (v.get("type") or "unknown"),
                        "scope": (v.get("scope") or "both"),
                        "params": {"on_fail": params.get("on_fail")},
                        "error": "validator_missing_pattern",
                    })
                    continue
                # Hub expects 'pattern'
                params["pattern"] = pattern

            params.setdefault("on_fail", (v.get("on_fail") or "exception"))

            reserved = {"type", "scope", "hub_id", "pattern", "on_fail", "params"}
            for k, val in v.items():
                if k not in reserved and k not in params:
                    params[k] = val

            # NEW: resolve target via class or hub_id/type fallback
            target = cls or (v.get("hub_id") or v.get("type"))
            if not target:
                lg.warning("Hub validator not found: type=%s hub_id=%s", v.get("type"), v.get("hub_id"))
                violations.append({
                    "type": (v.get("type") or "unknown"),
                    "scope": (v.get("scope") or "both"),
                    "params": params,
                    "error": "validator_not_found",
                })
                invalid_flags.append(True)
                continue

            # Only handle local fallback for regex; allow Guard().use for other Hub validators
            if cls is None and isinstance(target, str) and target.startswith("guardrails/"):
                if t in {"regex", "regex_match"} or hub_id.endswith(("regex_match", "/regex", "regex")):
                    import re
                    pattern = params.get("pattern") or ""
                    try:
                        matched = bool(re.search(pattern, sanitized_text))
                    except Exception as re_err:
                        violations.append({
                            "type": (v.get("type") or "unknown"),
                            "scope": (v.get("scope") or "both"),
                            "params": {"on_fail": params.get("on_fail")},
                            "error": f"validator_regex_compile_error: {re_err}",
                        })
                        invalid_flags.append(True)
                        continue
                    is_valid = bool(matched)
                    invalid_flags.append(not is_valid)
                    if not is_valid:
                        violations.append({
                            "type": (v.get("type") or "unknown"),
                            "scope": (v.get("scope") or "both"),
                            "params": {"on_fail": params.get("on_fail")},
                            "error": "validator_failed",
                        })
                    lg.info("Local regex fallback executed; pattern=%r matched=%s", pattern, matched)
                    continue
            try:
                guard = Guard().use(target, **params)
                lg.info(
                    "Hub Guardrail execution: target=%r, resolved_class=%s, type=%s, hub_id=%s, scope=%s",
                    target,
                    getattr(cls, "__name__", None),
                    t or "(unknown)",
                    v.get("hub_id") or "(none)",
                    v.get("scope") or "both"
                )
                lg.info("Hub Guardrail params keys=%s", sorted(list(params.keys())))
                logging.getLogger("gr_integration.app").info(
                    "[hub] validator params hub_id=%s type=%s scope=%s pattern=%r on_fail=%s",
                    v.get("hub_id") or "(none)", t or "(unknown)", v.get("scope") or "both",
                    params.get("pattern"), params.get("on_fail")
                )
                logging.getLogger("gr_integration.app").info(
                    "[hub] validator input text=%r", sanitized_text
                )
                result = guard.validate(sanitized_text)
                # Parse sanitized text and validity
                is_valid = True
                try:
                    if isinstance(result, tuple):
                        if len(result) >= 2 and isinstance(result[1], bool):
                            is_valid = result[1]
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
                if not bool(is_valid):
                    violations.append({
                        "type": (v.get("type") or "unknown"),
                        "scope": (v.get("scope") or "both"),
                        "params": {"on_fail": params.get("on_fail")},
                        "error": "validator_failed",
                    })
            except Exception as err:
                violations.append({
                    "type": (v.get("type") or "unknown"),
                    "scope": (v.get("scope") or "both"),
                    "params": params,
                    "error": str(err),
                })
                invalid_flags.append(params.get("on_fail", "exception") != "noop")

        lg.info("Guardrails Hub processed; violations=%d invalids=%d", len(violations), sum(1 for f in invalid_flags if f))
        return sanitized_text, {"valid": (not any(invalid_flags)), "violations": violations}
