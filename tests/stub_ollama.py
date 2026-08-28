"""A tiny fake Ollama so the suite (and the browser) can run without a model."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

REPLY_CHUNKS = [
    "<th", "ink>The user said hello. Keep it short.</think>",
    "\n\nHello", ", I am **JARVIS**", ", running locally.\n\n",
    "```python\nprint('hi')\n```\n",
]


def build_stub(chunks: list[str] | None = None) -> FastAPI:
    app = FastAPI()
    pieces = chunks if chunks is not None else REPLY_CHUNKS

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        return {"version": "0.0.0-stub"}

    @app.get("/api/tags")
    async def tags() -> dict[str, list[dict]]:
        return {"models": [
            {"name": "qwen3:4b", "size": 2600000000,
             "details": {"parameter_size": "4.0B", "quantization_level": "Q4_K_M",
                         "family": "qwen3"}},
            {"name": "llama3.2:3b", "size": 2000000000,
             "details": {"parameter_size": "3.2B", "quantization_level": "Q4_K_M",
                         "family": "llama"}},
        ]}

    @app.get("/api/ps")
    async def ps() -> dict[str, list[dict]]:
        return {"models": [{"name": "qwen3:4b"}]}

    @app.post("/api/chat")
    async def chat(request: Request):
        payload = await request.json()
        if payload.get("model") == "missing:1b":
            return JSONResponse(status_code=404, content={"error": "model not found"})
        if not payload.get("messages"):
            return JSONResponse({"model": payload["model"], "done": True})

        async def generate():
            for piece in pieces:
                await asyncio.sleep(0.02)
                yield json.dumps({"model": payload["model"],
                                  "message": {"role": "assistant", "content": piece},
                                  "done": False}) + "\n"
            yield json.dumps({"model": payload["model"], "message": {"role": "assistant",
                                                                     "content": ""},
                              "done": True, "eval_count": 42,
                              "eval_duration": 3_000_000_000,
                              "prompt_eval_count": 11}) + "\n"

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_stub(), host="127.0.0.1", port=11434, log_level="warning")
