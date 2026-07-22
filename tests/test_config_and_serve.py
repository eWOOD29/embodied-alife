from __future__ import annotations

from pathlib import Path

from app import serve
from app.config import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_default_host_binds_all_interfaces() -> None:
    assert Settings().host == "0.0.0.0"


def test_hidden_controls_are_not_overridden_by_component_styles() -> None:
    stylesheet = (ROOT / "app" / "web" / "static" / "style.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in stylesheet


def test_serve_uses_env_host_and_port(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9876")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UPDATE_ENABLED", "false")

    class FakeConfig:
        def __init__(self, app, **kwargs: object) -> None:
            captured["app"] = app
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config
            self.should_exit = False

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(serve.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(serve.uvicorn, "Server", FakeServer)
    serve.main()

    assert captured["app"].title == "Embodied Artificial Life"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9876
    assert captured["log_level"] == "info"
    assert captured["ran"] is True
