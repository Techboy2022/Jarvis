import socket
import threading
import time

import pytest
import uvicorn

from tests.stub_ollama import build_stub


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def stub_ollama() -> str:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_stub(), host="127.0.0.1", port=port,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "stub Ollama did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def client(stub_ollama, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OLLAMA_URL", stub_ollama)
    monkeypatch.setenv("JARVIS_DB", str(tmp_path / "jarvis.db"))
    monkeypatch.setenv("JARVIS_MODEL", "qwen3:4b")

    for module in ("jarvis.main", "jarvis.config", "jarvis.store", "jarvis.ollama"):
        import sys
        sys.modules.pop(module, None)

    from jarvis.main import app

    with TestClient(app) as test_client:
        yield test_client
