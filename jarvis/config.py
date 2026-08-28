"""Runtime configuration for JARVIS.

Every value can be overridden with an environment variable (or a .env file
loaded by ``run.sh`` / the systemd unit).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _default_threads() -> int:
    """Physical-core estimate.

    A T490 (i5-8265U / i7-8565U) has 4 physical cores and 8 logical ones.
    llama.cpp is memory-bandwidth bound, so using the hyperthreads costs
    throughput; half the logical count is the right default.
    """
    logical = os.cpu_count() or 4
    return max(1, logical // 2)


DEFAULT_SYSTEM_PROMPT = (
    "You are JARVIS, a helpful, concise AI assistant running locally on the "
    "user's own machine. Answer directly and clearly. Prefer short answers; "
    "expand only when the question needs it. Use markdown for structure and "
    "fenced code blocks with a language tag for code."
)


@dataclass
class Settings:
    host: str = field(default_factory=lambda: _env_str("JARVIS_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("JARVIS_PORT", 8080))

    ollama_url: str = field(
        default_factory=lambda: _env_str("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    )
    model: str = field(default_factory=lambda: _env_str("JARVIS_MODEL", "qwen3:4b"))
    system_prompt: str = field(
        default_factory=lambda: _env_str("JARVIS_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)
    )

    # Generation defaults (tuned for a 8-16 GB CPU-only laptop).
    temperature: float = field(default_factory=lambda: _env_float("JARVIS_TEMPERATURE", 0.7))
    top_p: float = field(default_factory=lambda: _env_float("JARVIS_TOP_P", 0.9))
    num_ctx: int = field(default_factory=lambda: _env_int("JARVIS_NUM_CTX", 4096))
    num_predict: int = field(default_factory=lambda: _env_int("JARVIS_NUM_PREDICT", 1024))
    num_thread: int = field(default_factory=lambda: _env_int("JARVIS_NUM_THREAD", _default_threads()))
    keep_alive: str = field(default_factory=lambda: _env_str("JARVIS_KEEP_ALIVE", "30m"))

    # How many previous messages (user+assistant) are replayed to the model.
    history_limit: int = field(default_factory=lambda: _env_int("JARVIS_HISTORY_LIMIT", 20))

    # Networking.
    request_timeout: float = field(default_factory=lambda: _env_float("JARVIS_TIMEOUT", 600.0))
    connect_timeout: float = field(default_factory=lambda: _env_float("JARVIS_CONNECT_TIMEOUT", 5.0))

    db_path: Path = field(
        default_factory=lambda: Path(
            _env_str("JARVIS_DB", str(Path.home() / ".local/share/jarvis/jarvis.db"))
        ).expanduser()
    )

    @property
    def chat_endpoint(self) -> str:
        return f"{self.ollama_url}/api/chat"

    @property
    def tags_endpoint(self) -> str:
        return f"{self.ollama_url}/api/tags"

    @property
    def version_endpoint(self) -> str:
        return f"{self.ollama_url}/api/version"

    @property
    def ps_endpoint(self) -> str:
        return f"{self.ollama_url}/api/ps"


settings = Settings()
