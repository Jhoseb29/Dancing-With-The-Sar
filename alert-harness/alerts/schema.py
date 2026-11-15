"""JSON Schema validation for indicators, alerts and evaluation cases (schemas/*.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .settings import HARNESS_DIR

SCHEMAS_DIR = HARNESS_DIR / "schemas"


@lru_cache
def _registry() -> Registry:
    resources = []
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema)
        resources += [(schema["$id"], resource), (path.name, resource)]
    return Registry().with_resources(resources)


@lru_cache
def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_registry())


def errors(name: str, document: Any) -> list[str]:
    """Human-readable validation errors ([] = valid)."""
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '/'}: {e.message}"
            for e in validator(name).iter_errors(document)]


def require(name: str, document: Any) -> Any:
    problems = errors(name, document)
    if problems:
        raise ValueError(f"{name} inválido: {problems[:3]}")
    return document
