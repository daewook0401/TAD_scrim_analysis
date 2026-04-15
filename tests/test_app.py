from __future__ import annotations

from fastapi.testclient import TestClient

import app


client = TestClient(app.app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unified_analyze_endpoint_uses_request_payload(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class DummyResult:
        def model_dump(self) -> dict[str, object]:
            return {"winner": "team1", "team1": {"players": []}, "team2": {"players": []}}

    def fake_analyze_from_request(
        *,
        image_url: str | None = None,
        image_path: str | None = None,
        bucket: str | None = None,
        object_key: str | None = None,
    ) -> DummyResult:
        captured.update(
            {
                "image_url": image_url,
                "image_path": image_path,
                "bucket": bucket,
                "object_key": object_key,
            }
        )
        return DummyResult()

    monkeypatch.setattr(app, "analyze_from_request", fake_analyze_from_request)

    response = client.post("/analyze", json={"bucket": "tad", "object_key": "11.png"})

    assert response.status_code == 200
    assert captured == {
        "image_url": None,
        "image_path": None,
        "bucket": "tad",
        "object_key": "11.png",
    }
    assert response.json()["winner"] == "team1"


def test_invalid_request_returns_422() -> None:
    response = client.post("/analyze", json={"image_url": "https://example.com/a.png", "image_path": "a.png"})

    assert response.status_code == 422
