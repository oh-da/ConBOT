"""
Cross-platform daemonization and process management utilities.

Supports:
- Unix/Linux: Double-fork daemonization pattern
- macOS: BSD-style daemonization
- Windows: Background process via DETACHED_PROCESS

Handles PID file management and process status checking.
"""

import os
import sys
import time
import logging
import signal
import atexit
from pathlib import Path
from typing import Optional
import platform

logger = logging.getLogger(__name__)


class DaemonError(Exception):
    """Raised when daemon operations fail."""
    pass


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == "Windows"


def write_pid_file(pid_file: str, pid: Optional[int] = None) -> None:
    """
    Write process ID to PID file.

    Args:
        pid_file: Path to PID file
        pid: Process ID to write (default: current process)

    Raises:
        DaemonError: If PID file cannot be written
    """
    if pid is None:
        pid = os.getpid()

    try:
        # Create directory if needed
        pid_path = Path(pid_file)
        pid_path.parent.mkdir(parents=True, exist_ok=True)

        # Write PID
        with open(pid_file, 'w') as f:
            f.write(str(pid))

        logger.info(f"PID file created: {pid_file} (PID: {pid})")

    except Exception as e:
        raise DaemonError(f"Failed to write PID file: {e}") from e


def read_pid_file(pid_file: str) -> Optional[int]:
    """
    Read process ID from PID file.

    Args:
        pid_file: Path to PID file

    Returns:
        Process ID or None if file doesn't exist or is invalid
    """
    try:
        if not Path(pid_file).exists():
            return None

        with open(pid_file, 'r') as f:
            pid_str = f.read().strip()

        pid = int(pid_str)
        return pid

    except (ValueError, IOError) as e:
        logger.warning(f"Invalid PID file {pid_file}: {e}")
        return None


def remove_pid_file(pid_file: str) -> None:
    """
    Remove PID file.

    Args:
        pid_file: Path to PID file
    """
    try:
        if Path(pid_file).exists():
            os.remove(pid_file)
            logger.info(f"PID file removed: {pid_file}")
    except Exception as e:
        logger.warning(f"Failed to remove PID file: {e}")


def is_process_running(pid: int) -> bool:
    """
    Check if a process with given PID is running.

    Cross-platform implementation.

    Args:
        pid: Process ID to check

    Returns:
        True if process is running, False otherwise
    """
    try:
        if is_windows():
            # Windows: Use tasklist
            import subprocess
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}'],
                capture_output=True,
                text=True
            )
            return str(pid) in result.stdout
        else:
            # Unix: Send signal 0 (doesn't actually send signal, just checks)
            os.kill(pid, 0)
            return True

    except (OSError, ProcessLookupError):
        return False
    except Exception as e:
        logger.warning(f"Error checking if process {pid} is running: {e}")
        return False


def kill_process(pid: int, timeout: int = 10) -> bool:
    """
    Kill a process gracefully (SIGTERM) then forcefully (SIGKILL) if needed.

    Args:
        pid: Process ID to kill
        timeout: Seconds to wait before SIGKILL (Unix only)

    Returns:
        True if process was killed, False otherwise
    """
    try:
        if not is_process_running(pid):
            logger.info(f"Process {pid} is not running")
            return True

        if is_windows():
            # Windows: Use taskkill
            import subprocess
            result = subprocess.run(
                ['taskkill', '/PID', str(pid), '/F'],
                capture_output=True
            )
            return result.returncode == 0
        else:
            # Unix: Send SIGTERM, wait, then SIGKILL if needed
            logger.info(f"Sending SIGTERM to process {pid}")
            os.kill(pid, signal.SIGTERM)

            # Wait for graceful shutdown
            for _ in range(timeout):
                if not is_process_running(pid):
                    logger.info(f"Process {pid} terminated gracefully")
                    return True
                time.sleep(1)

            # Force kill if still running
            logger.warning(f"Process {pid} did not terminate, sending SIGKILL")
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)

            if not is_process_running(pid):
                logger.info(f"Process {pid} killed forcefully")
                return True
            else:
                logger.error(f"Failed to kill process {pid}")
                return False

    except Exception as e:
        logger.error(f"Error killing process {pid}: {e}")
        return False


