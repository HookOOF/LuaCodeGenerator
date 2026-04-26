"""Multi-agent pipeline orchestrator.

Flow (both /generate and /chat):
  User request
    -> Planner (SIMPLE / COMPLEX / QUESTION)
    -> Coder(s)  (single-shot or multi-part + Assembler, with auto-continuation)
    -> Reviewer   (deterministic code cleanup)
    -> Validator  (syntax)
    -> Test Generator + Executor (Lua asserts)
    -> Judge      (PASS / FAIL — skipped when syntax+tests both pass)
    -> Fix loop   (up to MAX_FIX_ITERATIONS retries, with escalating context)
"""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass

from app.config import settings
from app.agent.agents.base import shared_llm_call, LLMCallFn
from app.agent.agents.planner import PlannerAgent
from app.agent.agents.coder import CoderAgent
from app.agent.agents.assembler import AssemblerAgent
from app.agent.agents.test_generator import TestGeneratorAgent
from app.agent.agents.judge import JudgeAgent
from app.agent.agents.reviewer import review_and_fix
from app.agent.validator import validate_lua
from app.agent.executor import extract_json_context, run_lua_with_tests
from app.agent.context_manager import ContextManager
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.rag import retrieve
from app.agent.template_matcher import try_match

logger = logging.getLogger(__name__)

MAX_FIX_ITERATIONS = 3


@dataclass
class PipelineResult:
    code: str
    full_response: str
    is_valid: bool | None = None
    is_question: bool = False
    iterations: int = 1
    updated_summary: str | None = None
    summarized_count: int = 0


