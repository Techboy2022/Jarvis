"""Thin async client around the Ollama HTTP API."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .config import Settings


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or answers with an error."""


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # One pooled client for the whole process: reconnecting per request
        # adds latency and can exhaust local ports during fast streaming.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def version(self) -> str:
        try:
            response = await self._client.get(self.settings.version_endpoint, timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"cannot reach Ollama at {self.settings.ollama_url}: {exc}") from exc
        return str(response.json().get("version", "unknown"))

    async def models(self) -> list[dict[str, Any]]:
        try:
            response = await self._client.get(self.settings.tags_endpoint, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"cannot list models: {exc}") from exc
        models = []
        for entry in response.json().get("models", []):
            details = entry.get("details") or {}
            models.append({
                "name": entry.get("name"),
                "size": entry.get("size"),
                "parameter_size": details.get("parameter_size"),
                "quantization": details.get("quantization_level"),
                "family": details.get("family"),
            })
        models.sort(key=lambda m: m["name"] or "")
        return models

    async def loaded(self) -> list[str]:
        """Models currently resident in RAM (``/api/ps``)."""
        try:
            response = await self._client.get(self.settings.ps_endpoint, timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError:
            return []
        return [m.get("name", "") for m in response.json().get("models", [])]

    async def warmup(self, model: str) -> None:
        """Load a model into RAM without generating anything.

        On a CPU-only laptop the first token of a cold model can take 20 s;
        pre-loading on startup and on model switch hides that cost.
        """
        payload = {
            "model": model,
            "messages": [],
            "stream": False,
            "keep_alive": self.settings.keep_alive,
        }
        try:
            await self._client.post(self.settings.chat_endpoint, json=payload, timeout=120.0)
        except httpx.HTTPError:
            pass

    async def chat(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Stream ``/api/chat`` and yield each decoded NDJSON object."""
        try:
            async with self._client.stream(
                "POST", self.settings.chat_endpoint, json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise OllamaError(_error_detail(response.status_code, body, payload["model"]))
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except httpx.HTTPError as exc:
            raise OllamaError(f"connection to Ollama failed: {exc}") from exc


def _error_detail(status: int, body: str, model: str) -> str:
    try:
        message = json.loads(body).get("error", body)
    except json.JSONDecodeError:
        message = body
    if status == 404:
        return f"model '{model}' is not installed — run: ollama pull {model}"
    return f"Ollama returned HTTP {status}: {message}".strip()
