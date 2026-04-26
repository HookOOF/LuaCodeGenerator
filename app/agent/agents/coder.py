"""Coder agent: generates Lua code (single-shot or multi-part) with auto-continuation."""

from __future__ import annotations

import re
import logging

from app.agent.agents.base import BaseAgent, LLMCallFn
from app.agent.prompts import CODER_PROMPT, CODER_STEP_PROMPT, CONTINUE_PROMPT
from app.agent.rag import retrieve

logger = logging.getLogger(__name__)

MAX_CONTINUATIONS = 3
MAX_FORBIDDEN_RETRIES = 2

_FORBIDDEN_PATTERN = re.compile(r'\bos\s*\.\s*(?:time|date|clock|execute|getenv|remove|rename|exit)')

_FORBIDDEN_REGEN_MSG = (
    "Your code uses os.time/os.date which are FORBIDDEN in this runtime. "
    "Rewrite the ENTIRE solution without os.* — compute epoch manually using arithmetic: "
    "count days from 1970 with leap year handling, add month days, then hours/minutes/seconds. "
    "Return ONLY the corrected code in a ```lua block."
)


def _extract_lua(text: str) -> str | None:
    for pat in [r"```lua\s*\n(.*?)```", r"```\s*\n(.*?)```"]:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return None


def _extract_lua_open(text: str) -> str | None:
    """Extract code from an unclosed fenced block (truncated output)."""
    m = re.search(r"```lua\s*\n(.+)", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.+)", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _fallback_extract(text: str) -> str:
    """Extract code-like lines when no fenced block is found."""
    lines = []
    for line in text.strip().splitlines():
        s = line.strip()
        if not s or s.startswith("```") or s.startswith("---"):
            continue
        if any(s.lower().startswith(w) for w in [
            "here", "this", "the ", "note", "below", "above",
            "вот", "этот", "данный", "ниже",
        ]):
            continue
        lines.append(line)
    return "\n".join(lines)


def _clean_code(code: str) -> str:
    code = code.strip()
    m = re.match(r'^lua\s*\{(.*)\}\s*lua$', code, re.DOTALL)
    if m:
        code = m.group(1).strip()
    if (code.startswith('"') and code.endswith('"')) or (code.startswith("'") and code.endswith("'")):
        code = code[1:-1]
    code = re.sub(r'\bprint\((.+?)\)\s*$', r'return \1', code)
    return code


def _build_rag_context(user_query: str) -> str:
    chunks = retrieve(user_query, top_k=3)
    if chunks:
        return "\n=== RELEVANT DOMAIN KNOWLEDGE ===\n" + "\n---\n".join(chunks) + "\n"
    return ""


def is_truncated(code: str) -> bool:
    """Detect if Lua code was cut off mid-generation by the token limit."""
    if not code or not code.strip():
        return False

    stripped = code.rstrip()

    # Ends with an assignment operator, comma, concatenation, opening paren/brace
    trailing_patterns = [
        r'=\s*$',           # x =
        r',\s*$',           # trailing comma
        r'\.\.\s*$',        # string concat
        r'\(\s*$',          # open paren
        r'\{\s*$',          # open brace
        r'\bthen\s*$',      # then without body
        r'\bdo\s*$',        # do without body
        r'\belse\s*$',      # else without body
        r'\bfunction\s*\(.*\)\s*$',  # function declaration without body
    ]
    for pat in trailing_patterns:
        if re.search(pat, stripped):
            return True

    # Unbalanced block keywords: function/if/for/while need matching end
    openers = len(re.findall(r'\b(?:function|if|for|while|repeat)\b', stripped))
    closers = len(re.findall(r'\bend\b', stripped))
    if openers > closers:
        return True

    # No return statement at all (most Lua scripts need one)
    if 'return ' not in stripped and not stripped.endswith('return'):
        if stripped.count('\n') >= 3:
            return True

    return False


