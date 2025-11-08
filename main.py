# module imports and logger
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import logging
from fastapi import Query
import uuid

# Load environment variables (optional)
load_dotenv()

app = FastAPI(title="Guardrails Integration API", version="0.1.0")

# --------- Models ---------

class ValidatorConfig(BaseModel):
    type: str = Field(..., description="Validator type key, e.g. 'regex', 'valid_json', 'detect_pii'")
    scope: Optional[str] = Field(default="both", description="Scope: 'input', 'output', or 'both'")
    hub_id: Optional[str] = Field(default=None, description="Guardrails Hub ID, e.g. 'guardrails/valid_json'")
    pattern: Optional[str] = Field(default=None, description="Regex pattern for 'regex' type")
    on_fail: Optional[str] = Field(default="exception", description="Behavior on failure (validator-dependent)")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Extra validator parameters")

class ValidateRequest(BaseModel):
    text: str = Field(..., description="Text to validate")
    scope: Optional[str] = Field(default="both", description="Scope to run validators under")
    validators: List[ValidatorConfig] = Field(default_factory=list, description="List of validator configurations")
    agent_context: Optional[Dict[str, Any]] = Field(default=None, description="Optional agent context for local guardrails service")
    use_local_first: Optional[bool] = Field(default=True, description="Run local guardrails service before Hub if available")

class ValidateResponse(BaseModel):
    text: str
    valid: bool
    details: Dict[str, Any]

# --------- Helpers ---------

def _import_optional_guardrails_api_service():
    """
    Try to import the local guardrails service stack.
    Returns (service_cls, scope_enum_or_str) or (None, None) if unavailable.
    """
    try:
        from gr_integration.guardrails_api_service import GuardrailsApiService
        try:
            from gr_integration.dto import GuardrailsScope  # type: ignore
            scope_enum = GuardrailsScope
        except Exception:
            scope_enum = None
        return GuardrailsApiService, scope_enum
    except Exception:
        return None, None


def _run_hub_validators(text: str, validators: List[ValidatorConfig], scope: str) -> (str, Dict[str, Any]):
    try:
        from gr_integration.hub_adapter import GuardrailsHubAdapter
    except Exception as e:
        logging.getLogger("gr_integration.app").error("Hub adapter import failed: %s", e)
        return text, {
            "valid": False,
            "violations": [{"error": "hub_import_failed", "message": str(e)}],
        }
    hub = GuardrailsHubAdapter()
    if not hub.is_available() or not hub.has_validate():
        logging.getLogger("gr_integration.app").warning(
            "Hub unavailable: available=%s has_validate=%s",
            hub.is_available(), hub.has_validate()
        )
        return text, {
            "valid": False,
            "violations": [{"error": "hub_unavailable", "message": "guardrails-ai not installed or validate not supported"}],
        }

    validators_config: List[Dict[str, Any]] = []
    for v in validators:
        # Accept dict-shaped validators from request body
        if isinstance(v, dict):
            # Infer type from UI label when missing
            name_raw = (str(v.get("validator") or v.get("name") or "")).strip().lower()
            type_raw = (str(v.get("type") or "")).strip().lower()
            if not type_raw:
                if "regex" in name_raw:
                    type_raw = "regex"
                elif "valid url" in name_raw or "url" in name_raw:
                    type_raw = "valid_url"

            scope_raw = (str(v.get("scope") or "both")).strip().lower()
            cfg: Dict[str, Any] = {"type": type_raw, "scope": scope_raw}

            # Default hub_id for known types when missing
            hub_id_raw = (str(v.get("hub_id") or "")).strip().lower()
            if not hub_id_raw and type_raw in {"regex", "regex_match"}:
                hub_id_raw = "guardrails/regex_match"
            if hub_id_raw:
                cfg["hub_id"] = hub_id_raw

            # Strip any surrounding quotes from pattern
            pattern_val = v.get("pattern")
            if isinstance(pattern_val, str):
                pattern_val = pattern_val.strip().strip('"').strip("'")

            # Forward regex pattern for both type and hub_id variants
            if pattern_val and (
                type_raw in {"regex", "regex_match"} or
                hub_id_raw.endswith(("regex_match", "/regex", "regex"))
            ):
                cfg["pattern"] = pattern_val

            if v.get("on_fail"):
                cfg["on_fail"] = v.get("on_fail")

            params = v.get("params") or {}
            if isinstance(params, dict):
                for k, val in params.items():
                    cfg[k] = val
        else:
            # Fallback for Pydantic model instances, if present
            cfg: Dict[str, Any] = {
                "type": (getattr(v, "type", "") or "").strip().lower(),
                "scope": (getattr(v, "scope", "both") or "both").strip().lower(),
            }
            hub_id_val = getattr(v, "hub_id", None)
            if hub_id_val:
                cfg["hub_id"] = hub_id_val

            pattern_val = getattr(v, "pattern", None)
            if isinstance(pattern_val, str):
                pattern_val = pattern_val.strip().strip('"').strip("'")
            if pattern_val and (
                cfg["type"] in {"regex", "regex_match"} or
                str(hub_id_val or "").strip().lower().endswith(("regex_match", "/regex", "regex"))
            ):
                cfg["pattern"] = pattern_val

            on_fail_val = getattr(v, "on_fail", None)
            if on_fail_val:
                cfg["on_fail"] = on_fail_val

            params_val = getattr(v, "params", None)
            if isinstance(params_val, dict):
                for k, val in params_val.items():
                    cfg[k] = val
        validators_config.append(cfg)

    # Inspect what reaches the adapter (helps you verify hub_id/pattern)
    logging.getLogger("gr_integration.app").info("Hub validators_config=%s", validators_config)
    logging.getLogger("gr_integration.app").info("Hub adapter input text=%r scope=%s", text, (scope or "both"))

    sanitized_text, details = hub.run(text, validators_config=validators_config, scope=(scope or "both"))
    return sanitized_text, details or {}