def daemonize_unix(
    pid_file: str,
    log_file: Optional[str] = None,
    working_dir: str = "/"
) -> None:
    """
    Daemonize the current process (Unix/Linux/macOS).

    Uses the double-fork pattern to properly detach from terminal.

    Args:
        pid_file: Path to PID file
        log_file: Path to log file (optional)
        working_dir: Working directory for daemon

    Raises:
        DaemonError: If daemonization fails
    """
    try:
        # First fork
        pid = os.fork()
        if pid > 0:
            # Parent process exits
            sys.exit(0)

    except OSError as e:
        raise DaemonError(f"First fork failed: {e}") from e

    # Decouple from parent environment
    os.chdir(working_dir)
    os.setsid()
    os.umask(0)

    try:
        # Second fork
        pid = os.fork()
        if pid > 0:
            # Parent process exits
            sys.exit(0)

    except OSError as e:
        raise DaemonError(f"Second fork failed: {e}") from e

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    # Redirect stdin to /dev/null
    with open('/dev/null', 'r') as f:
        os.dup2(f.fileno(), sys.stdin.fileno())

    # Redirect stdout and stderr
    if log_file:
        # Ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Redirect to log file
        with open(log_file, 'a+') as f:
            os.dup2(f.fileno(), sys.stdout.fileno())
            os.dup2(f.fileno(), sys.stderr.fileno())
    else:
        # Redirect to /dev/null
        with open('/dev/null', 'a+') as f:
            os.dup2(f.fileno(), sys.stdout.fileno())
            os.dup2(f.fileno(), sys.stderr.fileno())

    # Write PID file
    write_pid_file(pid_file)

    # Register cleanup on exit
    atexit.register(lambda: remove_pid_file(pid_file))

    logger.info(f"Daemon started with PID {os.getpid()}")


def daemonize_windows(
    pid_file: str,
    log_file: Optional[str] = None
) -> None:
    """
    Create background process on Windows.

    Note: This is a simplified version. For production Windows services,
    consider using pythonw.exe or Windows Service API.

    Args:
        pid_file: Path to PID file
        log_file: Path to log file (optional)

    Raises:
        DaemonError: If background process creation fails
    """
    try:
        # Write PID file for current process
        write_pid_file(pid_file)

        # Register cleanup on exit
        atexit.register(lambda: remove_pid_file(pid_file))

        # Redirect stdout/stderr if log file specified
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            sys.stdout = open(log_file, 'a')
            sys.stderr = open(log_file, 'a')

        logger.info(f"Background process started with PID {os.getpid()}")

    except Exception as e:
        raise DaemonError(f"Failed to create background process: {e}") from e


def daemonize(
    pid_file: str,
    log_file: Optional[str] = None,
    working_dir: str = "/"
) -> None:
    """
    Daemonize the current process (cross-platform).

    Args:
        pid_file: Path to PID file
        log_file: Path to log file (optional)
        working_dir: Working directory for daemon (Unix only)

    Raises:
        DaemonError: If daemonization fails
    """
    if is_windows():
        daemonize_windows(pid_file=pid_file, log_file=log_file)
    else:
        daemonize_unix(pid_file=pid_file, log_file=log_file, working_dir=working_dir)


def get_daemon_status(pid_file: str) -> dict:
    """
    Get daemon status information.

    Args:
        pid_file: Path to PID file

    Returns:
        Dictionary with status information:
        - running: True if daemon is running
        - pid: Process ID (or None)
        - pid_file_exists: True if PID file exists
    """
    pid = read_pid_file(pid_file)

    return {
        'running': is_process_running(pid) if pid else False,
        'pid': pid,
        'pid_file_exists': Path(pid_file).exists(),
    }
