"""Single-shot, tool-less calls to Claude with structured JSON output.

Two backends (same `ask_structured` contract):
  * ANTHROPIC_API_KEY set -> Claude API through the official `anthropic` SDK (works the same on
    Windows, no CLI subprocess). Short answers: low effort, JSON asked in the prompt.
  * otherwise             -> Claude Code CLI (`claude -p`, user's subscription), as before:

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


# Short aliases used by settings (CLAUDE_INTENT_MODEL=haiku, CLAUDE_INTERPRET_MODEL=sonnet).
API_MODEL_ALIASES = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# Server-side refusal fallback is not available for Haiku.
API_FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5")
API_MAX_TOKENS = 8000


def ask_structured(system_prompt: str, user_prompt: str, schema: dict[str, Any],
                   model: str, settings: Settings) -> ClaudeResult:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _ask_api(system_prompt, user_prompt, schema, model)
    return _ask_cli(system_prompt, user_prompt, schema, model, settings)


def _ask_api(system_prompt: str, user_prompt: str, schema: dict[str, Any], model: str) -> ClaudeResult:
    """One Claude API call. The JSON shape goes in the system prompt (our schemas use nullable
    types and array bounds, so we parse tolerantly instead of using strict structured outputs)."""
    import anthropic

    model_id = API_MODEL_ALIASES.get(model, model)
    system = (f"{system_prompt}\n\nResponde SOLO con un objeto JSON válido (sin texto ni bloques de código "
              f"alrededor) que cumpla este JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}")
    params: dict[str, Any] = {
        "model": model_id,
        "max_tokens": API_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
        "output_config": {"effort": "low"},  # one extraction / one short explanation
    }
    client = anthropic.Anthropic()
    if model_id in API_FALLBACK_MODELS:
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
    else:
        response = client.messages.create(**params)
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declinó la solicitud")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Respuesta de Claude cortada por max_tokens")
    text = next((b.text for b in response.content if b.type == "text"), "")
    usage = {
        "model": response.model,
        "duration_ms": None,
        "num_turns": 1,
        "cost_usd_equivalent": None,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    log.info("Claude API (%s): %s→%s tokens", response.model, usage["input_tokens"], usage["output_tokens"])
    return ClaudeResult(_json_from_text(text), usage)


def _ask_cli(system_prompt: str, user_prompt: str, schema: dict[str, Any],
             model: str, settings: Settings) -> ClaudeResult:
    prefix, via_cmd_exe = resolve_command(settings.claude_bin)
    schema_json = json.dumps(schema, ensure_ascii=False)
    stdin_text = user_prompt
    flags = ["--system-prompt", system_prompt, "--json-schema", schema_json]
    if via_cmd_exe and len(system_prompt) + len(schema_json) > CMD_EXE_MAX_CHARS:
        # Last resort (shim only, no node/cli.js found): keep the command line short and move
        # role + schema into stdin. The answer then comes back as JSON text (parsed below).
        log.warning("Claude vía cmd.exe: el rol y el schema van por stdin (instala claude.exe para evitarlo)")
        flags = ["--system-prompt", "Sigue las instrucciones de <rol> y responde SOLO con JSON válido."]
        stdin_text = (f"<rol>\n{system_prompt}\n</rol>\n<json_schema>\n{schema_json}\n</json_schema>\n\n"
                      f"{user_prompt}")
    cmd = [
        *prefix, "-p",
        "--output-format", "json",
        "--model", model,
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        *flags,
    ]
    # Subscription auth: never let an API key or a parent Claude session hijack the call.
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    # encoding: on Windows text=True would use cp1252 and break tildes/ñ both ways.
    proc = subprocess.run(
        cmd, input=stdin_text, cwd=tempfile.gettempdir(), env=env,
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
    if data is None:  # older CLI or stdin fallback: JSON comes back as text
        data = _json_from_text(out.get("result") or "{}")
    usage = {
        "model": model,
        "duration_ms": out.get("duration_ms"),
        "num_turns": out.get("num_turns"),
        "cost_usd_equivalent": out.get("total_cost_usd"),
        "input_tokens": (out.get("usage") or {}).get("input_tokens"),
        "output_tokens": (out.get("usage") or {}).get("output_tokens"),
    }
    log.info("Claude (%s): %s turnos, %s ms", model, usage["num_turns"], usage["duration_ms"])
    return ClaudeResult(data, usage)


def _json_from_text(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text, tolerating ```json fences or surrounding prose."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])
