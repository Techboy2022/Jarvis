"""JARVIS — a local, private chat UI on top of Ollama."""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR, settings
from .ollama import OllamaClient, OllamaError
from .store import Store
from .thinking import ThinkSplitter

store = Store(settings.db_path)
client = OllamaClient(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    prefs = await store.get_prefs()
    # Warm the model in the background so the first question is not the one
    # that pays the cold-start cost.
    warm = asyncio.create_task(client.warmup(prefs.get("model", settings.model)))
    try:
        yield
    finally:
        warm.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await warm
        await client.aclose()
        store.close()


app = FastAPI(title="JARVIS", version="2.0.0", lifespan=lifespan)

TUNABLES = ("model", "system_prompt", "temperature", "top_p", "num_ctx",
            "num_predict", "num_thread", "keep_alive", "history_limit")


# --------------------------------------------------------------------- models


class ChatCreate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    pinned: bool | None = None


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None


class PrefsPatch(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    num_ctx: int | None = Field(default=None, ge=512, le=131072)
    num_predict: int | None = Field(default=None, ge=-1, le=32768)
    num_thread: int | None = Field(default=None, ge=1, le=64)
    keep_alive: str | None = None
    history_limit: int | None = Field(default=None, ge=0, le=200)


# -------------------------------------------------------------------- helpers


async def effective_settings() -> dict[str, Any]:
    prefs = await store.get_prefs()
    base = {key: getattr(settings, key) for key in TUNABLES}
    base.update({k: v for k, v in prefs.items() if k in TUNABLES and v is not None})
    return base


async def require_chat(chat_id: str) -> dict[str, Any]:
    chat = await store.get_chat_meta(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


def derive_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if len(title) > 48:
        title = title[:48].rsplit(" ", 1)[0] + "…"
    return title or "New chat"


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------- pages


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ----------------------------------------------------------------- system api


@app.get("/api/health")
async def health() -> dict[str, Any]:
    conf = await effective_settings()
    try:
        version = await client.version()
    except OllamaError as exc:
        return {"ok": False, "error": str(exc), "model": conf["model"],
                "ollama_url": settings.ollama_url}
    loaded = await client.loaded()
    return {
        "ok": True,
        "version": version,
        "ollama_url": settings.ollama_url,
        "model": conf["model"],
        "model_loaded": conf["model"] in loaded,
        "loaded_models": loaded,
    }


@app.get("/api/models")
async def models() -> dict[str, Any]:
    try:
        return {"models": await client.models()}
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/warmup")
async def warmup(payload: dict[str, str] | None = None) -> dict[str, bool]:
    conf = await effective_settings()
    model = (payload or {}).get("model") or conf["model"]
    asyncio.create_task(client.warmup(model))
    return {"started": True}


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    conf = await effective_settings()
    conf["ollama_url"] = settings.ollama_url
    return conf


@app.put("/api/settings")
async def put_settings(patch: PrefsPatch) -> dict[str, Any]:
    values = {k: v for k, v in patch.model_dump().items() if v is not None}
    if values:
        await store.set_prefs(values)
    if "model" in values:
        asyncio.create_task(client.warmup(values["model"]))
    return await effective_settings()


# ------------------------------------------------------------------ chats api


@app.get("/api/chats")
async def list_chats() -> dict[str, Any]:
    return {"chats": await store.list_chats()}


@app.post("/api/chats", status_code=201)
async def create_chat(payload: ChatCreate) -> dict[str, Any]:
    return await store.create_chat(
        title=payload.title or "New chat",
        model=payload.model,
        system_prompt=payload.system_prompt,
    )


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str) -> dict[str, Any]:
    chat = await store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@app.patch("/api/chats/{chat_id}")
async def patch_chat(chat_id: str, payload: ChatPatch) -> dict[str, Any]:
    await require_chat(chat_id)
    fields = payload.model_dump()
    if fields.get("pinned") is not None:
        fields["pinned"] = int(fields["pinned"])
    updated = await store.update_chat(chat_id, **fields)
    assert updated is not None
    return updated


@app.delete("/api/chats/{chat_id}", status_code=204, response_class=Response)
async def delete_chat(chat_id: str) -> Response:
    if not await store.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="chat not found")
    return Response(status_code=204)


@app.delete("/api/chats", status_code=200)
async def delete_all_chats() -> dict[str, int]:
    return {"deleted": await store.delete_all_chats()}


@app.get("/api/search")
async def search(q: str = "") -> dict[str, Any]:
    if not q.strip():
        return {"results": []}
    return {"results": await store.search(q.strip())}


@app.get("/api/chats/{chat_id}/export", response_class=PlainTextResponse)
async def export_chat(chat_id: str) -> PlainTextResponse:
    chat = await store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    lines = [f"# {chat['title']}", ""]
    for message in chat["messages"]:
        who = "You" if message["role"] == "user" else "JARVIS"
        lines += [f"## {who}", "", message["content"], ""]
    body = "\n".join(lines)
    filename = f"jarvis-{chat_id[:8]}.md"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------------------------------------------ streaming


async def run_turn(chat: dict[str, Any], overrides: dict[str, Any],
                   request: Request) -> AsyncIterator[str]:
    """Stream one assistant turn as server-sent events."""
    conf = await effective_settings()
    model = overrides.get("model") or chat.get("model") or conf["model"]
    system_prompt = (overrides.get("system_prompt") or chat.get("system_prompt")
                     or conf["system_prompt"])
    temperature = overrides.get("temperature")
    if temperature is None:
        temperature = conf["temperature"]

    history = await store.history(chat["id"], conf["history_limit"])
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, *history],
        "stream": True,
        "keep_alive": conf["keep_alive"],
        "options": {
            "temperature": temperature,
            "top_p": conf["top_p"],
            "num_ctx": conf["num_ctx"],
            "num_predict": conf["num_predict"],
            "num_thread": conf["num_thread"],
        },
    }

    splitter = ThinkSplitter()
    answer: list[str] = []
    reasoning: list[str] = []
    stats: dict[str, Any] = {}
    started = time.perf_counter()
    first_token_at: float | None = None
    stopped = False

    yield sse({"type": "start", "model": model, "chat_id": chat["id"]})

    try:
        async for chunk in client.chat(payload):
            if await request.is_disconnected():
                stopped = True
                break

            message = chunk.get("message") or {}
            # Recent Ollama versions separate reasoning; older ones inline it.
            native_thinking = message.get("thinking") or ""
            if native_thinking:
                reasoning.append(native_thinking)
                yield sse({"type": "think", "content": native_thinking})

            content = message.get("content") or ""
            if content:
                visible, thought = splitter.feed(content)
                if thought:
                    reasoning.append(thought)
                    yield sse({"type": "think", "content": thought})
                if visible:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    answer.append(visible)
                    yield sse({"type": "token", "content": visible})

            if chunk.get("done"):
                stats = _stats(chunk, started, first_token_at)
                break

        tail_visible, tail_thought = splitter.flush()
        if tail_thought:
            reasoning.append(tail_thought)
            yield sse({"type": "think", "content": tail_thought})
        if tail_visible:
            answer.append(tail_visible)
            yield sse({"type": "token", "content": tail_visible})

    except OllamaError as exc:
        text = "".join(answer).strip()
        if text:
            await store.add_message(chat["id"], "assistant", text,
                                    thinking="".join(reasoning).strip() or None, model=model)
        yield sse({"type": "error", "error": str(exc)})
        return
    except asyncio.CancelledError:
        stopped = True
        raise
    finally:
        text = "".join(answer).strip()
        if stopped and text:
            # Keep the partial answer when the user hits Stop or closes the tab;
            # shielded so a cancelled request still gets written.
            await asyncio.shield(asyncio.create_task(store.add_message(
                chat["id"], "assistant", text,
                thinking="".join(reasoning).strip() or None, model=model,
                stats={"stopped": True},
            )))

    if stopped:
        return

    text = "".join(answer).strip()
    if not text and reasoning:
        # Pure-reasoning reply (model never closed its think block): show it
        # rather than an empty bubble.
        text = "".join(reasoning).strip()
        reasoning = []
    stored = await store.add_message(
        chat["id"], "assistant", text,
        thinking="".join(reasoning).strip() or None, model=model, stats=stats or None,
    )
    yield sse({"type": "done", "message": stored, "stats": stats})


