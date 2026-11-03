"""Adversarial Empirical Stress Tests for Sandbox Command Runner & Process Isolation.

Milestone: M1 Security Foundation & Process Isolation
Role: Empirical Challenger
Target:
- Grandchild process tree termination when parent/leader exits immediately.
- Zero orphan background daemon loops (bash, sh, python) surviving timeout.
- High-volume data streaming (50MB+), strict memory bounds, zero disk spooling, no deadlocks.
- Safe rejection of invalid PIDs (0, -1, non-existent) without targeting caller or crashing.
- Concurrent stress testing of multi-process group termination.
"""

from __future__ import annotations

import concurrent.futures
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from sandbox.command_runner import (
    WorkspaceCommandRunner,
    _drain_and_capture_stream,
    kill_process_tree,
)
from sandbox.constants import MAX_COMMAND_OUTPUT_BYTES
from sandbox.resource_monitor import WorkspaceResourceMonitor


def _is_pid_alive(pid: int) -> bool:
    """Check if process is alive via signal 0."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


# ============================================================================
# Scenario 1: Grandchild Process Tree Termination (Immediate Parent Exit)
# ============================================================================


def test_adversarial_grandchild_when_intermediate_parent_exits_immediately(tmp_path: Path):
    """Stress-test 3-tier process tree: Leader A -> Child B -> Grandchild C.

    Child B spawns Grandchild C (daemon loop) and exits immediately.
    Leader A runs until timeout under WorkspaceCommandRunner.
    Empirically verifies Grandchild C is reaped on timeout.
    """
    gc_pid_file = tmp_path / "gc_intermediate.pid"
    if gc_pid_file.exists():
        gc_pid_file.unlink()

    script = tmp_path / "leader_3tier.py"
    script.write_text(
        f"""
import subprocess, sys, time, os

b_code = \"\"\"
import subprocess, sys, time, os, pathlib
c_code = "import time, os, pathlib; pathlib.Path({str(gc_pid_file)!r}).write_text(str(os.getpid())); \\\\nwhile True: time.sleep(1)"
subprocess.Popen([sys.executable, "-c", c_code])
sys.exit(0)
\"\"\"

p_b = subprocess.Popen([sys.executable, "-c", b_code])
p_b.wait(timeout=5)
time.sleep(60)
"""
    )

    runner = WorkspaceCommandRunner()
    res = runner.run_command(tmp_path, "python", [str(script)], timeout_seconds=1)

    assert res.timed_out is True
    assert res.exit_code == -1

    # Verify grandchild was spawned and recorded PID
    deadline = time.time() + 3.0
    gc_pid = None
    while time.time() < deadline:
        if gc_pid_file.exists():
            text = gc_pid_file.read_text().strip()
            if text:
                gc_pid = int(text)
                break
        time.sleep(0.05)

    assert gc_pid is not None, "Grandchild failed to start"

    # Wait for OS to process SIGKILL
    kill_deadline = time.time() + 3.0
    while time.time() < kill_deadline:
        if not _is_pid_alive(gc_pid):
            break
        time.sleep(0.1)

    assert not _is_pid_alive(gc_pid), f"Grandchild PID {gc_pid} survived timeout termination!"


def test_adversarial_grandchild_when_both_leader_and_parent_exit_immediately(tmp_path: Path):
    """Stress-test tree termination when session leader AND intermediate parent exit immediately.

    Empirically verifies kill_process_tree(leader_pid) targets the dead-leader process group.
    """
    gc_pid_file = tmp_path / "gc_dead_leader.pid"
    if gc_pid_file.exists():
        gc_pid_file.unlink()

    script = tmp_path / "dead_tree.py"
    script.write_text(
        f"""
import subprocess, sys, time, os

b_code = \"\"\"
import subprocess, sys, time, os
c_code = "import time, os, pathlib; pathlib.Path({str(gc_pid_file)!r}).write_text(str(os.getpid())); \\\\nwhile True: time.sleep(1)"
subprocess.Popen([sys.executable, "-c", c_code])
sys.exit(0)
\"\"\"

