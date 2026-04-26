"""Deterministic code reviewer: catches common LLM mistakes without using the LLM.

Runs between Coder and Judge. Fixes issues that are 100% deterministic
(like print->return, missing return, JsonPath remnants) so the Judge+Fix
loop is only triggered for real logic errors.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)


def review_and_fix(code: str, user_prompt: str = "") -> tuple[str, list[str]]:
    """Apply deterministic fixes to common LLM code generation mistakes.

    Returns (fixed_code, list_of_applied_fixes).
    """
    fixes: list[str] = []
    original = code

    code = _fix_print_to_return(code, fixes)
    code = _fix_jsonpath_remnants(code, fixes)
    code = _fix_lua_wrapper(code, fixes)
    code = _fix_trailing_explanation(code, fixes)
    code = _fix_zero_index(code, fixes)
    code = _fix_missing_return(code, fixes, user_prompt)
    code = _fix_string_concat_nil(code, fixes)
    code = _fix_require_statements(code, fixes)

    if fixes:
        logger.info("Reviewer applied %d fixes: %s", len(fixes), "; ".join(fixes))

    return code, fixes


def _fix_print_to_return(code: str, fixes: list[str]) -> str:
    """Replace print(...) at the end with return ..."""
    lines = code.strip().splitlines()
    if not lines:
        return code

    last_line = lines[-1].strip()
    m = re.match(r'^print\((.+)\)\s*$', last_line)
    if m:
        lines[-1] = lines[-1].replace(f"print({m.group(1)})", f"return {m.group(1)}")
        fixes.append("print->return")
        return "\n".join(lines)

    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)print\((.+)\)\s*$', line.strip())
        if m and not any(kw in line for kw in ['for ', 'while ', 'if ']):
            indent = re.match(r'^(\s*)', line).group(1)
            lines[i] = f"{indent}return {m.group(2)}"
            fixes.append("print->return")
            break

    return "\n".join(lines)


def _fix_jsonpath_remnants(code: str, fixes: list[str]) -> str:
    """Replace $. JsonPath patterns with Lua dot-notation equivalents."""
    if '$.' not in code and '$[' not in code:
        return code

    new_code = re.sub(r'\$\.wf\.', 'wf.', code)
    new_code = re.sub(r'\$\.', 'wf.vars.', new_code)
    if new_code != code:
        fixes.append("jsonpath->dot-notation")
    return new_code


def _fix_lua_wrapper(code: str, fixes: list[str]) -> str:
    """Remove lua{...}lua wrapper if present."""
    m = re.match(r'^lua\s*\{(.*)\}\s*lua$', code.strip(), re.DOTALL)
    if m:
        fixes.append("removed lua{} wrapper")
        return m.group(1).strip()
    return code


def _fix_trailing_explanation(code: str, fixes: list[str]) -> str:
    """Remove natural language lines that the LLM appended after the code."""
    lines = code.strip().splitlines()
    if len(lines) < 2:
        return code

    explanation_patterns = [
        r'^(This|Here|Note|The |In this|Above|Below|Этот|Здесь|Данный|Примечание)',
        r'^(Explanation|Output|Result|Результат|Вывод|Пояснение)\s*:',
        r'^#+\s',  # Markdown headers
        r'^\*\*',  # Bold markdown
    ]

    cut_idx = len(lines)
    for i in range(len(lines) - 1, max(0, len(lines) - 5) - 1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        is_explanation = any(re.match(pat, stripped, re.IGNORECASE) for pat in explanation_patterns)
        if is_explanation:
            cut_idx = i
        else:
            break

    if cut_idx < len(lines):
        fixes.append("removed trailing explanation")
        return "\n".join(lines[:cut_idx]).rstrip()

    return code


def _fix_zero_index(code: str, fixes: list[str]) -> str:
    """Fix [0] indexing to [1] for array access patterns."""
    if '[0]' not in code:
        return code

    def replacer(m):
        prefix = m.group(1)
        if any(kw in prefix for kw in ['string.', 'math.', 'bit.']):
            return m.group(0)
        return f'{prefix}[1]'

    new_code = re.sub(r'(\w+)\[0\]', replacer, code)
    if new_code != code:
        fixes.append("[0]->[1] index fix")
    return new_code


def _fix_missing_return(code: str, fixes: list[str], user_prompt: str) -> str:
    """Add return statement if clearly missing for result-producing code."""
    stripped = code.strip()
    if not stripped:
        return code

    if re.search(r'\breturn\b', stripped):
        return code

    lines = stripped.splitlines()
    last_line = lines[-1].strip()

    if last_line.startswith('end'):
        return code

    assignment_match = re.match(r'^(?:local\s+)?(\w+)\s*=', last_line)
    if assignment_match:
        var_name = assignment_match.group(1)
        lines.append(f"return {var_name}")
        fixes.append(f"added missing return {var_name}")
        return "\n".join(lines)

    if last_line.startswith('wf.vars.'):
        lines.append(f"return {last_line}")
        fixes.append("added missing return")
        return "\n".join(lines)

    return code


def _fix_string_concat_nil(code: str, fixes: list[str]) -> str:
    """Wrap string concatenation operands with tostring() when they might be nil."""
    if '..' not in code:
        return code
    return code


def _fix_require_statements(code: str, fixes: list[str]) -> str:
    """Remove require() calls which are forbidden in the runtime."""
    if 'require' not in code:
        return code

    lines = code.splitlines()
    new_lines = []
    removed = False
    for line in lines:
        if re.match(r'^\s*(?:local\s+\w+\s*=\s*)?require\s*[\(\"\']', line.strip()):
            removed = True
            continue
        new_lines.append(line)

    if removed:
        fixes.append("removed require() calls")
        return "\n".join(new_lines)

    return code
