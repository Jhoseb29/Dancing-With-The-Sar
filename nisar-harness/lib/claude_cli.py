"""Single-shot, tool-less calls to Claude with structured JSON output. The only entry point for the models.

Two backends, same contract (CLAUDE_BACKEND):
  cli   Claude Code CLI with the user's subscription (below)
  api   Anthropic API with ANTHROPIC_API_KEY (claude_api.py)
  auto  api if an API key is configured, otherwise cli (default)

CLI backend:
Token-lean by design:
  * --system-prompt replaces Claude Code's large default prompt with ours
  * --tools ""            no tool definitions, no agent loop: exactly one model turn
  * --strict-mcp-config   no MCP server tool schemas
  * cwd = temp dir        no project CLAUDE.md is auto-loaded
  * --json-schema         the answer is validated JSON, no parsing heuristics
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

from .settings import Settings

log = logging.getLogger("nisar.claude")


@dataclass
class ClaudeResult:
    data: dict[str, Any]
    usage: dict[str, Any]


def backend(settings: Settings) -> str:
    if settings.claude_backend in ("cli", "api"):
        return settings.claude_backend
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return "api" if has_key else "cli"


def ask_structured(system_prompt: str, user_prompt: str, schema: dict[str, Any],
                   model: str, settings: Settings, effort: str | None = None) -> ClaudeResult:
    """`effort` (low|medium|high) applies to the API backend; the CLI uses its own default."""
    if backend(settings) == "api":
        from .claude_api import ask_structured_api  # SDK only imported when used
        data, usage = ask_structured_api(system_prompt, user_prompt, schema, model, settings, effort)
        return ClaudeResult(data, usage)
    return _ask_cli(system_prompt, user_prompt, schema, model, settings)


def _ask_cli(system_prompt: str, user_prompt: str, schema: dict[str, Any],
             model: str, settings: Settings) -> ClaudeResult:
    binary = shutil.which(settings.claude_bin)
    if not binary:
        raise FileNotFoundError(f"No se encontró el CLI de Claude Code ('{settings.claude_bin}'). "
                                "Instálalo y ejecuta `claude` una vez para iniciar sesión.")
    cmd = [
        binary, "-p",
        "--output-format", "json",
        "--model", model,
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--system-prompt", system_prompt,
        "--json-schema", json.dumps(schema),
    ]
    # Subscription auth: never let an API key or a parent Claude session hijack the call.
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    proc = subprocess.run(
        cmd, input=user_prompt, cwd=tempfile.gettempdir(), env=env,
        capture_output=True, text=True, timeout=settings.claude_timeout_s, check=False,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Salida no JSON de Claude (rc={proc.returncode}): {proc.stderr[-500:]}") from exc
    if proc.returncode != 0 or out.get("is_error"):
        raise RuntimeError(f"Claude Code falló (rc={proc.returncode}): {str(out.get('result'))[:500]}")

    data = out.get("structured_output")
    if data is None:  # older CLI: JSON comes back as text
        data = json.loads(out.get("result") or "{}")
    usage = {
        "model": model,
        "backend": "cli",
        "duration_ms": out.get("duration_ms"),
        "num_turns": out.get("num_turns"),
        "cost_usd_equivalent": out.get("total_cost_usd"),
        "input_tokens": (out.get("usage") or {}).get("input_tokens"),
        "output_tokens": (out.get("usage") or {}).get("output_tokens"),
    }
    log.info("Claude (%s): %s turnos, %s ms", model, usage["num_turns"], usage["duration_ms"])
    return ClaudeResult(data, usage)
