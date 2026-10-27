"""Tests for the Sketch (statelyai/sketch) transport used by `serve`."""

import io
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
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


class TestSketchPnpmVersion:
    def test_reads_package_manager(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"packageManager": "pnpm@10.32.1"}))
        assert xstate._sketch_pnpm_version(tmp_path) == "10.32.1"

    def test_drops_integrity_hash(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"packageManager": "pnpm@11.0.0+sha512.abc"}))
        assert xstate._sketch_pnpm_version(tmp_path) == "11.0.0"

    @pytest.mark.parametrize(
        "content",
        [None, "not json", json.dumps([]), json.dumps({}), json.dumps({"packageManager": "yarn@4.0.0"})],
    )
    def test_defaults_without_pinned_pnpm(self, tmp_path: Path, content: str | None) -> None:
        if content is not None:
            (tmp_path / "package.json").write_text(content)
        assert xstate._sketch_pnpm_version(tmp_path) == xstate._PNPM_VERSION


def fake_pnpm(monkeypatch: pytest.MonkeyPatch, *, on_path: set[str], version: str | None = None) -> None:
    """Pretend ``on_path`` tools are installed and ``pnpm --version`` prints ``version``."""
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in on_path else None)

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args == ["pnpm", "--version"]
        if version is None:
            raise OSError("pnpm is broken")
        return subprocess.CompletedProcess(args, 0, stdout=f"{version}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)


class TestPnpmCommand:
    def test_uses_pnpm_on_path_with_the_same_major(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pnpm(monkeypatch, on_path={"pnpm", "npx"}, version="10.1.0")
        assert xstate._pnpm_command("10.32.1") == ["pnpm"]

    def test_uses_npx_when_pnpm_on_path_has_another_major(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_pnpm(monkeypatch, on_path={"pnpm", "npx"}, version="9.15.9")
        assert xstate._pnpm_command("10.32.1") == ["npx", "--yes", "pnpm@10.32.1"]
        assert "pnpm 9.15.9 on PATH" in capsys.readouterr().err

    def test_uses_npx_when_pnpm_on_path_does_not_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pnpm(monkeypatch, on_path={"pnpm", "npx"}, version=None)
        assert xstate._pnpm_command("10.32.1") == ["npx", "--yes", "pnpm@10.32.1"]

    def test_falls_back_to_npx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pnpm(monkeypatch, on_path={"npx"})
        assert xstate._pnpm_command() == ["npx", "--yes", f"pnpm@{xstate._PNPM_VERSION}"]

    def test_errors_on_another_major_without_npx(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_pnpm(monkeypatch, on_path={"pnpm"}, version="9.15.9")
        with pytest.raises(SystemExit):
            xstate._pnpm_command("10.32.1")
        assert "needs pnpm 10.32.1, found pnpm 9.15.9" in capsys.readouterr().err

    def test_errors_without_node_tooling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pnpm(monkeypatch, on_path=set())
        with pytest.raises(SystemExit):
            xstate._pnpm_command()
