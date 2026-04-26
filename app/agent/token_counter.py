from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Conservative heuristic: ~1 token per 3 chars for mixed ru/en text."""
    return max(1, len(text) // 3)


def estimate_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(msg["content"]) + 4
    return total
