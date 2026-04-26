"""Base agent with shared LLM call logic."""

from __future__ import annotations

import logging
from typing import Callable, Awaitable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LLMCallFn = Callable[..., Awaitable[str]]

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=300.0)
    return _http_client


async def shared_llm_call(
    messages: list[dict],
    *,
    num_predict: int | None = None,
    temperature: float | None = None,
) -> str:
    """Shared LLM call with per-invocation overrides for num_predict and temperature."""
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": num_predict if num_predict is not None else settings.ollama_num_predict,
            "temperature": temperature if temperature is not None else 0.1,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
        },
    }
    client = _get_http_client()
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]


class BaseAgent:
    """Base class for all pipeline agents."""

    def __init__(
        self,
        system_prompt: str,
        llm_call: LLMCallFn | None = None,
        num_predict: int | None = None,
        temperature: float | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self._llm_call = llm_call or shared_llm_call
        self._num_predict = num_predict
        self._temperature = temperature

    async def call(self, user_content: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        return await self._llm_call(
            messages,
            num_predict=self._num_predict,
            temperature=self._temperature,
        )

    async def call_with_history(self, messages: list[dict]) -> str:
        full = [{"role": "system", "content": self.system_prompt}] + messages
        return await self._llm_call(
            full,
            num_predict=self._num_predict,
            temperature=self._temperature,
        )
