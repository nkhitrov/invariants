"""Tests for the Sketch (statelyai/sketch) transport used by `serve`."""

import io
import json
import shutil
import urllib.request
from typing import Any

import pytest

from invariants.viz import xstate


class TestUrls:
    def test_api_url_points_at_local_sketch_registry(self) -> None:
        assert xstate._sketch_api_url(3000) == "http://127.0.0.1:3000/api/viz"

    def test_viz_url_opens_source_file(self) -> None:
        assert xstate._sketch_viz_url(3000, "local-1-abc") == "http://127.0.0.1:3000/viz/local-1-abc"


class TestCreateSourceFile:
    def test_posts_code_and_returns_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def fake_urlopen(req: Any, timeout: float = 0) -> io.BytesIO:
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["content_type"] = req.get_header("Content-type")
            seen["body"] = json.loads(req.data.decode())
            return io.BytesIO(json.dumps({"data": {"id": "local-1-xyz", "text": "..."}}).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        file_id = xstate._create_source_file(3000, name="DebtState", code="const x = 1;")

        assert file_id == "local-1-xyz"
        assert seen["url"] == "http://127.0.0.1:3000/api/viz/create-source-file"
        assert seen["method"] == "POST"
        assert seen["content_type"] == "application/json"
        assert seen["body"] == {"text": "const x = 1;", "name": "DebtState", "format": "xstate"}

    def test_rejects_response_without_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req: Any, timeout: float = 0) -> io.BytesIO:
            return io.BytesIO(b'{"data": {}}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(RuntimeError, match="create-source-file"):
            xstate._create_source_file(3000, name="X", code="")


class TestSketchEnv:
    def test_env_points_client_at_local_api_and_uses_memory_db(self) -> None:
        env = xstate._sketch_env(4321, base={"PATH": "/bin"})
        assert env["PATH"] == "/bin"
        assert env["VITE_REGISTRY_API_URL"] == "http://127.0.0.1:4321/api/viz"
        assert env["DB_PATH"] == ":memory:"
        assert "NODE_OPTIONS" not in env


class TestPnpmCommand:
    def test_prefers_pnpm_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/pnpm" if cmd == "pnpm" else None)
        assert xstate._pnpm_command() == ["pnpm"]

    def test_falls_back_to_npx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/npx" if cmd == "npx" else None)
        assert xstate._pnpm_command() == ["npx", "--yes", f"pnpm@{xstate._PNPM_VERSION}"]

    def test_errors_without_node_tooling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        with pytest.raises(SystemExit):
            xstate._pnpm_command()
