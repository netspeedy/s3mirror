"""Stopping a run with SIGTERM or Ctrl+C, in a real process against the moto servers."""

# pytest passes fixtures as arguments, so a test that needs several takes several.
# pylint: disable=too-many-arguments,too-many-positional-arguments

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import s3mirror

OBJECTS = {f"objects/{n:04}.txt": b"x" for n in range(300)}


@pytest.mark.parametrize(
    "signum, code, message",
    [
        (signal.SIGTERM, 143, "Operation stopped by SIGTERM"),
        (signal.SIGINT, 130, "Operation cancelled by user (Ctrl+C)"),
    ],
    ids=["SIGTERM", "SIGINT"],
)
def test_a_signal_stops_queuing_work_and_exits(
    source, destination, config, tmp_path, signum, code, message
):
    """The copies already running finish, the queued ones are dropped, and it exits.

    With one worker and 300 objects, the signal arrives after the first copy, so
    the run has hundreds still queued.
    """
    source.put("app-data", OBJECTS)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    command = [sys.executable, str(Path(s3mirror.__file__))]
    command += ["--config", str(path), "--debug", "--workers", "1"]
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    ) as process:
        watchdog = threading.Timer(60, process.kill)
        watchdog.start()
        try:
            output = []
            for line in process.stdout:
                output.append(line)
                if "✓ objects/" in line:
                    process.send_signal(signum)
                    break
            output.extend(process.stdout)
            process.wait()
        finally:
            watchdog.cancel()

    text = "".join(output)
    assert process.returncode == code, text
    assert message in text
    assert "FINAL SUMMARY" not in text
    copied = destination.client.list_objects_v2(Bucket="app-data").get("KeyCount", 0)
    assert 0 < copied < len(OBJECTS)
