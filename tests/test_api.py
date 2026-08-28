import json


def events(response) -> list[dict]:
    parsed = []
    for frame in response.text.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data:"):
            parsed.append(json.loads(frame[5:]))
    return parsed


def test_health_reports_stub_ollama(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["model"] == "qwen3:4b"
    assert body["model_loaded"] is True


def test_models_are_listed(client):
    names = [m["name"] for m in client.get("/api/models").json()["models"]]
    assert names == ["llama3.2:3b", "qwen3:4b"]


def test_chat_lifecycle_and_streaming(client):
    chat = client.post("/api/chats", json={}).json()
    chat_id = chat["id"]

    response = client.post(f"/api/chats/{chat_id}/messages", json={"message": "hello"})
    assert response.status_code == 200
    parsed = events(response)

    kinds = {event["type"] for event in parsed}
    assert {"start", "token", "think", "done"} <= kinds

    answer = "".join(e["content"] for e in parsed if e["type"] == "token")
    thinking = "".join(e["content"] for e in parsed if e["type"] == "think")
    assert answer.startswith("Hello, I am **JARVIS**")
    assert "<think>" not in answer
    assert thinking == "The user said hello. Keep it short."

    done = [e for e in parsed if e["type"] == "done"][0]
    assert done["stats"]["tokens"] == 42
    assert done["stats"]["tokens_per_second"] == 14.0

    stored = client.get(f"/api/chats/{chat_id}").json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["title"] == "hello"
    assert stored["messages"][1]["thinking"] == "The user said hello. Keep it short."


def test_history_is_replayed_to_the_model(client):
    chat_id = client.post("/api/chats", json={}).json()["id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"message": "first"})
    client.post(f"/api/chats/{chat_id}/messages", json={"message": "second"})

    messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["first", "second"]


def test_regenerate_replaces_the_last_answer(client):
    chat_id = client.post("/api/chats", json={}).json()["id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"message": "hello"})

    response = client.post(f"/api/chats/{chat_id}/regenerate")
    assert response.status_code == 200
    messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_missing_model_produces_a_helpful_error(client):
    chat_id = client.post("/api/chats", json={}).json()["id"]
    response = client.post(f"/api/chats/{chat_id}/messages",
                           json={"message": "hi", "model": "missing:1b"})
    errors = [e for e in events(response) if e["type"] == "error"]
    assert errors and "ollama pull missing:1b" in errors[0]["error"]


def test_settings_round_trip(client):
    updated = client.put("/api/settings", json={"temperature": 0.2, "num_thread": 4}).json()
    assert updated["temperature"] == 0.2
    assert updated["num_thread"] == 4
    assert client.get("/api/settings").json()["temperature"] == 0.2


def test_rename_search_export_and_delete(client):
    chat_id = client.post("/api/chats", json={}).json()["id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"message": "pineapple facts"})

    client.patch(f"/api/chats/{chat_id}", json={"title": "Fruit", "pinned": True})
    assert client.get("/api/chats").json()["chats"][0]["pinned"] is True

    results = client.get("/api/search", params={"q": "pineapple"}).json()["results"]
    assert results[0]["id"] == chat_id

    export = client.get(f"/api/chats/{chat_id}/export")
    assert "# Fruit" in export.text and "pineapple facts" in export.text

    assert client.delete(f"/api/chats/{chat_id}").status_code == 204
    assert client.get(f"/api/chats/{chat_id}").status_code == 404


def test_index_page_is_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "JARVIS" in page.text
