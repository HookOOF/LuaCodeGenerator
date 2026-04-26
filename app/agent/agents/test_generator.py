"""Test generator agent: produces Lua assert statements for generated code."""

from __future__ import annotations

import re
import logging

from app.agent.agents.base import BaseAgent, LLMCallFn
from app.agent.prompts import TEST_GENERATOR_PROMPT

logger = logging.getLogger(__name__)


class TestGeneratorAgent(BaseAgent):
    def __init__(self, llm_call: LLMCallFn | None = None, num_predict: int | None = None) -> None:
        super().__init__(system_prompt=TEST_GENERATOR_PROMPT, llm_call=llm_call, num_predict=num_predict)

    async def generate_tests(
        self,
        user_prompt: str,
        code: str,
        json_context_str: str,
    ) -> str:
        """Generate Lua assert statements for the given code."""
        user_content = (
            f"=== TASK ===\n{user_prompt}\n\n"
            f"=== JSON CONTEXT ===\n{json_context_str}\n\n"
            f"=== GENERATED CODE ===\n```lua\n{code}\n```"
        )
        response = await self.call(user_content)
        return self._clean(response)

    @staticmethod
    def _clean(response: str) -> str:
        """Extract only assert(...) lines from the response."""
        # If wrapped in code fences, extract content
        m = re.search(r"```(?:lua)?\s*\n(.*?)```", response, re.DOTALL)
        text = m.group(1) if m else response

        lines = []
        for line in text.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("assert(") or stripped.startswith("assert ("):
                lines.append(stripped)
            elif stripped.startswith("-- "):
                lines.append(stripped)

        if not lines:
            return 'assert(_result ~= nil, "result is nil, got: " .. tostring(_result))'

        return "\n".join(lines)
