"""Single-shot, tool-less call to the Claude API (Anthropic SDK) with structured JSON output.

Same contract as the Claude Code CLI backend (claude_cli.py): one turn, no tools, the answer
validated against a JSON schema. Used when an API key is configured (CLAUDE_BACKEND=api|auto).
Credentials come from the environment (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN), never code.
"""
from __future__ import annotations

import copy
import json
import logging
import time
from typing import Any

import anthropic

from .settings import Settings

log = logging.getLogger("nisar.claude")

# CLI-style aliases -> current model IDs (exact strings, no date suffixes).
MODEL_IDS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# USD per million tokens (input, output), first-party API, prompts up to 100K tokens.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}
MAX_TOKENS = 16000
# JSON-schema keywords the structured-output grammar may reject; Python re-validates them anyway.
_UNSUPPORTED = ("minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength", "pattern")


def model_id(model: str) -> str:
    return MODEL_IDS.get(model, model)


def output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured outputs need closed objects: additionalProperties=false everywhere."""
    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: fix(v) for k, v in node.items() if k not in _UNSUPPORTED}
            if node.get("type") == "object" or (isinstance(node.get("type"), list) and "object" in node["type"]):
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [fix(v) for v in node]
        return node
    return fix(copy.deepcopy(schema))


def _cost(model: str, usage: Any) -> float | None:
    price = PRICES.get(model)
    if not price:
        return None
    cin, cout = price
    cached = (getattr(usage, "cache_read_input_tokens", 0) or 0) * 0.1 \
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * 1.25
    return round(((usage.input_tokens or 0) + cached) * cin / 1e6 + (usage.output_tokens or 0) * cout / 1e6, 6)


def ask_structured_api(system_prompt: str, user_prompt: str, schema: dict[str, Any], model: str,
                       settings: Settings, effort: str | None = None,
                       client: anthropic.Anthropic | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    mid = model_id(model)
    client = client or anthropic.Anthropic(timeout=float(settings.claude_timeout_s), max_retries=2)
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": output_schema(schema)}}
    if effort:
        output_config["effort"] = effort
    started = time.monotonic()
    try:
        response = client.messages.create(
            model=mid,
            max_tokens=MAX_TOKENS,
            # The role (skill / parser prompt) is stable across calls: cache it.
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}],
            output_config=output_config,
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("API key de Anthropic inválida o ausente (ANTHROPIC_API_KEY).") from exc
    except anthropic.PermissionDeniedError as exc:
        raise RuntimeError(f"La API key no tiene acceso al modelo {mid}.") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Límite de uso de la API de Anthropic alcanzado; intenta en un rato.") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Error de la API de Anthropic ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("No se pudo conectar con la API de Anthropic.") from exc

    if response.stop_reason == "refusal":
        raise RuntimeError("El modelo declinó responder esta consulta.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta del modelo se cortó (max_tokens).")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError("La API no devolvió texto.")
    usage = {
        "model": mid,
        "backend": "api",
        "duration_ms": round((time.monotonic() - started) * 1000),
        "num_turns": 1,
        "cost_usd_equivalent": _cost(mid, response.usage),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "request_id": getattr(response, "_request_id", None),
    }
    log.info("Claude API (%s): %s ms, %s→%s tokens", mid, usage["duration_ms"],
             usage["input_tokens"], usage["output_tokens"])
    return json.loads(text), usage
