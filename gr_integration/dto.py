from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Union


class GuardrailsScope(Enum):
    INPUT = "input"
    OUTPUT = "output"
    BOTH = "both"


class GuardrailsType(Enum):
    REGEX_MATCH = "regex_match"
    VALID_JSON = "valid_json"
    VALID_URL = "valid_url"
    TOXIC_LANGUAGE = "toxic_language"
    COMPETITOR_CHECK = "competitor_check"
    DETECT_PII = "detect_pii"
    BLOCKLIST = "blocklist"
    PII = "pii"


@dataclass
class AgentMetadata:
    id: Optional[str] = None


@dataclass
class CoreAgentContext:
    session_id: Optional[str] = None
    agent_metadata: Optional[AgentMetadata] = None


@dataclass
class AgentGuardrail:
    id: Optional[str] = None
    type: Union[str, GuardrailsType] = "regex_match"
    scope: Union[str, GuardrailsScope] = GuardrailsScope.BOTH
    hub_id: Optional[str] = None
    pattern: Optional[str] = None
    on_fail: Optional[str] = "exception"
    params: Optional[Dict[str, Any]] = None