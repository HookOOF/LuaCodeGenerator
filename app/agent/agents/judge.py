"""Judge agent: evaluates code quality based on syntax validation and test results."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

from app.agent.agents.base import BaseAgent, LLMCallFn
from app.agent.prompts import JUDGE_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class JudgeVerdict:
    passed: bool
    reason: str = ""
    fix_instruction: str = ""


class JudgeAgent(BaseAgent):
    def __init__(self, llm_call: LLMCallFn | None = None, num_predict: int | None = None) -> None:
        super().__init__(system_prompt=JUDGE_PROMPT, llm_call=llm_call, num_predict=num_predict)

    async def evaluate(
        self,
        code: str,
        syntax_result: str,
        test_result: str,
    ) -> JudgeVerdict:
        user_content = (
            f"=== CODE ===\n```lua\n{code}\n```\n\n"
            f"=== SYNTAX VALIDATION ===\n{syntax_result}\n\n"
            f"=== TEST EXECUTION ===\n{test_result}"
        )
        response = await self.call(user_content)
        return self._parse(response)

    @staticmethod
    def _parse(response: str) -> JudgeVerdict:
        text = response.strip()

        if text.upper().startswith("PASS"):
            return JudgeVerdict(passed=True)

        reason = ""
        fix_instruction = ""
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.upper().startswith("REASON:"):
                reason = re.sub(r"^REASON:\s*", "", line_s, flags=re.IGNORECASE)
            elif line_s.upper().startswith("FIX:"):
                fix_instruction = re.sub(r"^FIX:\s*", "", line_s, flags=re.IGNORECASE)

        return JudgeVerdict(
            passed=False,
            reason=reason or text[:200],
            fix_instruction=fix_instruction,
        )