subprocess.Popen([sys.executable, "-c", b_code])
sys.exit(0)
"""
    )

    p = subprocess.Popen([sys.executable, str(script)], cwd=str(tmp_path), start_new_session=True)
    leader_pid = p.pid
    p.wait(timeout=5)

    # Leader has exited
    assert not _is_pid_alive(leader_pid), "Session leader should have exited"

    # Wait for grandchild PID
    deadline = time.time() + 3.0
    gc_pid = None
    while time.time() < deadline:
        if gc_pid_file.exists():
            text = gc_pid_file.read_text().strip()
            if text:
                gc_pid = int(text)
                break
        time.sleep(0.05)

    assert gc_pid is not None, "Grandchild failed to start"
    assert _is_pid_alive(gc_pid), "Grandchild should be running"

    # Execute kill_process_tree on dead leader
    kill_process_tree(leader_pid)

    # Verify grandchild is killed
    kill_deadline = time.time() + 3.0
    while time.time() < kill_deadline:
        if not _is_pid_alive(gc_pid):
            break
        time.sleep(0.1)

    assert not _is_pid_alive(gc_pid), f"Grandchild PID {gc_pid} survived dead leader tree termination!"


# ============================================================================
# Scenario 2: Background Daemon Loops (Python, sh, bash)
# ============================================================================


def test_adversarial_python_background_daemon_loop_terminated(tmp_path: Path):
    """Stress-test Python script launching infinite loop daemon child; verify zero orphan leaks."""
    daemon_pid_file = tmp_path / "py_daemon.pid"
    script = tmp_path / "py_spawner.py"
    script.write_text(
        f"""
import subprocess, sys, time, os
code = \"\"\"import time, os, pathlib
pathlib.Path({str(daemon_pid_file)!r}).write_text(str(os.getpid()))
while True:
    time.sleep(1)
\"\"\"
subprocess.Popen([sys.executable, "-c", code])
time.sleep(60)
"""
    )

    runner = WorkspaceCommandRunner()
    res = runner.run_command(tmp_path, "python", [str(script)], timeout_seconds=1)

    assert res.timed_out is True
    assert daemon_pid_file.exists()
    daemon_pid = int(daemon_pid_file.read_text().strip())

    time.sleep(0.5)
    assert not _is_pid_alive(daemon_pid), f"Python daemon {daemon_pid} survived timeout!"


def test_adversarial_sh_background_daemon_loop_terminated(tmp_path: Path):
    """Stress-test sh launching background daemon loop `(while true; do sleep 1; done) &`."""
    daemon_pid_file = tmp_path / "sh_daemon.pid"
    script = tmp_path / "sh_spawner.sh"
    script.write_text(
        f"""#!/bin/sh
(
  while true; do
    sleep 1
  done
) &
echo $! > {str(daemon_pid_file)}
sleep 60
"""
    )
    script.chmod(0o755)

    runner = WorkspaceCommandRunner(allowed_commands=["sh"])
    res = runner.run_command(tmp_path, "sh", [str(script)], timeout_seconds=1)

    assert res.timed_out is True
    assert daemon_pid_file.exists()
    daemon_pid = int(daemon_pid_file.read_text().strip())

    time.sleep(0.5)
    assert not _is_pid_alive(daemon_pid), f"sh background daemon {daemon_pid} survived timeout!"


def test_adversarial_bash_background_daemon_loop_terminated(tmp_path: Path):
    """Stress-test bash launching background daemon loop `(while true; do sleep 1; done) &`."""
    daemon_pid_file = tmp_path / "bash_daemon.pid"
    script = tmp_path / "bash_spawner.bash"
    script.write_text(
        f"""#!/bin/bash
(
  while true; do
    sleep 1
  done
) &
echo $! > {str(daemon_pid_file)}
sleep 60
"""
    )
    script.chmod(0o755)

    runner = WorkspaceCommandRunner(allowed_commands=["bash"])
    res = runner.run_command(tmp_path, "bash", [str(script)], timeout_seconds=1)

    assert res.timed_out is True
    assert daemon_pid_file.exists()
    daemon_pid = int(daemon_pid_file.read_text().strip())

    time.sleep(0.5)
    assert not _is_pid_alive(daemon_pid), f"bash background daemon {daemon_pid} survived timeout!"


# ============================================================================
# Scenario 3: High-Volume Stream (50MB+), Memory Bounds, Disk Isolation, No Deadlock
# ============================================================================


def test_adversarial_stream_50mb_strict_memory_bound_and_no_disk():
    """Stream 50MB of raw bytes through _drain_and_capture_stream.

    Verifies:
    1. Bounded memory consumption strictly capped at max_bytes.
    2. holder['truncated'] set to True cleanly.
    3. Zero disk files or temporary disk leaks created.
    """
    fifty_mb = 50 * 1024 * 1024
    max_bytes = 64 * 1024  # 64 KB limit

    # Create in-memory pseudo-pipe feeding 50MB
    class LargeByteStream:
        def __init__(self, total_bytes: int):
            self.remaining = total_bytes
            self.chunk = b"A" * 65536
            self.closed = False

        def read(self, size: int) -> bytes:
            if self.closed or self.remaining <= 0:
                return b""
            to_read = min(size, self.remaining, len(self.chunk))
            self.remaining -= to_read
            return self.chunk[:to_read]

        def close(self) -> None:
            self.closed = True

    stream = LargeByteStream(fifty_mb)
    holder: dict[str, Any] = {"data": b"", "truncated": False}

    # Verify no disk calls occur
    original_tempfile = tempfile.TemporaryFile

    def forbidden_tempfile(*args, **kwargs):
        raise AssertionError("Disk tempfile was created during stream draining!")

    tempfile.TemporaryFile = forbidden_tempfile
    try:
        # Run stream drainer
        _drain_and_capture_stream(stream, max_bytes, holder)
    finally:
        tempfile.TemporaryFile = original_tempfile

    # Assertions
    assert len(holder["data"]) == max_bytes, f"Expected exactly {max_bytes} bytes captured"
    assert holder["truncated"] is True, "Stream should be marked as truncated"
    assert stream.closed is True, "Pipe should be closed after draining"


def test_adversarial_stream_concurrent_stdout_stderr_saturation(tmp_path: Path):
    """Saturate both stdout and stderr with large bursts; verify zero deadlock and clean truncation."""
    script = tmp_path / "flood_both.py"
    script.write_text(
        """
