"""Dedicated Unit Tests for Process Tree Isolation & Streaming Output Bounds.

Target:
- kill_process_tree functionality (descendant killing, dead leader handling, safe invalid pids)
- streaming output reader (zero temporary files, bounded memory consumption, structured truncation)
- WorkspaceCommandRunner timeout killing process group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from sandbox.command_runner import WorkspaceCommandRunner, kill_process_tree
from sandbox.constants import MAX_COMMAND_OUTPUT_BYTES
from sandbox.resource_monitor import WorkspaceResourceMonitor


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def test_kill_process_tree_terminates_descendants(tmp_path: Path):
    """Spawns nested child processes and verifies kill_process_tree leaves zero alive descendants."""
    grandchild_marker = tmp_path / "grandchild.pid"
    script = tmp_path / "nested_tree.py"
    script.write_text(
        f"""
import subprocess, sys, time, pathlib

grandchild_code = '''
import time, os, pathlib
pathlib.Path({str(grandchild_marker)!r}).write_text(str(os.getpid()))
time.sleep(60)
'''
child = subprocess.Popen([sys.executable, "-c", grandchild_code])
time.sleep(60)
"""
    )

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        start_new_session=True,
    )

    # Wait for grandchild to spin up and record its PID
    deadline = time.time() + 5.0
    grandchild_pid = None
    while time.time() < deadline:
        if grandchild_marker.exists():
            text = grandchild_marker.read_text().strip()
            if text:
                grandchild_pid = int(text)
                break
        time.sleep(0.1)

    assert grandchild_pid is not None, "Grandchild process failed to start"
    assert _is_pid_alive(proc.pid)
    assert _is_pid_alive(grandchild_pid)

    # Terminate the entire process tree using leader PID
    kill_process_tree(proc.pid)
    proc.wait(timeout=2.0)

    # Verify both leader and grandchild are dead
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _is_pid_alive(grandchild_pid) and not _is_pid_alive(proc.pid):
            break
        time.sleep(0.1)

    assert not _is_pid_alive(proc.pid), "Leader process remained alive"
    assert not _is_pid_alive(grandchild_pid), "Grandchild process remained alive"


def test_kill_process_tree_handles_dead_leader(tmp_path: Path):
    """Spawns a grandchild where the leader exits immediately; verifies kill_process_tree still kills grandchild."""
    grandchild_marker = tmp_path / "gc_pid.txt"
    script = tmp_path / "dead_leader.py"
    script.write_text(
        f"""
import subprocess, sys, time, os, pathlib

gc_code = '''
import time, os, pathlib
pathlib.Path({str(grandchild_marker)!r}).write_text(str(os.getpid()))
time.sleep(60)
'''
# Child detached inside same PGID
subprocess.Popen([sys.executable, "-c", gc_code])
# Leader exits immediately
sys.exit(0)
"""
    )

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        start_new_session=True,
    )

    # Wait for leader to exit
    proc.wait(timeout=5.0)
    assert not _is_pid_alive(proc.pid), "Leader should have exited"

    # Wait for grandchild to write its pid
    deadline = time.time() + 5.0
    grandchild_pid = None
    while time.time() < deadline:
        if grandchild_marker.exists():
            text = grandchild_marker.read_text().strip()
            if text:
                grandchild_pid = int(text)
                break
        time.sleep(0.1)

    assert grandchild_pid is not None, "Grandchild failed to start"
    assert _is_pid_alive(grandchild_pid), "Grandchild should be running"

    # Terminate using original leader PID (dead leader PGID fallback)
    kill_process_tree(proc.pid)

    # Verify grandchild is killed
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _is_pid_alive(grandchild_pid):
            break
        time.sleep(0.1)

    assert not _is_pid_alive(grandchild_pid), "Grandchild survived dead leader process group kill"


def test_kill_process_tree_safe_on_invalid_pids():
    """Verifies kill_process_tree handles 0, negative PIDs, and nonexistent PIDs without error."""
    # Must not kill self or caller
    kill_process_tree(0)
    kill_process_tree(-1)
    kill_process_tree(-99999)

    # Non-existent PID should be handled gracefully
    kill_process_tree(9999999)
    assert True


def test_streaming_output_limiter_bounds_memory_and_truncates(tmp_path: Path):
    """Runs a subprocess outputting large data; verifies output is cleanly bounded and truncated."""
    script = tmp_path / "large_output.py"
    script.write_text(
        """
import sys
sys.stdout.write("X" * 300_000)
sys.stdout.flush()
sys.stderr.write("Y" * 300_000)
sys.stderr.flush()
"""
    )

    max_bytes = 4096
    runner = WorkspaceCommandRunner(max_output_bytes=max_bytes)
    result = runner.run_command(tmp_path, "python", [str(script)], timeout_seconds=10)

    assert result.success is True
    assert "[TRUNCATED: output exceeded size limit]" in result.stdout
    assert "[TRUNCATED: error output exceeded size limit]" in result.stderr
    assert len(result.stdout.encode("utf-8")) <= max_bytes + 200
    assert len(result.stderr.encode("utf-8")) <= max_bytes + 200

    monitor = WorkspaceResourceMonitor(tmp_path)
    assert monitor.check_output_limit(50000) is False
    assert monitor.check_output_limit(MAX_COMMAND_OUTPUT_BYTES + 1) is True


def test_streaming_output_limiter_zero_temporary_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verifies no temporary disk files are created during execution."""
    def _forbidden_tempfile(*args, **kwargs):
        raise AssertionError("tempfile.TemporaryFile was called! Output must stream in-memory.")

    monkeypatch.setattr(tempfile, "TemporaryFile", _forbidden_tempfile)

    script = tmp_path / "echo_test.py"
    script.write_text("print('streaming test passed')\n")

    runner = WorkspaceCommandRunner()
    result = runner.run_command(tmp_path, "python", [str(script)], timeout_seconds=10)

    assert result.success is True
    assert "streaming test passed" in result.stdout


def test_command_timeout_kills_process_group_and_reaps(tmp_path: Path):
    """Verifies run_command on timeout terminates background grandchild and returns structured timeout result."""
    marker = tmp_path / "should_not_exist.txt"
    script = tmp_path / "runaway.py"
    script.write_text(
        f"""
import subprocess, sys, time
child_cmd = "import time, pathlib; time.sleep(2.5); pathlib.Path({str(marker)!r}).write_text('survived')"
subprocess.Popen([sys.executable, "-c", child_cmd])
time.sleep(60)
"""
    )

    runner = WorkspaceCommandRunner()
    result = runner.run_command(tmp_path, "python", [str(script)], timeout_seconds=1)

    assert result.timed_out is True
    assert result.success is False
    assert result.exit_code == -1
    assert "timed out after 1 seconds" in result.stderr

    time.sleep(3.5)
    assert not marker.exists(), "Grandchild process kept running and created marker file"
