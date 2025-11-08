import importlib
from typing import Dict, Type, Optional, Union
from agents.dto import AgentGuardrail, GuardrailsType
from .base_guardrail import Guardrail
from .blocklist_guardrail import BlocklistGuardrail
from .hub_guardrail import HubGuardrail
from .pii_guardrail import PIIGuardrail
from .regex_guardrail import RegexGuardrail


def _normalize_type_key(type_key: Union[str, GuardrailsType]) -> str:
    """Normalize type key to a canonical lower-case string.

    Accepts enum or string values like "Regex", "Blocklist", "PII" and
    returns "regex", "blocklist", "pii". Also trims dotted enum names.
    """
    if isinstance(type_key, GuardrailsType):
        key = str(type_key.value or "").strip().lower()
    else:
        key = str(type_key or "").strip().lower()
    if "." in key:
        key = key.split(".")[-1]
    return key


def _import_class(path: str) -> Type[Guardrail]:
    module_path, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    if not isinstance(cls, type):
        raise TypeError(f"Imported object is not a class: {path}")
    return cls


class GuardrailFactory:
    """Factory for creating Guardrail instances with a dynamic registry."""

    def __init__(self) -> None:
        self._registry: Dict[str, Type[Guardrail]] = {}

    def register(self, type_key: Union[str, GuardrailsType], cls: Type[Guardrail]) -> None:
        key = _normalize_type_key(type_key)
        self._registry[key] = cls

    def register_from_path(self, type_key: Union[str, GuardrailsType], class_path: str) -> None:
        cls = _import_class(class_path)
        self.register(type_key, cls)

    def unregister(self, type_key: Union[str, GuardrailsType]) -> None:
        key = _normalize_type_key(type_key)
        self._registry.pop(key, None)

    def get(self, type_key: Union[str, GuardrailsType]) -> Optional[Type[Guardrail]]:
        key = _normalize_type_key(type_key)
        return self._registry.get(key)

    def create(self, config: AgentGuardrail) -> Guardrail:
        cls = self.get(getattr(config, "type", None)) or Guardrail
        return cls(config)


def get_default_factory() -> GuardrailFactory:
    return _default_factory


# module-level registrations for default factory
_default_factory = GuardrailFactory()
_default_factory.register("regex_match", HubGuardrail)
_default_factory.register("valid_json", HubGuardrail)
_default_factory.register("valid_url", HubGuardrail)
_default_factory.register("toxic_language", HubGuardrail)
_default_factory.register("competitor_check", HubGuardrail)
# _default_factory.register("pii", PIIGuardrail)
_default_factory.register("detect_pii", PIIGuardrail)
_default_factory.register("blocklist", BlocklistGuardrail)
