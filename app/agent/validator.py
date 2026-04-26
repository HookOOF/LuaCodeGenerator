import asyncio
import re
import shutil
from dataclasses import dataclass, field


LUA_STUB_PREAMBLE = """\
local _mt = {__index = function(t, k) return setmetatable({}, getmetatable(t)) end, __newindex = function() end, __call = function() return setmetatable({}, {__index = function(t,k) return t end}) end}
wf = setmetatable({}, _mt)
wf.vars = setmetatable({}, _mt)
wf.initVariables = setmetatable({}, _mt)
_utils = setmetatable({}, _mt)
"""

PREAMBLE_LINES = LUA_STUB_PREAMBLE.count("\n")

ALLOWED_GLOBALS = frozenset({
    "wf", "_utils",
    "string", "table", "math",
    "tonumber", "tostring", "type",
    "pairs", "ipairs", "next", "select", "unpack",
    "pcall", "xpcall", "error", "assert",
    "setmetatable", "getmetatable", "rawget", "rawset", "rawlen",
    "true", "false", "nil",
})

_FORBIDDEN_MODULE_RE = re.compile(
    r'\b(os|io|package|debug|coroutine)\s*\.\s*\w+',
)
_FORBIDDEN_FUNC_RE = re.compile(
    r'\b(require|dofile|loadfile)\s*[\(\"\']',
)
_JSONPATH_RE = re.compile(
    r'(\$\.|\$\[)',
)
_PRINT_RE = re.compile(
    r'\bprint\s*\(',
)
_ZERO_INDEX_RE = re.compile(
    r'\[\s*0\s*\]',
)


def _find_lua_checker() -> list[str] | None:
    for cmd in (["luac", "-p", "-"], ["lua5.4", "-p", "-"], ["lua", "-p", "-"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


@dataclass
class ValidationResult:
    is_valid: bool
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _strip_lua_strings_and_comments(code: str) -> str:
    """Remove string literals and comments so regex rules don't false-positive on them."""
    result = []
    i = 0
    n = len(code)
    while i < n:
        if code[i] == '-' and i + 1 < n and code[i + 1] == '-':
            if i + 2 < n and code[i + 2] == '[':
                level = 0
                j = i + 3
                while j < n and code[j] == '=':
                    level += 1
                    j += 1
                if j < n and code[j] == '[':
                    close = ']' + '=' * level + ']'
                    end = code.find(close, j + 1)
                    if end == -1:
                        i = n
                    else:
                        i = end + len(close)
                    continue
            end = code.find('\n', i)
            i = end if end != -1 else n
            continue
        if code[i] == '[':
            level = 0
            j = i + 1
            while j < n and code[j] == '=':
                level += 1
                j += 1
            if j < n and code[j] == '[':
                close = ']' + '=' * level + ']'
                end = code.find(close, j + 1)
                if end == -1:
                    result.append(code[i])
                    i += 1
                else:
                    result.append(' ' * (end + len(close) - i))
                    i = end + len(close)
                continue
        if code[i] in ('"', "'"):
            quote = code[i]
            j = i + 1
            while j < n:
                if code[j] == '\\':
                    j += 2
                    continue
                if code[j] == quote:
                    j += 1
                    break
                j += 1
            result.append(' ' * (j - i))
            i = j
            continue
        result.append(code[i])
        i += 1
    return ''.join(result)


def _check_domain_rules(code: str) -> list[str]:
    """Run regex-based domain rule checks. Returns list of error descriptions."""
    clean = _strip_lua_strings_and_comments(code)
    errors: list[str] = []

    for m in _JSONPATH_RE.finditer(clean):
        lineno = clean[:m.start()].count('\n') + 1
        errors.append(
            f"line {lineno}: JsonPath syntax detected ('{m.group()}'). "
            f"Use Lua dot-notation: wf.vars.FIELD, not $.wf.vars.FIELD"
        )

    for m in _FORBIDDEN_MODULE_RE.finditer(clean):
        lineno = clean[:m.start()].count('\n') + 1
        module = m.group(1)
        errors.append(
            f"line {lineno}: Forbidden module '{module}.*' is not available in the LowCode runtime"
        )

    for m in _FORBIDDEN_FUNC_RE.finditer(clean):
        lineno = clean[:m.start()].count('\n') + 1
        func = m.group(1)
        errors.append(
            f"line {lineno}: Forbidden function '{func}()' is not available in the LowCode runtime"
        )

    for m in _PRINT_RE.finditer(clean):
        lineno = clean[:m.start()].count('\n') + 1
        errors.append(
            f"line {lineno}: Do not use print(). Use 'return' to produce the result value"
        )

    for m in _ZERO_INDEX_RE.finditer(clean):
        lineno = clean[:m.start()].count('\n') + 1
        errors.append(
            f"line {lineno}: Lua arrays are 1-indexed. [0] is likely a bug — use [1] for the first element"
        )

    return errors


def _adjust_error(error_text: str) -> str:
    lines = error_text.split("\n")
    adjusted = []
    for line in lines:
        clean = line.replace("stdin:", "").replace("luac:", "").strip()
        if not clean:
            continue
        try:
            parts = clean.split(":", 1)
            lineno = int(parts[0].strip())
            adjusted_lineno = lineno - PREAMBLE_LINES
            if adjusted_lineno < 1:
                adjusted_lineno = 1
            adjusted.append(f"line {adjusted_lineno}:{parts[1]}")
        except (ValueError, IndexError):
            adjusted.append(line.strip())
    return "\n".join(adjusted) if adjusted else error_text


async def validate_lua(code: str) -> ValidationResult:
    domain_errors = _check_domain_rules(code)

    if domain_errors:
        return ValidationResult(
            is_valid=False,
            error="Domain rule violations:\n" + "\n".join(domain_errors),
        )

    checker = _find_lua_checker()
    if not checker:
        return ValidationResult(is_valid=True, error=None)

    wrapped = LUA_STUB_PREAMBLE + code
    try:
        proc = await asyncio.create_subprocess_exec(
            *checker,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(input=wrapped.encode()), timeout=5.0)
        if proc.returncode == 0:
            return ValidationResult(is_valid=True)
        return ValidationResult(is_valid=False, error=_adjust_error(stderr.decode()))
    except asyncio.TimeoutError:
        return ValidationResult(is_valid=False, error="Lua syntax check timed out")
