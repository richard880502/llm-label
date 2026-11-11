"""HTTP liveness/readiness probes must be safe for orchestrators."""
from fastapi.testclient import TestClient

from backend import main


def test_livez_returns_json_without_touching_db(monkeypatch):
    def fail_if_called():
        raise AssertionError("livez must not query PostgreSQL")

    monkeypatch.setattr(main, "check_db_readiness", fail_if_called)
    response = TestClient(main.app).get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"].startswith("application/json")


def test_readyz_returns_200_when_postgres_is_available(monkeypatch):
    checked = []
    monkeypatch.setattr(main, "check_db_readiness", lambda: checked.append(True))

    response = TestClient(main.app).get("/readyz")

    assert checked == [True]
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_returns_503_without_exposing_database_errors(monkeypatch):
    def db_unavailable():
        raise RuntimeError("sensitive database connection information")

    monkeypatch.setattr(main, "check_db_readiness", db_unavailable)
    response = TestClient(main.app).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "sensitive" not in response.text


def test_health_endpoints_are_hidden_from_openapi():
    paths = main.app.openapi()["paths"]
    assert "/livez" not in paths
    assert "/readyz" not in paths
