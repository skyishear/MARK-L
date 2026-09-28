"""MARK L v8.31 — Tool Catalog (metadata + schema validation only).

Describes tools for future model-facing, tool-calling and retry decisions
without touching execution. A ``ToolSpec`` is immutable metadata; a
``ToolCatalog`` stores specs by name. The catalog is **separate from the
execution registry** (``ToolRegistry``): it never executes, routes,
retries, resumes or authorizes anything, and a tool with no spec simply
has no catalog metadata — it is not model-invocable and not eligible for
any future catalog-driven decision. The registry's behaviour is unchanged
by this module.

Metadata defaults are the most restrictive: ``idempotent=False``,
``side_effects=True``, ``model_invocable=False``. They are data only —
nothing here acts on them.

``ToolSpec.parameters`` is a *declaration* (a JSON-Schema subset), not
runtime tool arguments. ``validate_parameters_schema`` checks the
declaration's structure only; it never validates an invocation. The
supported subset is deliberately bounded:

* every schema node is a mapping with a ``type`` of ``"object"``,
  ``"array"``, ``"string"``, ``"number"``, ``"integer"`` or ``"boolean"``
  and an optional ``description`` (str);
* ``"object"`` may add ``properties`` (mapping of non-blank names to
  schemas), ``required`` (unique names, each present in ``properties``)
  and ``additionalProperties`` (bool);
* ``"array"`` may add ``items`` (a schema);
* scalar types may add ``enum`` (non-empty, unique, values of that type);
* the root must be an ``"object"`` schema.

Anything else — unknown keywords, keywords on the wrong type, type
unions — is rejected with ``InvalidToolSchemaError``; nothing is repaired.
An accepted schema is stored as a deep read-only copy (mappings behind
``MappingProxyType``, arrays as tuples; keys, order and values preserved).

Standard library only; no provider, execution, retry, resume, context,
memory, persistence or network dependency.

Dependency direction:

    callers  →  tool_catalog  →  stdlib
    tool_catalog  →  anything in core.*   (forbidden)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional

__all__ = [
    "InvalidToolSchemaError",
    "ToolCatalog",
    "ToolSpec",
    "ToolSpecAlreadyRegisteredError",
    "validate_parameters_schema",
]

_TYPES = ("object", "array", "string", "number", "integer", "boolean")
_COMMON_KEYS = frozenset({"type", "description"})
_KEYS_BY_TYPE = {
    "object": _COMMON_KEYS | {"properties", "required", "additionalProperties"},
    "array": _COMMON_KEYS | {"items"},
    "string": _COMMON_KEYS | {"enum"},
    "number": _COMMON_KEYS | {"enum"},
    "integer": _COMMON_KEYS | {"enum"},
    "boolean": _COMMON_KEYS | {"enum"},
}


class InvalidToolSchemaError(ValueError):
    """Raised when a parameters schema is outside the supported subset."""


class ToolSpecAlreadyRegisteredError(ValueError):
    """Raised when a spec name is registered with a different spec object."""


def validate_parameters_schema(schema: object) -> None:
    """Validate ``schema`` as a tool parameters declaration.

    Pure and deterministic: reads ``schema`` only, returns ``None`` when it
    is inside the supported subset, otherwise raises
    ``InvalidToolSchemaError`` naming the offending location.
    """
    _validate_node(schema, "$")
    if schema.get("type") != "object":  # type: ignore[union-attr]
        raise InvalidToolSchemaError("$: root schema must have type 'object'")


def _validate_node(node: object, path: str) -> None:
    if not isinstance(node, Mapping):
        raise InvalidToolSchemaError(f"{path}: schema must be a mapping")
    for key in node:
        if not isinstance(key, str):
            raise InvalidToolSchemaError(f"{path}: schema keys must be strings")
    kind = node.get("type")
    if not isinstance(kind, str) or kind not in _TYPES:
        raise InvalidToolSchemaError(f"{path}: 'type' must be one of {', '.join(_TYPES)}")
    unsupported = [key for key in node if key not in _KEYS_BY_TYPE[kind]]
    if unsupported:
        raise InvalidToolSchemaError(f"{path}: unsupported keyword(s) for type '{kind}': {sorted(unsupported)}")
    if "description" in node and not isinstance(node["description"], str):
        raise InvalidToolSchemaError(f"{path}: 'description' must be a string")
    if kind == "object":
        _validate_object(node, path)
    elif kind == "array":
        if "items" in node:
            _validate_node(node["items"], f"{path}.items")
    elif "enum" in node:
        _validate_enum(node["enum"], kind, path)


def _validate_object(node: Mapping[str, object], path: str) -> None:
    properties = node.get("properties", {})
    if not isinstance(properties, Mapping):
        raise InvalidToolSchemaError(f"{path}: 'properties' must be a mapping")
    for name, sub in properties.items():
        if not isinstance(name, str) or not name.strip():
            raise InvalidToolSchemaError(f"{path}.properties: property names must be non-empty strings")
        _validate_node(sub, f"{path}.properties.{name}")
    if "required" in node:
        required = node["required"]
        if not isinstance(required, (list, tuple)):
            raise InvalidToolSchemaError(f"{path}: 'required' must be a list")
        if not all(isinstance(r, str) for r in required):
            raise InvalidToolSchemaError(f"{path}: 'required' entries must be strings")
        if len(set(required)) != len(required):
            raise InvalidToolSchemaError(f"{path}: 'required' entries must be unique")
        missing = [r for r in required if r not in properties]
        if missing:
            raise InvalidToolSchemaError(f"{path}: 'required' names not in 'properties': {missing}")
    if "additionalProperties" in node and not isinstance(node["additionalProperties"], bool):
        raise InvalidToolSchemaError(f"{path}: 'additionalProperties' must be a boolean")


def _validate_enum(values: object, kind: str, path: str) -> None:
    if not isinstance(values, (list, tuple)) or not values:
        raise InvalidToolSchemaError(f"{path}: 'enum' must be a non-empty list")
    for value in values:
        if not _matches(value, kind):
            raise InvalidToolSchemaError(f"{path}: 'enum' values must be of type '{kind}'")
    if len(set(values)) != len(values):
        raise InvalidToolSchemaError(f"{path}: 'enum' values must be unique")


def _matches(value: object, kind: str) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int)
    return isinstance(value, (int, float))  # "number"


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(sub) for key, sub in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(sub) for sub in value)
    return value


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Immutable metadata describing one tool (never executes anything)."""

    name: str
    description: str
    parameters: Mapping[str, object]
    idempotent: bool = False
    side_effects: bool = True
    model_invocable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.description, str):
            raise TypeError("description must be a str")
        for flag in ("idempotent", "side_effects", "model_invocable"):
            if not isinstance(getattr(self, flag), bool):
                raise TypeError(f"{flag} must be a bool")
        validate_parameters_schema(self.parameters)
        # Deep defensive copy behind read-only views: the caller's schema
        # and the stored one never alias each other.
        object.__setattr__(self, "parameters", _freeze(self.parameters))


