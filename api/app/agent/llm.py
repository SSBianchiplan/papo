"""Fronteira com o modelo. Interface mínima para o motor poder ser testado com um modelo falso."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

OnText = Callable[[str], Awaitable[None]]


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class TurnResult:
    content: list[dict[str, Any]]
    stop_reason: str
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLM(Protocol):
    async def turn(self, *, model: str, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None, tool_choice: dict[str, Any] | None,
                   max_tokens: int, on_text: OnText) -> TurnResult: ...

    async def complete(self, *, model: str, prompt: str, max_tokens: int = 200) -> tuple[str, int, int]: ...


class AnthropicLLM:
    def __init__(self, api_key: str, workspace_id: str = "") -> None:
        from anthropic import AsyncAnthropic

        # chave que não pertence a um workspace só exige o cabeçalho em toda chamada
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = AsyncAnthropic(api_key=api_key, max_retries=2, timeout=300, default_headers=headers)

    async def check(self, model: str) -> dict[str, Any]:
        """Valida a chave de ponta a ponta: lista os modelos e faz uma chamada mínima (centavos de centavo)."""
        page = await self.client.models.list(limit=50)
        ids = [m.id for m in page.data]
        r = await self.client.messages.create(model=model, max_tokens=8, messages=[{"role": "user", "content": "Responda só: ok"}])
        return {"models": ids, "model_tested": r.model, "input_tokens": r.usage.input_tokens or 0, "output_tokens": r.usage.output_tokens or 0}

    async def turn(self, *, model: str, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None, tool_choice: dict[str, Any] | None,
                   max_tokens: int, on_text: OnText) -> TurnResult:
        kwargs: dict[str, Any] = {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens}
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
        async with self.client.messages.stream(**kwargs) as stream:
            async for delta in stream.text_stream:
                await on_text(delta)
            final = await stream.get_final_message()
        content: list[dict[str, Any]] = []
        uses: list[ToolUse] = []
        text = ""
        for b in final.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
                text += b.text
            elif b.type in ("thinking", "redacted_thinking"):
                # modelos com raciocínio sempre ligado (Sonnet 5.5, Opus 5.5): o bloco volta intacto na próxima volta da
                # ferramenta, senão a API recusa a continuação
                content.append(b.model_dump(exclude_none=True))
            elif b.type == "tool_use":
                inp = b.input if isinstance(b.input, dict) else {}
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": inp})
                uses.append(ToolUse(b.id, b.name, inp))
        u = final.usage
        tokens_in = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        return TurnResult(content=content, stop_reason=str(final.stop_reason), text=text, tool_uses=uses,
                          input_tokens=tokens_in, output_tokens=u.output_tokens or 0, model=final.model)

    async def complete(self, *, model: str, prompt: str, max_tokens: int = 200) -> tuple[str, int, int]:
        r = await self.client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in r.content if b.type == "text")
        return text, r.usage.input_tokens or 0, r.usage.output_tokens or 0


class EchoLLM:
    """Modelo de desenvolvimento: sem rede, sem chave. Lista os arquivos uma vez e responde ecoando."""

    async def turn(self, *, model: str, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None, tool_choice: dict[str, Any] | None,
                   max_tokens: int, on_text: OnText) -> TurnResult:
        import asyncio

        if tools and not any(isinstance(m["content"], list) and m["content"] and m["content"][0].get("type") == "tool_result" for m in messages):
            return TurnResult(content=[{"type": "tool_use", "id": "echo1", "name": "listar_documentos", "input": {}}],
                              stop_reason="tool_use", text="", tool_uses=[ToolUse("echo1", "listar_documentos", {})], input_tokens=10, output_tokens=5)
        last = next((m for m in reversed(messages) if m["role"] == "user" and isinstance(m["content"], str)), {"content": ""})
        text = f"(modo eco · {model}) Recebi: {str(last['content'])[:300]}"
        for i in range(0, len(text), 12):
            await on_text(text[i:i + 12])
            await asyncio.sleep(0.03)
        return TurnResult(content=[{"type": "text", "text": text}], stop_reason="end_turn", text=text, input_tokens=20, output_tokens=len(text) // 4)

    async def complete(self, *, model: str, prompt: str, max_tokens: int = 200) -> tuple[str, int, int]:
        return "[]", 1, 1


class LLMNotConfigured(Exception):
    """ANTHROPIC_API_KEY ausente: a execução falha com mensagem legível, sem chamar a rede."""


class UnconfiguredLLM:
    async def turn(self, *, model: str, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None, tool_choice: dict[str, Any] | None,
                   max_tokens: int, on_text: OnText) -> TurnResult:
        raise LLMNotConfigured("ANTHROPIC_API_KEY ausente")

    async def complete(self, *, model: str, prompt: str, max_tokens: int = 200) -> tuple[str, int, int]:
        raise LLMNotConfigured("ANTHROPIC_API_KEY ausente")