class AgentPipeline:
    def __init__(self) -> None:
        self._llm_call: LLMCallFn = shared_llm_call
        self.planner = PlannerAgent(llm_call=self._llm_call, num_predict=64)
        self.coder = CoderAgent(llm_call=self._llm_call)
        self.assembler = AssemblerAgent(llm_call=self._llm_call)
        self.test_gen = TestGeneratorAgent(llm_call=self._llm_call, num_predict=192)
        self.judge = JudgeAgent(llm_call=self._llm_call, num_predict=96)
        self.context_manager = ContextManager(llm_call=self._llm_call)

    # ------------------------------------------------------------------
    # Public entry point (kept compatible with main.py and chat API)
    # ------------------------------------------------------------------

    async def run(
        self,
        user_prompt: str,
        chat_history: list[dict] | None = None,
        existing_summary: str | None = None,
        summarized_count: int = 0,
    ) -> PipelineResult:
        if chat_history:
            return await self._run_chat(
                user_prompt, chat_history, existing_summary, summarized_count,
            )
        return await self._run_generate(user_prompt)

    # ------------------------------------------------------------------
    # Core multi-agent code generation (shared by /generate and /chat)
    # ------------------------------------------------------------------

    async def _generate_code(self, user_prompt: str) -> PipelineResult:
        """Run Planner -> Coder(s) -> Reviewer -> Validate -> Test -> Judge -> Fix loop."""
        json_ctx = extract_json_context(user_prompt)
        json_ctx_str = json.dumps(json_ctx, ensure_ascii=False) if json_ctx else "(no JSON context)"

        # --- 0. Template matching: instant result for well-known patterns ---
        tmpl = try_match(user_prompt, json_ctx)
        if tmpl:
            logger.info("Template match: %s — skipping LLM pipeline", tmpl.pattern_name)
            syntax = await validate_lua(tmpl.code)
            if syntax.is_valid:
                exec_result = await run_lua_with_tests(tmpl.code, json_ctx, "")
                if exec_result.success or not exec_result.error_summary:
                    return PipelineResult(
                        code=tmpl.code,
                        full_response=tmpl.code,
                        is_valid=True,
                        iterations=0,
                    )
            logger.info("Template code failed validation, falling through to LLM pipeline")

        # --- 1. Planner ---
        plan = await self.planner.analyze(user_prompt)
        logger.info("Planner decision: %s", plan.complexity)

        if plan.complexity == "QUESTION":
            return PipelineResult(
                code="",
                full_response=plan.question or "",
                is_question=True,
            )

        # --- 2. Coder (with auto-continuation built into CoderAgent) ---
        if plan.complexity == "COMPLEX" and plan.steps:
            code = await self._generate_complex(user_prompt, plan.steps)
        else:
            code = await self.coder.generate_simple(user_prompt)

        if not code.strip():
            return PipelineResult(code="", full_response="", is_valid=None)

        # --- 2.5. Deterministic Reviewer: fix common LLM mistakes ---
        code, reviewer_fixes = review_and_fix(code, user_prompt)
        if reviewer_fixes:
            logger.info("Reviewer applied: %s", reviewer_fixes)

        # --- 3. Validate + Test + (conditional Judge) + Fix loop ---
        best_code = code
        best_valid = None
        total_iterations = 1
        prev_error = ""

        for attempt in range(1 + MAX_FIX_ITERATIONS):
            syntax = await validate_lua(code)
            syntax_ok = syntax.is_valid
            syntax_str = "PASS" if syntax_ok else f"FAIL: {syntax.error}"

            test_assertions = await self.test_gen.generate_tests(
                user_prompt, code, json_ctx_str,
            )
            exec_result = await run_lua_with_tests(code, json_ctx, test_assertions)
            tests_ok = exec_result.tests_passed
            test_str = "PASS" if tests_ok else f"FAIL: {exec_result.error_summary or exec_result.stderr}"

            # Deterministic fast-path: if both syntax and tests pass, skip
            # the LLM Judge call entirely — saves time and VRAM.
            if syntax_ok and tests_ok:
                logger.info(
                    "Attempt %d: syntax=PASS tests=PASS -> auto-PASS (skipped Judge)",
                    attempt + 1,
                )
                return PipelineResult(
                    code=code,
                    full_response=code,
                    is_valid=True,
                    iterations=total_iterations,
                )

            # Only call the LLM Judge when there are failures to analyze
            verdict = await self.judge.evaluate(code, syntax_str, test_str)
            logger.info(
                "Attempt %d: syntax=%s tests=%s judge=%s",
                attempt + 1,
                "PASS" if syntax_ok else "FAIL",
                "PASS" if tests_ok else "FAIL",
                "PASS" if verdict.passed else "FAIL",
            )

            if syntax_ok:
                best_code = code
                best_valid = True

            if verdict.passed:
                return PipelineResult(
                    code=code,
                    full_response=code,
                    is_valid=True,
                    iterations=total_iterations,
                )

            if attempt < MAX_FIX_ITERATIONS:
                total_iterations += 1
                current_error = exec_result.error_summary or exec_result.stderr or syntax.error or ""

                # Escalating context: if the same error repeats, provide more
                # context to the fixer so it doesn't loop on the same mistake
                escalation = ""
                if current_error and current_error == prev_error:
                    escalation = (
                        "\nIMPORTANT: The previous fix attempt did NOT resolve this error. "
                        "Try a fundamentally different approach."
                    )

                feedback = verdict.reason
                if verdict.fix_instruction:
                    feedback += "\n" + verdict.fix_instruction
                feedback += escalation

                code = await self.coder.fix(
                    user_prompt,
                    code,
                    feedback=feedback,
                    test_errors=current_error,
                )
                # Run reviewer on fixed code too
                code, _ = review_and_fix(code, user_prompt)
                prev_error = current_error

        return PipelineResult(
            code=best_code,
            full_response=best_code,
            is_valid=best_valid,
            iterations=total_iterations,
        )

    async def _generate_complex(self, user_prompt: str, steps: list[str]) -> str:
        """Multi-part generation: one coder call per step, then assemble."""
        parts: list[str] = []
        accumulated = ""
        for step in steps:
            part = await self.coder.generate_step(
                user_prompt, step, existing_code=accumulated,
            )
            parts.append(part)
            accumulated += "\n" + part

        assembled = await self.assembler.assemble(parts, user_prompt)
        return assembled

    # ------------------------------------------------------------------
    # /generate path (stateless)
    # ------------------------------------------------------------------

    async def _run_generate(self, user_prompt: str) -> PipelineResult:
        return await self._generate_code(user_prompt)

    # ------------------------------------------------------------------
    # Chat path (with context management + multi-agent code generation)
    # ------------------------------------------------------------------

    async def _run_chat(
        self,
        user_prompt: str,
        chat_history: list[dict],
        existing_summary: str | None,
        summarized_count: int,
    ) -> PipelineResult:
        # Determine if this is a follow-up (fix/change) or new code request
        is_followup = _is_followup_request(user_prompt, chat_history)

        if is_followup:
            # Follow-ups need chat history context (previous code, corrections)
            return await self._run_chat_followup(
                user_prompt, chat_history, existing_summary, summarized_count,
            )

        # New code generation request: use the full multi-agent pipeline
        # (Planner, Coder with auto-continuation, Test, Judge)
        result = await self._generate_code(user_prompt)

        # Attach context management metadata
        ctx = await self.context_manager.prepare(
            system_prompt="",
            chat_history=chat_history,
            existing_summary=existing_summary,
            summarized_count=summarized_count,
        )
        result.updated_summary = ctx.summary
        result.summarized_count = ctx.summarized_count
        return result

    async def _run_chat_followup(
        self,
        user_prompt: str,
        chat_history: list[dict],
        existing_summary: str | None,
        summarized_count: int,
    ) -> PipelineResult:
        """Handle follow-up messages (fix, change, add) using chat history."""
        system_content = self._build_system_prompt(user_prompt)

        ctx = await self.context_manager.prepare(
            system_prompt=system_content,
            chat_history=chat_history,
            existing_summary=existing_summary,
            summarized_count=summarized_count,
        )
        messages = ctx.messages
        updated_summary = ctx.summary
        new_summarized_count = ctx.summarized_count

        response_text = await self._llm_call(messages)

        if _is_clarifying_question(response_text):
            return PipelineResult(
                code="",
                full_response=response_text,
                is_valid=None,
                is_question=True,
                iterations=1,
                updated_summary=updated_summary,
                summarized_count=new_summarized_count,
            )

        code = _extract_lua_code(response_text)
        if not code:
            code = _extract_lua_open(response_text)
        if not code:
            code = _fallback_extract(response_text)
        if not code:
            return PipelineResult(
                code=response_text.strip(),
                full_response=response_text,
                is_valid=None,
                iterations=1,
                updated_summary=updated_summary,
                summarized_count=new_summarized_count,
            )

        code = _clean_code(code)

        # Auto-continuation for truncated follow-up responses
        from app.agent.agents.coder import is_truncated
        from app.agent.prompts import CONTINUE_PROMPT
        for _attempt in range(3):
            if not is_truncated(code):
                break
            logger.info("Chat follow-up truncated, requesting continuation...")
            code_lines = code.strip().splitlines()
            last_n = code_lines[-10:] if len(code_lines) > 10 else code_lines
            cont_msg = CONTINUE_PROMPT.format(
                total_lines=len(code_lines),
                last_lines="\n".join(last_n),
                last_line=code_lines[-1].strip() if code_lines else "",
            )
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": cont_msg})
            response_text = await self._llm_call(messages)

            cont_code = _extract_lua_code(response_text)
            if not cont_code:
                cont_code = _extract_lua_open(response_text)
            if not cont_code:
                cont_code = _strip_fences(response_text)
            if cont_code:
                from app.agent.agents.coder import _deduplicate_continuation
                cont_code = _deduplicate_continuation(code, cont_code)
                if cont_code:
                    code = code + "\n" + cont_code

        code = _clean_code(code)

        # Apply deterministic reviewer to chat follow-up code too
        code, _ = review_and_fix(code, user_prompt)

        validation = await validate_lua(code)
        iterations = 1

        while not validation.is_valid and iterations < MAX_FIX_ITERATIONS + 1:
            iterations += 1
            from app.agent.prompts import FIX_PROMPT_TEMPLATE
            fix_content = FIX_PROMPT_TEMPLATE.format(code=code, error=validation.error)
            messages.append({"role": "assistant", "content": f"```lua\n{code}\n```"})
            messages.append({"role": "user", "content": fix_content})

            response_text = await self._llm_call(messages)
            new_code = _extract_lua_code(response_text)
            if not new_code:
                new_code = _fallback_extract(response_text)
            if new_code:
                code = _clean_code(new_code)
                code, _ = review_and_fix(code, user_prompt)
            validation = await validate_lua(code)

        return PipelineResult(
            code=code,
            full_response=response_text,
            is_valid=validation.is_valid,
            iterations=iterations,
            updated_summary=updated_summary,
            summarized_count=new_summarized_count,
        )

    def _build_system_prompt(self, user_query: str) -> str:
        context_chunks = retrieve(user_query, top_k=3)
        if context_chunks:
            rag_section = "\n=== RELEVANT DOMAIN KNOWLEDGE ===\n" + "\n---\n".join(context_chunks) + "\n"
        else:
            rag_section = ""
        return SYSTEM_PROMPT.format(rag_context=rag_section)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _is_followup_request(user_prompt: str, chat_history: list[dict]) -> bool:
    """Detect if the current message is a follow-up to previous code."""
    if len(chat_history) < 2:
        return False

    has_prior_assistant = any(m["role"] == "assistant" for m in chat_history[:-1])
    if not has_prior_assistant:
        return False

    prompt_lower = user_prompt.lower().strip()
    followup_markers = [
        "fix", "change", "add", "remove", "modify", "update", "replace",
        "исправь", "измени", "добавь", "убери", "удали", "поменяй",
        "замени", "обнови", "переделай", "доработай",
        "продолжай", "continue",
    ]
    return any(marker in prompt_lower for marker in followup_markers)