def _is_valid(details: Dict[str, Any]) -> bool:
    try:
        if "valid" in details:
            return bool(details["valid"])
        # Any explicit error should be considered invalid
        if isinstance(details, dict) and details.get("error"):
            return False
        violations = details.get("violations", [])
        if isinstance(violations, list) and len(violations) > 0:
            return False
        return True
    except Exception:
        return True

# --------- Routes ---------

@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})

class _ListHandler(logging.Handler):
    # Collect log records as formatted strings in-memory
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records: List[str] = []
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(self.format(record))
        except Exception:
            # Avoid breaking the request on logging errors
            pass

@app.post("/validate", response_model=ValidateResponse)
@app.post("/validate")
async def validate(
    payload: dict,
    include_logs: bool = Query(default=False, description="Include server-side guardrails logs in response"),
):
    # Per-request log capture
    capturer = _ListHandler()
    target_loggers = ["gr_integration.app", "gr_integration.hub_adapter"]
    for name in target_loggers:
        logging.getLogger(name).addHandler(capturer)

    try:
        scope = str(payload.get("scope", "both")).strip().lower()
        validators = payload.get("validators", []) or []
        user_input = payload.get("text") or payload.get("user_input") or ""
        hub_ids = [ (v.get("hub_id") or "").strip() for v in validators if isinstance(v, dict) and v.get("hub_id") ]

        validation_id = uuid.uuid4().hex[:8]
        use_local_first = payload.get("use_local_first", True)
        logging.getLogger("gr_integration.app").info(
            f"[start] id={validation_id} scope={scope} validators={len(validators)} use_local_first={use_local_first} hub_ids={hub_ids or '(none)'}"
        )
        logging.getLogger("gr_integration.app").info(
            f"[payload] id={validation_id} scope={scope} text={user_input!r}"
        )

        # Optionally run local guardrails first
        if use_local_first:
            GuardrailsApiService, scope_enum = _import_optional_guardrails_api_service()
            if GuardrailsApiService and scope_enum:
                try:
                    sanitized_text, details = GuardrailsApiService.validate(
                        text=user_input,
                        validators=validators,
                        scope=scope_enum(scope),
                        agent_context=payload.get("agent_context"),
                    )
                    valid = _is_valid(details)
                    logging.getLogger("gr_integration.app").info(f"[local] result id={validation_id} valid={valid}")
                    if valid:
                        logging.getLogger("gr_integration.app").info(f"[local] completed id={validation_id}")
                        if include_logs:
                            details = details or {}
                            details["server_logs"] = capturer.records[-200:]
                        return ValidateResponse(text=sanitized_text, valid=True, details=details)
                except Exception as e:
                    logging.getLogger("gr_integration.app").error(f"[local] error id={validation_id} msg={e}")
            else:
                logging.getLogger("gr_integration.app").info(f"[local] unavailable id={validation_id} -> switching to Hub")
        else:
            logging.getLogger("gr_integration.app").info(f"[hub] local-first disabled id={validation_id}")

        # Run hub validators
        logging.getLogger("gr_integration.app").info(
            f"[hub] running id={validation_id} scope={scope} validators={len(validators)} hub_ids={hub_ids or '(none)'}"
        )
        sanitized_text, details = _run_hub_validators(user_input, validators, scope)
        valid = _is_valid(details)
        logging.getLogger("gr_integration.app").info(f"[hub] result id={validation_id} valid={valid}")

        # Attach logs when requested
        if include_logs:
            details = details or {}
            details["server_logs"] = capturer.records[-200:]

        if not valid:
            raise HTTPException(status_code=422, detail={"message": "Guardrail validation failed", **details})

        logging.getLogger("gr_integration.app").info(f"[hub] completed id={validation_id}")
        return ValidateResponse(text=sanitized_text, valid=True, details=details)
    finally:
        # Ensure we detach the per-request handler
        for name in target_loggers:
            try:
                logging.getLogger(name).removeHandler(capturer)
            except Exception:
                pass
    # Pass the original payload to your service (or use the extracted fields above if that’s what it expects)
    result = await GuardrailsApiService.validate(payload)


# App startup module

def _configure_guardrails_logging() -> None:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    target_names = [
        "gr_integration.app",
        "gr_integration.guardrails_api_service",
        "gr_integration.hub_adapter",
        "gr_integration.hub_guardrail",
    ]
    for name in target_names:
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.handlers = [handler]
        lg.propagate = False

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)

@app.on_event("startup")
async def _startup_logging():
    _configure_guardrails_logging()
    logging.getLogger("gr_integration.app").info("Guardrails logging configured")