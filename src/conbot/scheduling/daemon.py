"""
APScheduler-based daemon for ConBOT.

Replaces Databricks Workflows with a local scheduler daemon that:
- Runs daily conference scans at 09:00 AM
- Manages PID file for process control
- Provides start/stop/restart/status operations
- Supports graceful shutdown

Requires APScheduler package.
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import signal

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from ..utils.daemonize import (
    daemonize,
    write_pid_file,
    read_pid_file,
    remove_pid_file,
    is_process_running,
    kill_process,
    get_daemon_status,
    DaemonError,
)

logger = logging.getLogger(__name__)


class ConBOTDaemon:
    """
    Background daemon for scheduled conference scans.

    Uses APScheduler to run daily scans at 09:00 AM local time.

    Example:
        >>> daemon = ConBOTDaemon(
        ...     config_path="~/.conbot/config/conferences.yaml",
        ...     recipient_email="user@example.com"
        ... )
        >>> daemon.start()  # Daemonize and schedule
        >>> daemon.status()  # Check if running
        >>> daemon.stop()   # Graceful shutdown
    """

    def __init__(
        self,
        config_path: str,
        recipient_email: str,
        sender_email: Optional[str] = None,
        db_path: Optional[str] = None,
        pid_file: Optional[str] = None,
        log_file: Optional[str] = None,
        scan_hour: int = 9,
        scan_minute: int = 0,
    ):
        """
        Initialize daemon configuration.

        Args:
            config_path: Path to conferences.yaml
            recipient_email: Email address for notifications
            sender_email: SES sender email (optional, uses env var if None)
            db_path: Path to SQLite database (default: ~/.conbot/conbot.db)
            pid_file: Path to PID file (default: ~/.conbot/conbot.pid)
            log_file: Path to log file (default: ~/.conbot/logs/conbot.log)
            scan_hour: Hour to run daily scan (default: 9 = 09:00 AM)
            scan_minute: Minute to run daily scan (default: 0)
        """
        self.config_path = os.path.expanduser(config_path)
        self.recipient_email = recipient_email
        self.sender_email = sender_email

        # Paths
        conbot_dir = Path.home() / ".conbot"
        self.db_path = db_path or str(conbot_dir / "conbot.db")
        self.pid_file = pid_file or str(conbot_dir / "conbot.pid")
        self.log_file = log_file or str(conbot_dir / "logs" / "conbot.log")

        # Schedule
        self.scan_hour = scan_hour
        self.scan_minute = scan_minute

        # Scheduler (initialized in start())
        self.scheduler: Optional[BackgroundScheduler] = None

    def _setup_logging(self):
        """Configure logging to file."""
        log_path = Path(self.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def _run_daily_scan(self):
        """
        Run daily scan workflow.

        This is the job function called by APScheduler.
        """
        try:
            logger.info("=" * 80)
            logger.info("Daily scan triggered by scheduler")
            logger.info("=" * 80)

            # Import here to avoid circular dependencies
            from ..main import ConferenceScanOrchestrator

            # Create orchestrator
            orchestrator = ConferenceScanOrchestrator(
                config_path=self.config_path,
                recipient_email=self.recipient_email,
                sender_email=self.sender_email,
                db_path=self.db_path,
            )

            # Run scan
            results = orchestrator.run_daily_scan()

            logger.info(f"Daily scan complete: {results}")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Daily scan failed: {e}", exc_info=True)
            # Don't re-raise - scheduler should continue

    def _job_listener(self, event):
        """
        Listen to scheduler events for logging.

        Args:
            event: APScheduler event
        """
        if event.exception:
            logger.error(f"Job failed: {event.exception}")
        else:
            logger.info(f"Job completed successfully at {datetime.now()}")

    def start(self, foreground: bool = False):
        """
        Start the daemon.

        Args:
            foreground: If True, run in foreground (no daemonization)

        Raises:
            DaemonError: If daemon is already running or start fails
        """
        # Check if already running
        if self.is_running():
            pid = read_pid_file(self.pid_file)
            raise DaemonError(f"Daemon already running (PID: {pid})")

        logger.info("Starting ConBOT daemon")

        # Setup logging
        self._setup_logging()

        # Daemonize (unless foreground mode)
        if not foreground:
            logger.info(f"Daemonizing process (PID file: {self.pid_file})")
            daemonize(
                pid_file=self.pid_file,
                log_file=self.log_file,
                working_dir=str(Path.home())
            )
        else:
            logger.info("Running in foreground mode")
            write_pid_file(self.pid_file)

        # Initialize scheduler
        self.scheduler = BackgroundScheduler(
            timezone='UTC',  # Use local timezone or UTC
            job_defaults={
                'coalesce': True,  # Combine missed runs
                'max_instances': 1,  # Prevent overlapping scans
                'misfire_grace_time': 3600,  # Allow 1 hour grace for missed jobs
            }
        )

        # Add job listener
        self.scheduler.add_listener(
            self._job_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        # Schedule daily job
        self.scheduler.add_job(
            func=self._run_daily_scan,
            trigger=CronTrigger(hour=self.scan_hour, minute=self.scan_minute),
            id='daily_scan',
            name='ConBOT Daily Conference Scan',
            replace_existing=True,
        )

        # Start scheduler
        self.scheduler.start()

        next_run = self.scheduler.get_job('daily_scan').next_run_time
        logger.info(f"Scheduler started. Next scan: {next_run}")
        logger.info(f"Daily scans scheduled at {self.scan_hour:02d}:{self.scan_minute:02d} local time")

        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down gracefully")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        # Keep daemon running
        if foreground:
            logger.info("Press Ctrl+C to stop")
            try:
                # Keep main thread alive
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self.stop()
        else:
            # In background mode, keep running until killed
            try:
                while True:
                    time.sleep(60)
            except Exception as e:
                logger.error(f"Daemon error: {e}")
                self.stop()
                raise

    def stop(self):
        """
        Stop the daemon gracefully.

        Raises:
            DaemonError: If daemon is not running or stop fails
        """
        pid = read_pid_file(self.pid_file)

        if not pid:
            raise DaemonError("Daemon is not running (no PID file)")

        if not is_process_running(pid):
            logger.warning(f"PID file exists but process {pid} is not running")
            remove_pid_file(self.pid_file)
            return

        logger.info(f"Stopping daemon (PID: {pid})")

        # Shutdown scheduler if running in this process
        if self.scheduler and self.scheduler.running:
            logger.info("Shutting down scheduler")
            self.scheduler.shutdown(wait=True)

        # Kill process if this is a different process
        if pid != os.getpid():
            success = kill_process(pid, timeout=10)
            if not success:
                raise DaemonError(f"Failed to stop daemon (PID: {pid})")

        # Remove PID file
        remove_pid_file(self.pid_file)

        logger.info("Daemon stopped successfully")

    def restart(self, foreground: bool = False):
        """
        Restart the daemon.

        Args:
            foreground: If True, run in foreground after restart

        Raises:
            DaemonError: If restart fails
        """
        logger.info("Restarting daemon")

        # Stop if running
        if self.is_running():
            self.stop()
            time.sleep(2)  # Wait for clean shutdown

        # Start again
        self.start(foreground=foreground)

    def is_running(self) -> bool:
        """
        Check if daemon is running.

        Returns:
            True if daemon is running, False otherwise
        """
        status = get_daemon_status(self.pid_file)
        return status['running']

    def status(self) -> dict:
        """
        Get daemon status information.

        Returns:
            Dictionary with status details:
            - running: True if running
            - pid: Process ID (or None)
            - pid_file: Path to PID file
            - log_file: Path to log file
            - next_run: Next scheduled run time (if running)
        """
        daemon_status = get_daemon_status(self.pid_file)

        status = {
            'running': daemon_status['running'],
            'pid': daemon_status['pid'],
            'pid_file': self.pid_file,
            'log_file': self.log_file,
            'config_path': self.config_path,
            'db_path': self.db_path,
            'next_run': None,
        }

        # Get next run time if scheduler is running in this process
        if self.scheduler and self.scheduler.running:
            job = self.scheduler.get_job('daily_scan')
            if job:
                status['next_run'] = job.next_run_time

        return status

    def get_logs(self, num_lines: int = 50) -> str:
        """
        Get recent log entries.

        Args:
            num_lines: Number of lines to retrieve

        Returns:
            Recent log contents
        """
        try:
            if not Path(self.log_file).exists():
                return "Log file does not exist"

            with open(self.log_file, 'r') as f:
                lines = f.readlines()
                return ''.join(lines[-num_lines:])

        except Exception as e:
            return f"Error reading logs: {e}"
