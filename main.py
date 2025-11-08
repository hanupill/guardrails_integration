import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

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
        from guardrails.guardrails_api_service import GuardrailsApiService
        try:
            from agents.dto import GuardrailsScope  # type: ignore
            scope_enum = GuardrailsScope
        except Exception:
            scope_enum = None
        return GuardrailsApiService, scope_enum
    except Exception:
        return None, None


def _run_hub_validators(text: str, validators: List[ValidatorConfig], scope: str) -> (str, Dict[str, Any]):
    # Use the existing adapter to run hub validators
    try:
        from guardrails.hub_adapter import GuardrailsHubAdapter
    except Exception as e:
        return text, {"error": f"Hub adapter import failed: {e}"}

    hub = GuardrailsHubAdapter()
    if not hub.is_available() or not hub.has_validate():
        return text, {"error": "guardrails-ai library not available or validate not supported"}

    validators_config: List[Dict[str, Any]] = []
    for v in validators:
        cfg: Dict[str, Any] = {
            "type": (v.type or "").strip().lower(),
            "scope": (v.scope or "both").strip().lower(),
        }
        if v.hub_id:
            cfg["hub_id"] = v.hub_id
        if v.pattern and cfg["type"] == "regex":
            cfg["pattern"] = v.pattern
        if v.on_fail:
            cfg["on_fail"] = v.on_fail
        if v.params:
            for k, val in v.params.items():
                cfg[k] = val
        validators_config.append(cfg)

    sanitized_text, details = hub.run(text, validators_config=validators_config, scope=(scope or "both"))
    return sanitized_text, details or {}

def _is_valid(details: Dict[str, Any]) -> bool:
    try:
        if "valid" in details:
            return bool(details["valid"])
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

@app.post("/validate", response_model=ValidateResponse)
def validate(req: ValidateRequest) -> ValidateResponse:
    scope = (req.scope or "both").strip().lower()

    # Optionally run local guardrails first
    pre_text = req.text
     # Run hub validators
    sanitized_text, details = _run_hub_validators(pre_text, req.validators, scope)
    valid = _is_valid(details)

    # If invalid, propagate as 422 with details
    if not valid:
        raise HTTPException(status_code=422, detail={"message": "Guardrail validation failed", **details})

    return ValidateResponse(text=sanitized_text, valid=True, details=details)