class ToolCatalog:
    """Deterministic, thread-safe, in-process store of ``ToolSpec``s.

    Public API: ``register(spec)``, ``get(name)``, ``list()``.

    Insertion order is preserved. Re-registering the *same* spec object is
    an idempotent no-op; a *different* spec under an existing name raises
    ``ToolSpecAlreadyRegisteredError`` (the ``ToolRegistry`` convention).
    ``get`` of an unknown name returns ``None``. ``list()`` returns a tuple
    snapshot. Metadata only: no execution, routing, retry, resume or
    authorization.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._lock = threading.RLock()

    def register(self, spec: ToolSpec) -> ToolSpec:
        """Register ``spec`` under ``spec.name``.

        Raises:
            TypeError: ``spec`` is not a ``ToolSpec``.
            ToolSpecAlreadyRegisteredError: the name is held by a different
                spec object.
        """
        if not isinstance(spec, ToolSpec):
            raise TypeError("spec must be a ToolSpec")
        with self._lock:
            existing = self._specs.get(spec.name)
            if existing is not None:
                if existing is spec:
                    return spec
                raise ToolSpecAlreadyRegisteredError(f"tool spec '{spec.name}' is already registered")
            self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> Optional[ToolSpec]:
        """Return the spec registered under ``name``, or ``None``."""
        with self._lock:
            return self._specs.get(name)

    def list(self) -> tuple[ToolSpec, ...]:
        """Return all specs in registration order (tuple snapshot)."""
        with self._lock:
            return tuple(self._specs.values())
