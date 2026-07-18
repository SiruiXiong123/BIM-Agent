"""Run one validated field script in a short-lived isolated process."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from src.schemas.rule import (
    FieldCalculationOutput,
    ValidatedFieldScript,
)


DEFAULT_PYTHON_EXECUTABLE = Path(sys.executable).resolve()
MAX_JSON_BYTES = 64 * 1024


class RuleSandboxError(RuntimeError):
    """Raised when isolated field execution fails or returns invalid data."""


def run_validated_field_script(
    code: ValidatedFieldScript,
    *,
    python_executable: str | Path = DEFAULT_PYTHON_EXECUTABLE,
    timeout_seconds: float = 3.0,
) -> FieldCalculationOutput:
    executable = Path(python_executable)
    if not executable.is_file():
        raise RuleSandboxError(f"Python executable does not exist: {executable}")

    with tempfile.TemporaryDirectory(prefix="bim_rule_") as temporary:
        temp_dir = Path(temporary)
        script_path = temp_dir / "generated_field_runner.py"
        script_path.write_text(_runner_source(code.source), encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(executable), "-I", "-S", str(script_path)],
                capture_output=True,
                timeout=timeout_seconds,
                cwd=temp_dir,
                env=_safe_environment(),
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuleSandboxError("generated field execution timed out") from exc

    if completed.returncode != 0:
        error = (completed.stderr or b"").decode(
            "utf-8",
            errors="replace",
        ).strip() or "unknown generated field error"
        raise RuleSandboxError(f"generated field failed: {error[:1000]}")
    stdout_bytes = (completed.stdout or b"").strip()
    if len(stdout_bytes) > MAX_JSON_BYTES:
        raise RuleSandboxError("generated field output exceeds the JSON size limit")
    try:
        import json

        stdout = stdout_bytes.decode("utf-8")
        response = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuleSandboxError(
            "generated field did not return valid JSON"
        ) from exc
    if not isinstance(response, dict):
        raise RuleSandboxError("generated field output must be a JSON object")
    response = {
        "target_field": code.target_field,
        **response,
    }
    try:
        return FieldCalculationOutput.model_validate(response)
    except Exception as exc:
        raise RuleSandboxError(
            "generated field returned an invalid result schema"
        ) from exc


def _runner_source(generated_source: str) -> str:
    return (
        "import json\n"
        "import sys\n"
        "from math import ceil, floor\n\n"
        f"{generated_source.rstrip()}\n\n"
        "_result = calculate_value()\n"
        "sys.stdout.write(json.dumps(_result, ensure_ascii=False, allow_nan=False))\n"
    )


def _safe_environment() -> dict[str, str]:
    safe = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            safe[key] = value
    return safe
