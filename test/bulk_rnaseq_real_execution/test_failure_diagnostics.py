"""Focused evidence retention checks; no Docker, Redis or scientific execution."""

from hashlib import sha256
import json
import os
from pathlib import Path
import stat

import pytest

from .failure_diagnostics import PRIVATE_DIAGNOSTICS_ENV, preserve_execution_failure


def test_first_task_error_is_private_bounded_and_survives_temp_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "persistent"
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.setenv(PRIVATE_DIAGNOSTICS_ENV, str(private))
    workspace = tmp_path / "temporary/run"
    first = workspace / "engine/work/aa/first"
    second = workspace / "engine/work/bb/second"
    for task in (first, second):
        task.mkdir(parents=True)
        (task / ".exitcode").write_text("127\n")
    os.utime(first / ".exitcode", ns=(1, 1))
    raw = b"error while loading shared libraries: libc.so.6: Permission denied\n"
    raw += b"/private/path?token=do-not-publish\n" * 4096
    (first / ".command.err").write_bytes(raw)
    (second / ".command.err").write_bytes(b"later failure")
    (workspace / "logs").mkdir()
    (workspace / "logs/nextflow.log").write_bytes(b"private workflow log\n" + raw)
    evidence = tmp_path / "temporary/evidence"
    result = preserve_execution_failure(
        workspace=workspace,
        evidence_root=evidence,
        stage="platform",
        reason_code="LOCAL_RUN_EXECUTION_FAILED",
        rq_exception="private RQ traceback",
    )
    assert result["capture_status"] == "complete"
    assert result["task_exit_code"] == 127
    assert result["task_signal"] == "SHARED_LIBRARY_PERMISSION_DENIED"
    public = (evidence / "execution-failure.json").read_text()
    assert "token" not in public and "/private" not in public
    assert "traceback" not in public
    record = private / result["private_record"]
    saved = record / "command.err"
    assert saved.read_bytes() == raw[:65536]
    assert (
        json.loads(public)["files"]["command.err"]["sha256"]
        == sha256(raw[:65536]).hexdigest()
    )
    assert result["files"]["command.err"]["truncated"] is True
    assert stat.S_IMODE(record.stat().st_mode) == 0o700
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert (record / "rq-exception.txt").read_text() == "private RQ traceback"
    assert (record / "nextflow.log").read_bytes() == (b"private workflow log\n" + raw)[
        -65536:
    ]
    (first / ".command.err").unlink()
    assert saved.read_bytes() == raw[:65536]


@pytest.mark.parametrize(
    "unsafe", ["symlink", "permissions", "upload-tree", "ephemeral"]
)
def test_diagnostic_failure_is_path_free_and_does_not_replace_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    if unsafe == "upload-tree":
        private = tmp_path / "evidence/raw"
    elif unsafe == "ephemeral":
        monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    elif unsafe == "permissions":
        private.chmod(0o755)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(private, target_is_directory=True)
        private = alias
    monkeypatch.setenv(PRIVATE_DIAGNOSTICS_ENV, str(private))
    result = preserve_execution_failure(
        workspace=tmp_path / "missing-workspace",
        evidence_root=tmp_path / "evidence",
        stage="rapid-quant",
        reason_code="/private/token=secret",
    )
    assert result["capture_status"] == "incomplete"
    assert result["capture_error_type"] == "ValueError"
    assert result["reason_code"] is None
    assert str(tmp_path) not in json.dumps(result)
