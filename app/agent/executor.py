"""Lua code executor: runs generated code with test assertions in a subprocess."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    tests_passed: bool = False
    error_summary: str = ""


def json_to_lua(obj: object) -> str:
    """Convert a Python object (parsed JSON) to a Lua table literal."""
    if obj is None:
        return "nil"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, str):
        escaped = (
            obj.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\0", "\\0")
        )
        return f'"{escaped}"'
    if isinstance(obj, list):
        items = ", ".join(json_to_lua(v) for v in obj)
        return "{" + items + "}"
    if isinstance(obj, dict):
        pairs = []
        for k, v in obj.items():
            if re.match(r"^[A-Za-z_]\w*$", k):
                pairs.append(f"{k} = {json_to_lua(v)}")
            else:
                pairs.append(f'["{k}"] = {json_to_lua(v)}')
        return "{" + ", ".join(pairs) + "}"
    return tostring(obj)


def extract_json_context(prompt: str) -> dict | None:
    """Extract JSON context (wf structure) from the user prompt."""
    # Try to find JSON that starts with {"wf" or { "wf"
    patterns = [
        r'(\{["\s]*wf["\s]*:.+)',
        r'(\{["\s]*"wf"["\s]*:.+)',
    ]
    for pat in patterns:
        m = re.search(pat, prompt, re.DOTALL)
        if m:
            text = m.group(1)
            # Try to parse progressively shorter substrings
            for end in range(len(text), 0, -1):
                try:
                    return json.loads(text[:end])
                except json.JSONDecodeError:
                    continue
    return None


def _build_lua_preamble(json_context: dict | None) -> str:
    """Build Lua preamble that sets up wf and _utils from JSON context."""
    lines = [
        '_utils = {array = {new = function() return {} end, markAsArray = function(t) return t end}}',
    ]
    if json_context and "wf" in json_context:
        wf = json_context["wf"]
        vars_lua = json_to_lua(wf.get("vars", {}))
        init_lua = json_to_lua(wf.get("initVariables", {}))
        lines.append(f"wf = {{vars = {vars_lua}, initVariables = {init_lua}}}")
    else:
        lines.append("wf = {vars = {}, initVariables = {}}")
    return "\n".join(lines)


def _build_deep_equal() -> str:
    """Lua helper for deep table comparison in assertions."""
    return """\
local function _deepEqual(a, b)
  if type(a) ~= type(b) then return false end
  if type(a) ~= "table" then return a == b end
  for k, v in pairs(a) do
    if not _deepEqual(v, b[k]) then return false end
  end
  for k in pairs(b) do
    if a[k] == nil then return false end
  end
  return true
end
local function _serialize(v, depth)
  depth = depth or 0
  if depth > 5 then return "..." end
  if v == nil then return "nil" end
  if type(v) == "string" then return '"' .. v .. '"' end
  if type(v) ~= "table" then return tostring(v) end
  local parts = {}
  for k, val in pairs(v) do
    parts[#parts + 1] = tostring(k) .. "=" .. _serialize(val, depth + 1)
  end
  return "{" .. table.concat(parts, ", ") .. "}"
end"""


def build_test_script(
    code: str,
    json_context: dict | None,
    test_assertions: str,
) -> str:
    """Build a complete Lua script: preamble + code-under-test + assertions."""
    preamble = _build_lua_preamble(json_context)
    deep_equal = _build_deep_equal()

    return f"""{preamble}

{deep_equal}

local _ok, _result = pcall(function()
{_indent(code)}
end)

if not _ok then
  io.stderr:write("RUNTIME_ERROR: " .. tostring(_result) .. "\\n")
  os.exit(1)
end

{test_assertions}
print("TESTS_PASSED")
"""


def _indent(code: str, spaces: int = 2) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in code.splitlines())


def _find_lua() -> list[str] | None:
    for cmd in ["lua5.4", "lua"]:
        if shutil.which(cmd):
            return [cmd]
    return None


async def run_lua_with_tests(
    code: str,
    json_context: dict | None,
    test_assertions: str,
    timeout: float = 5.0,
) -> ExecutionResult:
    """Execute generated Lua code with test assertions in a subprocess."""
    lua_cmd = _find_lua()
    if not lua_cmd:
        return ExecutionResult(
            success=False,
            error_summary="Lua interpreter not found (lua5.4 / lua)",
        )

    script = build_test_script(code, json_context, test_assertions)
    logger.debug("Executor script:\n%s", script)

    try:
        proc = await asyncio.create_subprocess_exec(
            *lua_cmd, "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=script.encode()), timeout=timeout,
        )
        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        exit_code = proc.returncode or 0
        tests_passed = "TESTS_PASSED" in stdout

        error_summary = ""
        if not tests_passed:
            if "RUNTIME_ERROR:" in stderr:
                error_summary = stderr
            elif stderr:
                error_summary = stderr
            elif exit_code != 0:
                error_summary = f"Lua exited with code {exit_code}"

        return ExecutionResult(
            success=exit_code == 0 and tests_passed,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            tests_passed=tests_passed,
            error_summary=error_summary,
        )
    except asyncio.TimeoutError:
        return ExecutionResult(
            success=False,
            error_summary="Lua execution timed out",
        )
    except Exception as exc:
        return ExecutionResult(
            success=False,
            error_summary=f"Executor error: {exc}",
        )