import sys
# Flood stdout with 500KB and stderr with 500KB
sys.stdout.write("O" * 500_000)
sys.stdout.flush()
sys.stderr.write("E" * 500_000)
sys.stderr.flush()
"""
    )

    max_bytes = 8192
    runner = WorkspaceCommandRunner(max_output_bytes=max_bytes)
    t0 = time.time()
    result = runner.run_command(tmp_path, "python", [str(script)], timeout_seconds=10)
    dur = time.time() - t0

    assert dur < 8.0, "Execution took too long; potential pipe deadlock!"
    assert result.success is True
    assert result.timed_out is False

    # Verify stdout was capped and truncated
    assert "[TRUNCATED: output exceeded size limit]" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= max_bytes + 250

    # Verify stderr was capped and truncated
    assert "[TRUNCATED: error output exceeded size limit]" in result.stderr
    assert len(result.stderr.encode("utf-8")) <= max_bytes + 250


# ============================================================================
# Scenario 4: Invalid PIDs Safety (0, -1, non-existent, None)
# ============================================================================


def test_adversarial_invalid_pids_never_target_caller_or_crash():
    """Verify kill_process_tree on 0, -1, -9999, None, and non-existent PIDs.

    Crucial POSIX invariant: kill(0) signals caller's process group,
    and kill(-1) signals all processes caller has permission to signal.
    kill_process_tree MUST safely guard against <= 0.
    """
    caller_pid = os.getpid()
    assert _is_pid_alive(caller_pid)

    # PID 0: Must not signal caller process group
    kill_process_tree(0)
    assert _is_pid_alive(caller_pid), "Caller process group was signaled by kill_process_tree(0)!"

    # PID -1: Must not signal all processes
    kill_process_tree(-1)
    assert _is_pid_alive(caller_pid), "Caller was signaled by kill_process_tree(-1)!"

    # Negative PID
    kill_process_tree(-42)
    kill_process_tree(-99999)
    assert _is_pid_alive(caller_pid)

    # Non-existent PID
    kill_process_tree(99999999)
    assert _is_pid_alive(caller_pid)


# ============================================================================
# Scenario 5: Multi-Process Group Concurrent Termination Stress
# ============================================================================


def test_adversarial_concurrent_process_trees_stress(tmp_path: Path):
    """Launch 8 concurrent process groups with background daemons; verify clean parallel reap."""
    def run_stress_worker(idx: int) -> tuple[int, bool]:
        worker_dir = tmp_path / f"worker_{idx}"
        worker_dir.mkdir(parents=True, exist_ok=True)
        pid_file = worker_dir / f"daemon_{idx}.pid"

        script = worker_dir / f"worker_{idx}.py"
        script.write_text(
            f"""
import subprocess, sys, time
code = "import time, os, pathlib; pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); \\\\nwhile True: time.sleep(1)"
subprocess.Popen([sys.executable, "-c", code])
time.sleep(60)
"""
        )

        runner = WorkspaceCommandRunner()
        res = runner.run_command(worker_dir, "python", [str(script)], timeout_seconds=1)

        daemon_pid = None
        if pid_file.exists():
            text = pid_file.read_text().strip()
            if text:
                daemon_pid = int(text)

        time.sleep(0.3)
        alive = _is_pid_alive(daemon_pid) if daemon_pid else False
        return idx, alive

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_stress_worker, i) for i in range(8)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for idx, alive in results:
        assert not alive, f"Worker {idx} background daemon survived concurrent stress test!"