def _stats(chunk: dict[str, Any], started: float, first_token_at: float | None) -> dict[str, Any]:
    eval_count = chunk.get("eval_count") or 0
    eval_duration = chunk.get("eval_duration") or 0
    tps = (eval_count / (eval_duration / 1e9)) if eval_count and eval_duration else None
    return {
        "tokens": eval_count,
        "prompt_tokens": chunk.get("prompt_eval_count") or 0,
        "tokens_per_second": round(tps, 1) if tps else None,
        "first_token_seconds": round(first_token_at - started, 2) if first_token_at else None,
        "total_seconds": round(time.perf_counter() - started, 2),
    }


def stream_response(generator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/chats/{chat_id}/messages")
async def post_message(chat_id: str, payload: MessageRequest, request: Request) -> StreamingResponse:
    chat = await require_chat(chat_id)
    prompt = payload.message.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="message is empty")

    await store.add_message(chat_id, "user", prompt)
    if chat["title"] == "New chat":
        await store.update_chat(chat_id, title=derive_title(prompt))

    overrides = {
        "model": payload.model,
        "system_prompt": payload.system_prompt,
        "temperature": payload.temperature,
    }
    return stream_response(run_turn(chat, overrides, request))


@app.post("/api/chats/{chat_id}/regenerate")
async def regenerate(chat_id: str, request: Request) -> StreamingResponse:
    chat = await require_chat(chat_id)
    prompt = await store.truncate_from_last_user(chat_id)
    if prompt is None:
        raise HTTPException(status_code=409, detail="nothing to regenerate")
    await store.add_message(chat_id, "user", prompt)
    return stream_response(run_turn(chat, {}, request))


@app.exception_handler(OllamaError)
async def _ollama_error_handler(_: Request, exc: OllamaError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def main() -> None:
    import uvicorn

    uvicorn.run(
        "jarvis.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
