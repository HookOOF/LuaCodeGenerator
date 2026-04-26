"""Planner agent: analyzes task complexity and decomposes if needed."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.agent.agents.base import BaseAgent, LLMCallFn
from app.agent.prompts import PLANNER_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class PlanResult:
    complexity: str  # "SIMPLE", "COMPLEX", "QUESTION"
    question: str | None = None
    steps: list[str] = field(default_factory=list)


class PlannerAgent(BaseAgent):
    def __init__(self, llm_call: LLMCallFn | None = None, num_predict: int | None = None) -> None:
        super().__init__(system_prompt=PLANNER_PROMPT, llm_call=llm_call, num_predict=num_predict)

    async def analyze(self, user_prompt: str) -> PlanResult:
        response = await self.call(user_prompt)
        return self._parse(response)

    @staticmethod
    def _parse(response: str) -> PlanResult:
        text = response.strip()

        if text.upper().startswith("QUESTION"):
            question = re.sub(r"^QUESTION\s*:\s*", "", text, flags=re.IGNORECASE)
            return PlanResult(complexity="QUESTION", question=question.strip())

        if text.upper().startswith("SIMPLE"):
            return PlanResult(complexity="SIMPLE")

        if text.upper().startswith("COMPLEX"):
            steps = []
            for line in text.splitlines()[1:]:
                step = re.sub(r"^STEP\s*\d+\s*:\s*", "", line.strip(), flags=re.IGNORECASE)
                if step:
                    steps.append(step)
            if not steps:
                return PlanResult(complexity="SIMPLE")
            return PlanResult(complexity="COMPLEX", steps=steps)

        # Fallback: if we can't parse, treat as simple
        logger.warning("Could not parse planner response, defaulting to SIMPLE: %s", text[:200])
        return PlanResult(complexity="SIMPLE")
