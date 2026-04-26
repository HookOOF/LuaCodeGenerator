from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

from app.config import settings
from app.agent.token_counter import estimate_tokens
from app.agent.prompts import SUMMARIZE_PROMPT, SUMMARY_INJECTION

logger = logging.getLogger(__name__)


@dataclass
class ContextWindow:
    messages: list[dict]
    summary: str | None = None
    summarized_count: int = 0


class ContextManager:
    def __init__(
        self,
        llm_call: Callable[..., Awaitable[str]],
    ) -> None:
        self._llm_call = llm_call

    async def prepare(
        self,
        system_prompt: str,
        chat_history: list[dict],
        existing_summary: str | None,
        summarized_count: int,
    ) -> ContextWindow:
        num_ctx = settings.ollama_num_ctx
        num_predict = settings.ollama_num_predict
        input_budget = int(
            (num_ctx - num_predict) * settings.context_reserve_ratio
        )

        system_tokens = estimate_tokens(system_prompt)
        summary_reserve = settings.summary_max_tokens
        history_budget = input_budget - system_tokens - summary_reserve

        if history_budget < 0:
            history_budget = 0

        kept: list[dict] = []
        kept_tokens = 0
        split_index = len(chat_history)

        for i in range(len(chat_history) - 1, -1, -1):
            msg_tokens = estimate_tokens(chat_history[i]["content"]) + 4
            if kept_tokens + msg_tokens > history_budget:
                split_index = i + 1
                break
            kept_tokens += msg_tokens
            kept.insert(0, chat_history[i])
        else:
            split_index = 0

        if split_index == 0:
            return ContextWindow(
                messages=[{"role": "system", "content": system_prompt}] + chat_history,
                summary=existing_summary,
                summarized_count=summarized_count,
            )

        overflow = chat_history[:split_index]

        new_overflow = overflow[summarized_count:] if summarized_count < len(overflow) else []

        if not new_overflow and existing_summary:
            summary_text = existing_summary
            new_summarized_count = summarized_count
        else:
            summary_text = await self._summarize(existing_summary, new_overflow)
            new_summarized_count = split_index

        summary_block = SUMMARY_INJECTION.format(summary=summary_text)
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": summary_block},
        ]
        messages.extend(kept)

        logger.info(
            "Context managed: %d messages summarized, %d kept verbatim, "
            "summary ~%d tokens",
            split_index,
            len(kept),
            estimate_tokens(summary_block),
        )

        return ContextWindow(
            messages=messages,
            summary=summary_text,
            summarized_count=new_summarized_count,
        )

    async def _summarize(
        self,
        existing_summary: str | None,
        new_messages: list[dict],
    ) -> str:
        conversation_lines: list[str] = []
        for msg in new_messages:
            role = msg["role"].capitalize()
            content = msg["content"]
            if len(content) > 300:
                content = content[:300] + "..."
            conversation_lines.append(f"{role}: {content}")
        conversation_text = "\n".join(conversation_lines)

        previous_section = ""
        if existing_summary:
            previous_section = (
                f"Previous summary:\n{existing_summary}\n\n"
            )

        prompt_text = SUMMARIZE_PROMPT.format(
            previous_summary=previous_section,
            conversation=conversation_text,
        )

        messages = [
            {"role": "system", "content": "You are a concise summarizer."},
            {"role": "user", "content": prompt_text},
        ]
        result = await self._llm_call(messages)

        max_chars = settings.summary_max_tokens * 3
        if len(result) > max_chars:
            result = result[:max_chars]

        return result.strip()
