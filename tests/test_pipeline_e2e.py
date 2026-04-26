"""End-to-end pipeline tests using the 8 public prompts.

These tests require a running Ollama instance with the configured model.
Skip them in CI or when Ollama is not available by setting:
    pytest -m "not e2e"
"""

import shutil

import pytest

from tests.conftest import PUBLIC_PROMPTS

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="session")]

HAS_LUA = shutil.which("lua5.4") is not None or shutil.which("lua") is not None


def _ollama_available() -> bool:
    try:
        import httpx
        from app.config import settings
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running",
)
skip_no_lua = pytest.mark.skipif(not HAS_LUA, reason="lua not installed")


@skip_no_ollama
@skip_no_lua
@pytest.mark.parametrize(
    "case",
    PUBLIC_PROMPTS,
    ids=[p["name"] for p in PUBLIC_PROMPTS],
)
async def test_generate_public_prompt(case):
    from app.agent.pipeline import AgentPipeline

    pipeline = AgentPipeline()
    result = await pipeline.run(case["prompt"])

    assert result.code, f"Empty code for {case['name']}"

    if result.is_question:
        pytest.skip(f"Pipeline asked a clarifying question for {case['name']}")

    for frag in case["expected_fragments"]:
        assert frag in result.code, (
            f"Expected fragment '{frag}' not found in code for {case['name']}:\n{result.code}"
        )
