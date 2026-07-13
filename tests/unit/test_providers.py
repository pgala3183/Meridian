"""Unit tests for multimodal provider adapters (mocked clients only)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from meridian.providers import (
    AudioInput,
    ImageInput,
    ProviderCapabilityError,
    ProviderConfig,
    ProviderName,
    ProviderRequest,
    available_providers,
    create_provider,
    get_default_provider,
)
from meridian.providers.anthropic_provider import AnthropicProvider
from meridian.providers.gemini_provider import GeminiProvider
from meridian.providers.openai_provider import OpenAIProvider

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_available_providers_includes_all_three() -> None:
    names = available_providers()
    assert names == ["gemini", "openai", "anthropic"]


def test_create_provider_defaults_to_gemini() -> None:
    client = MagicMock()
    provider = create_provider(
        ProviderConfig(name=ProviderName.GEMINI, project="demo-project"),
        client=client,
    )
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"


def test_get_default_provider_is_gemini() -> None:
    client = MagicMock()
    provider = get_default_provider(client=client)
    assert isinstance(provider, GeminiProvider)


def test_create_provider_openai_and_anthropic() -> None:
    assert isinstance(
        create_provider(ProviderConfig(name=ProviderName.OPENAI), client=MagicMock()),
        OpenAIProvider,
    )
    assert isinstance(
        create_provider(ProviderConfig(name=ProviderName.ANTHROPIC), client=MagicMock()),
        AnthropicProvider,
    )


def test_gemini_requires_project_without_injected_client() -> None:
    with pytest.raises(ValueError, match="project"):
        GeminiProvider(ProviderConfig(name=ProviderName.GEMINI, project=None))


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def _gemini_generate_response(text: str) -> Any:
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text=text)]))],
    )


def _gemini_embed_response(values: list[float]) -> Any:
    return SimpleNamespace(embeddings=[SimpleNamespace(values=values)])


@pytest.fixture
def gemini_client() -> MagicMock:
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=_gemini_generate_response("hello from gemini [clip-1]")
    )
    client.aio.models.embed_content = AsyncMock(
        return_value=_gemini_embed_response([0.1, 0.2, 0.3])
    )
    return client


@pytest.mark.asyncio
async def test_gemini_transcribe(gemini_client: MagicMock) -> None:
    provider = GeminiProvider(
        ProviderConfig(project="demo", generation_model="gemini-2.0-flash"),
        client=gemini_client,
    )
    result = await provider.transcribe(AudioInput(data=b"RIFF", mime_type="audio/wav"))
    assert result.text == "hello from gemini [clip-1]"
    assert result.model == "gemini-2.0-flash"
    gemini_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_embed_text(gemini_client: MagicMock) -> None:
    provider = GeminiProvider(ProviderConfig(project="demo"), client=gemini_client)
    result = await provider.embed_text("chunk text")
    assert result.vector == (0.1, 0.2, 0.3)
    assert result.dimensions == 3
    gemini_client.aio.models.embed_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_answer_question_with_image(gemini_client: MagicMock) -> None:
    provider = GeminiProvider(ProviderConfig(project="demo"), client=gemini_client)
    result = await provider.answer_question(
        context="The speaker mentions latency.",
        question="What is mentioned?",
        images=[ImageInput(data=b"\xff\xd8", mime_type="image/jpeg")],
    )
    assert "gemini" in result.answer
    assert result.citations == ("clip-1",)
    call_kwargs = gemini_client.aio.models.generate_content.await_args.kwargs
    parts = call_kwargs["contents"][0]["parts"]
    assert any("inline_data" in part for part in parts)


@pytest.mark.asyncio
async def test_gemini_estimate_cost() -> None:
    provider = GeminiProvider(ProviderConfig(project="demo"), client=MagicMock())
    estimate = await provider.estimate_cost(
        ProviderRequest(operation="answer_question", input_tokens=1_000_000, output_tokens=500_000)
    )
    assert estimate.estimated_usd > 0
    assert "text_input" in estimate.breakdown


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.fixture
def openai_client() -> MagicMock:
    client = MagicMock()
    client.audio = MagicMock()
    client.audio.transcriptions = MagicMock()
    client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="openai transcript", language="en")
    )
    client.embeddings = MagicMock()
    client.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.4, 0.5])])
    )
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="openai grounded answer"))]
        )
    )
    return client


@pytest.mark.asyncio
async def test_openai_transcribe(openai_client: MagicMock) -> None:
    provider = OpenAIProvider(ProviderConfig(name=ProviderName.OPENAI), client=openai_client)
    result = await provider.transcribe(AudioInput(data=b"audio-bytes", mime_type="audio/mpeg"))
    assert result.text == "openai transcript"
    assert result.language == "en"
    openai_client.audio.transcriptions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_embed_and_answer(openai_client: MagicMock) -> None:
    provider = OpenAIProvider(ProviderConfig(name=ProviderName.OPENAI), client=openai_client)
    embedding = await provider.embed_text("hello")
    assert embedding.vector == (0.4, 0.5)
    answer = await provider.answer_question(
        "context",
        "question?",
        images=[ImageInput(data=b"img", mime_type="image/png")],
    )
    assert answer.answer == "openai grounded answer"
    openai_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_estimate_cost_transcribe() -> None:
    provider = OpenAIProvider(ProviderConfig(name=ProviderName.OPENAI), client=MagicMock())
    estimate = await provider.estimate_cost(
        ProviderRequest(operation="transcribe", audio_seconds=120.0)
    )
    assert estimate.breakdown["audio"] > 0
    assert estimate.breakdown["text_input"] == 0


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_client() -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="anthropic answer")]
        )
    )
    return client


@pytest.mark.asyncio
async def test_anthropic_answer_question(anthropic_client: MagicMock) -> None:
    provider = AnthropicProvider(
        ProviderConfig(name=ProviderName.ANTHROPIC),
        client=anthropic_client,
    )
    result = await provider.answer_question(
        "Only discuss cats.",
        "What animal?",
        images=[ImageInput(data=b"img", mime_type="image/jpeg")],
    )
    assert result.answer == "anthropic answer"
    anthropic_client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_anthropic_unsupported_capabilities() -> None:
    provider = AnthropicProvider(
        ProviderConfig(name=ProviderName.ANTHROPIC),
        client=MagicMock(),
    )
    with pytest.raises(ProviderCapabilityError, match="transcription"):
        await provider.transcribe(AudioInput(data=b"x"))
    with pytest.raises(ProviderCapabilityError, match="embeddings"):
        await provider.embed_text("nope")


@pytest.mark.asyncio
async def test_anthropic_estimate_cost() -> None:
    provider = AnthropicProvider(
        ProviderConfig(name=ProviderName.ANTHROPIC),
        client=MagicMock(),
    )
    estimate = await provider.estimate_cost(
        ProviderRequest(
            operation="answer_question",
            input_tokens=1000,
            output_tokens=200,
            image_count=2,
        )
    )
    assert estimate.estimated_usd > 0
    assert estimate.breakdown["vision"] > 0
    with pytest.raises(ProviderCapabilityError):
        await provider.estimate_cost(ProviderRequest(operation="transcribe"))