class CoderAgent(BaseAgent):
    def __init__(self, llm_call: LLMCallFn | None = None) -> None:
        super().__init__(system_prompt="", llm_call=llm_call)

    async def generate_simple(self, user_prompt: str) -> str:
        """Single-shot generation with auto-continuation for truncated output."""
        rag = _build_rag_context(user_prompt)
        prompt = CODER_PROMPT.format(rag_context=rag)
        self.system_prompt = prompt
        response = await self.call(user_prompt)
        code = self._extract_and_clean(response, allow_open=True)
        code = await self._sanitize_forbidden(code, user_prompt)
        code = await self._auto_continue(code, prompt)
        return code

    async def generate_step(
        self,
        user_prompt: str,
        step_description: str,
        existing_code: str = "",
    ) -> str:
        """Generate code for one step of a complex task."""
        rag = _build_rag_context(user_prompt)
        prompt = CODER_STEP_PROMPT.format(
            rag_context=rag,
            existing_code=existing_code or "(none yet)",
            step_description=step_description,
        )
        self.system_prompt = prompt
        response = await self.call(user_prompt)
        code = self._extract_and_clean(response, allow_open=True)
        code = await self._sanitize_forbidden(code, user_prompt)
        code = await self._auto_continue(code, prompt)
        return code

    async def fix(self, user_prompt: str, code: str, feedback: str, test_errors: str) -> str:
        """Fix code based on judge feedback."""
        from app.agent.prompts import FIX_WITH_FEEDBACK_TEMPLATE
        rag = _build_rag_context(user_prompt)
        self.system_prompt = CODER_PROMPT.format(rag_context=rag)
        fix_request = FIX_WITH_FEEDBACK_TEMPLATE.format(
            task=user_prompt,
            code=code,
            feedback=feedback,
            test_errors=test_errors,
        )
        response = await self.call(fix_request)
        code = self._extract_and_clean(response, allow_open=True)
        code = await self._sanitize_forbidden(code, user_prompt)
        code = await self._auto_continue(code, self.system_prompt)
        return code

    async def _sanitize_forbidden(self, code: str, user_prompt: str) -> str:
        """If code uses os.time/os.date, immediately re-request without wasting Judge iterations."""
        for attempt in range(MAX_FORBIDDEN_RETRIES):
            if not _FORBIDDEN_PATTERN.search(code):
                return code
            logger.warning("Forbidden os.* detected (attempt %d), re-requesting...", attempt + 1)
            response = await self.call(user_prompt + "\n\n" + _FORBIDDEN_REGEN_MSG)
            code = self._extract_and_clean(response, allow_open=True)
        return code

    async def _auto_continue(self, code: str, system_prompt: str) -> str:
        """Detect truncated output and request continuation up to MAX_CONTINUATIONS times."""
        for i in range(MAX_CONTINUATIONS):
            if not is_truncated(code):
                break

            logger.info("Truncation detected (attempt %d), requesting continuation...", i + 1)

            lines = code.strip().splitlines()
            last_n = lines[-10:] if len(lines) > 10 else lines
            continue_request = CONTINUE_PROMPT.format(
                total_lines=len(lines),
                last_lines="\n".join(last_n),
                last_line=lines[-1].strip() if lines else "",
            )
            self.system_prompt = system_prompt
            continuation = await self.call(continue_request)

            cont_clean = continuation.strip()
            for fence in ["```lua", "```"]:
                if cont_clean.startswith(fence):
                    cont_clean = cont_clean[len(fence):].strip()
            if cont_clean.endswith("```"):
                cont_clean = cont_clean[:-3].strip()

            cont_clean = _deduplicate_continuation(code, cont_clean)

            if not cont_clean:
                break

            code = code + "\n" + cont_clean

        return _clean_code(code)

    @staticmethod
    def _extract_and_clean(response: str, allow_open: bool = False) -> str:
        code = _extract_lua(response)
        if not code and allow_open:
            code = _extract_lua_open(response)
        if not code:
            code = _fallback_extract(response)
        return code.strip() if code else response.strip()


def _deduplicate_continuation(existing: str, continuation: str) -> str:
    """Remove lines from continuation that duplicate existing code.

    Handles three cases:
    1. Tail/head overlap (model repeats the end of existing before continuing)
    2. Whole-block regeneration (model rewrites the entire function from scratch)
    3. Scattered duplicates (individual lines already present in existing)
    """
    existing_lines = existing.strip().splitlines()
    cont_lines = continuation.strip().splitlines()

    if not cont_lines:
        return ""

    # --- Case 1: tail/head overlap ---
    max_overlap = min(len(existing_lines), len(cont_lines))
    overlap = 0
    for n in range(1, max_overlap + 1):
        tail = [l.strip() for l in existing_lines[-n:]]
        head = [l.strip() for l in cont_lines[:n]]
        if tail == head:
            overlap = n

    if overlap > 0:
        cont_lines = cont_lines[overlap:]

    if not cont_lines:
        return ""

    # --- Case 2: whole-block regeneration detection ---
    existing_set = {l.strip() for l in existing_lines if l.strip()}
    non_trivial_cont = [l for l in cont_lines if l.strip() and l.strip() not in ("end", "return", "else", "then")]
    if non_trivial_cont:
        dup_count = sum(1 for l in non_trivial_cont if l.strip() in existing_set)
        dup_ratio = dup_count / len(non_trivial_cont)
        if dup_ratio > 0.6:
            # Most of the "continuation" already exists — keep only truly new lines
            new_lines = []
            for l in cont_lines:
                if l.strip() not in existing_set or l.strip() in ("end",):
                    new_lines.append(l)
            cont_lines = new_lines

    return "\n".join(cont_lines)
