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
from pathlib import Path
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


CMD_SHIM_SUFFIXES = (".cmd", ".bat")
# Our system prompts + schema exceed this when they go through cmd.exe (npm's claude.cmd shim).
CMD_EXE_MAX_CHARS = 8000


def _npm_cli_js(shim: Path) -> Path | None:
    """npm installs `claude.cmd` next to node_modules/@anthropic-ai/claude-code/cli.js."""
    candidate = shim.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    return candidate if candidate.is_file() else None


def resolve_command(claude_bin: str) -> tuple[list[str], bool]:
    """Command prefix to launch Claude Code and whether it runs through cmd.exe.

    On Windows `shutil.which("claude")` may return the npm shim `claude.cmd`. Running a .cmd
    goes through cmd.exe, which caps the command line at 8191 chars and mangles the quotes of
    our JSON schema; so we launch `node cli.js` directly when we can find it.
    """
    binary = shutil.which(claude_bin)
    if not binary:
        raise FileNotFoundError(f"No se encontró el CLI de Claude Code ('{claude_bin}'). "
                                "Instálalo y ejecuta `claude` una vez para iniciar sesión.")
    path = Path(binary)
    if os.name != "nt" or path.suffix.lower() not in CMD_SHIM_SUFFIXES:
        return [binary], False
    exe = shutil.which(str(path.with_suffix(".exe"))) or shutil.which("claude.exe")
    if exe:  # native installer
        return [exe], False
    cli_js, node = _npm_cli_js(path), shutil.which("node")
    if cli_js and node:
        return [node, str(cli_js)], False
    return [binary], True


def _ask_cli(system_prompt: str, user_prompt: str, schema: dict[str, Any],
             model: str, settings: Settings) -> ClaudeResult:
    # Windows: `claude.cmd` (npm) pasaría por cmd.exe, que corta la línea a 8191 caracteres.
    prefix, via_cmd_exe = resolve_command(settings.claude_bin)
    if via_cmd_exe and len(system_prompt) + len(json.dumps(schema)) > CMD_EXE_MAX_CHARS:
        raise RuntimeError("El rol y el schema no caben en cmd.exe: instala claude.exe o usa CLAUDE_BACKEND=api.")
    cmd = [
        *prefix, "-p",
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
        # encoding: en Windows text=True usaría cp1252 y rompería tildes y ñ.
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=settings.claude_timeout_s, check=False,
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
