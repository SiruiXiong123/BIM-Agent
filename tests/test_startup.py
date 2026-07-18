"""Tests for the portable CLI startup boundary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.main import build_streamlit_command, main
from src.rules.sandbox_runner import DEFAULT_PYTHON_EXECUTABLE
from src.startup import REQUIRED_ENV_KEYS, StartupCheckError, _load_settings


def test_streamlit_command_uses_current_python_and_opens_browser() -> None:
    command = build_streamlit_command(
        host="127.0.0.1",
        port=8501,
        no_browser=False,
    )

    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert command[command.index("--server.headless") + 1] == "false"
    assert command[command.index("--server.maxUploadSize") + 1] == "250"


def test_rule_sandbox_uses_the_active_environment_interpreter() -> None:
    assert DEFAULT_PYTHON_EXECUTABLE == Path(sys.executable).resolve()


def test_environment_template_placeholders_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "base_url=https://example.test/v1\n"
        "api_key=replace-me\n"
        "model_name=test-model\n"
        "evacuation_door_model_name=test-classifier\n"
        "embedding_model_name=Pro/BAAI/bge-m3\n",
        encoding="utf-8",
    )

    with pytest.raises(StartupCheckError, match="api_key"):
        _load_settings(env_path)


def test_check_mode_does_not_start_streamlit(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import main as main_module
    from src.startup import StartupReport

    report = StartupReport(
        project_root=Path.cwd(),
        python_version="3.12.0",
        document_ids=("doc-a", "doc-b"),
        embedding_model="test-embedding",
        eval_fixture=Path("eval.ifc"),
    )
    monkeypatch.setattr(main_module, "run_startup_checks", lambda _: report)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called in --check mode")

    monkeypatch.setattr(main_module.subprocess, "run", fail_if_called)

    assert main(["--check"]) == 0
