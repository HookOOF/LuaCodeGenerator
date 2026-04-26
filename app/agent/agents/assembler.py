"""Assembler agent: combines multi-part code into a single coherent script."""

from __future__ import annotations

import re
import logging

from app.agent.agents.base import BaseAgent, LLMCallFn
from app.agent.prompts import ASSEMBLER_PROMPT

logger = logging.getLogger(__name__)


class AssemblerAgent(BaseAgent):
    def __init__(self, llm_call: LLMCallFn | None = None) -> None:
        super().__init__(system_prompt=ASSEMBLER_PROMPT, llm_call=llm_call)

    async def assemble(self, parts: list[str], task_description: str) -> str:
        """Combine code parts into one script."""
        sections = []
        for i, part in enumerate(parts, 1):
            sections.append(f"-- PART {i} --\n{part}")
        combined_input = (
            f"=== ORIGINAL TASK ===\n{task_description}\n\n"
            f"=== CODE PARTS ===\n" + "\n\n".join(sections)
        )
        response = await self.call(combined_input)
        return self._extract(response)

    @staticmethod
    def _extract(response: str) -> str:
        for pat in [r"```lua\s*\n(.*?)```", r"```\s*\n(.*?)```"]:
            m = re.search(pat, response, re.DOTALL)
            if m:
                return m.group(1).strip()
        return response.strip()
