"""Incremental splitter for ``<think>`` reasoning blocks.

Reasoning models (qwen3, deepseek-r1, ...) wrap their chain of thought in
``<think> ... </think>``. Ollama only reports it in a separate ``thinking``
field on recent versions, so we also have to strip it out of the token stream
ourselves — without ever emitting a half-written tag to the browser.
"""
from __future__ import annotations

OPEN = "<think>"
CLOSE = "</think>"


def _partial_tag_len(buffer: str, tag: str) -> int:
    """Length of the suffix of ``buffer`` that could still grow into ``tag``."""
    for size in range(min(len(tag) - 1, len(buffer)), 0, -1):
        if buffer[-size:] == tag[:size]:
            return size
    return 0


class ThinkSplitter:
    """Feed raw token chunks in, get ``(answer, reasoning)`` pairs out."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False
        self._seen_answer = False

    def feed(self, chunk: str) -> tuple[str, str]:
        self._buffer += chunk
        answer_parts: list[str] = []
        think_parts: list[str] = []

        while self._buffer:
            if self._in_think:
                end = self._buffer.find(CLOSE)
                if end == -1:
                    hold = _partial_tag_len(self._buffer, CLOSE)
                    emit = self._buffer[: len(self._buffer) - hold]
                    self._buffer = self._buffer[len(self._buffer) - hold:]
                    if emit:
                        think_parts.append(emit)
                    break
                think_parts.append(self._buffer[:end])
                self._buffer = self._buffer[end + len(CLOSE):]
                self._in_think = False
                continue

            start = self._buffer.find(OPEN)
            if start == -1:
                hold = _partial_tag_len(self._buffer, OPEN)
                emit = self._buffer[: len(self._buffer) - hold]
                self._buffer = self._buffer[len(self._buffer) - hold:]
                if emit:
                    answer_parts.append(emit)
                break
            if start:
                answer_parts.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(OPEN):]
            self._in_think = True

        answer = "".join(answer_parts)
        if not self._seen_answer:
            # Models often start the answer with the newlines that followed
            # </think>; drop that leading whitespace so the bubble looks clean.
            answer = answer.lstrip()
            if answer:
                self._seen_answer = True
        return answer, "".join(think_parts)

    def flush(self) -> tuple[str, str]:
        """Emit whatever is still buffered once the stream ends."""
        rest, self._buffer = self._buffer, ""
        if self._in_think:
            return "", rest
        return rest.lstrip() if not self._seen_answer else rest, ""