def _extract_lua_code(text: str) -> str | None:
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


def _strip_fences(text: str) -> str:
    """Remove code fences from text."""
    t = text.strip()
    for fence in ["```lua", "```"]:
        if t.startswith(fence):
            t = t[len(fence):].strip()
    if t.endswith("```"):
        t = t[:-3].strip()
    return t


def _fallback_extract(text: str) -> str | None:
    lines = text.strip().split("\n")
    code_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```") or stripped.startswith("---"):
            continue
        if any(stripped.lower().startswith(w) for w in [
            "here", "this", "the ", "note", "below", "above",
            "вот", "этот", "данный", "ниже",
        ]):
            continue
        code_lines.append(line)

    joined = "\n".join(code_lines)
    lua_keywords = ("return", "local", "function", "for ", "if ", "while ", "wf.", "end", "table.", "string.", "_utils")
    if code_lines and any(kw in joined for kw in lua_keywords):
        return joined
    return None


def _clean_code(code: str) -> str:
    code = code.strip()
    m = re.match(r'^lua\s*\{(.*)\}\s*lua$', code, re.DOTALL)
    if m:
        code = m.group(1).strip()
    if (code.startswith('"') and code.endswith('"')) or (code.startswith("'") and code.endswith("'")):
        code = code[1:-1]
    code = re.sub(r'\bprint\((.+?)\)\s*$', r'return \1', code)
    return code


def _is_clarifying_question(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "```" in stripped:
        return False
    lua_keywords = ("return ", "local ", "function ", "wf.", "for ", "if ", "table.", "_utils")
    if any(kw in stripped for kw in lua_keywords):
        return False
    if stripped.endswith("?"):
        return True
    question_markers = [
        "уточни", "clarify", "could you", "можете", "какой", "какие",
        "что именно", "what exactly", "какую", "какое", "укажите",
        "please specify", "which ", "что вы имеете",
    ]
    return any(kw in stripped.lower() for kw in question_markers)
