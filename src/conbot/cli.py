"""
Command-line interface for ConBOT.

Provides commands for:
- Daemon management (start, stop, restart, status, logs)
- Manual scanning (scan conferences)
- Database management (init, vacuum, backup, restore)
- Configuration (show, validate, init)
- Utilities (test-email, version)

Usage:
    conbot daemon start
    conbot scan --all
    conbot db init
    conbot test-email
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import click
import logging

# Package version
__version__ = "1.0.0"

# Default paths
DEFAULT_CONFIG_DIR = Path.home() / ".conbot"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config" / "conferences.yaml"
DEFAULT_DB_PATH = DEFAULT_CONFIG_DIR / "conbot.db"
DEFAULT_PID_FILE = DEFAULT_CONFIG_DIR / "conbot.pid"
DEFAULT_LOG_FILE = DEFAULT_CONFIG_DIR / "logs" / "conbot.log"


# ============================================================================
# Main CLI Group
# ============================================================================

@click.group()
@click.version_option(version=__version__, prog_name="conbot")
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def cli(verbose):
    """
    ConBOT - Conference Deadline Monitor

    Automated monitoring of academic conference websites for Call for Papers
    announcements and submission deadlines.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)


# ============================================================================
# Daemon Commands
# ============================================================================

@cli.group()
def daemon():
    """Daemon management commands."""
    pass


@daemon.command()
@click.option('--config', '-c', default=str(DEFAULT_CONFIG_PATH),
              help='Path to conferences.yaml')
@click.option('--recipient-email', '-r', required=True,
              help='Email address for notifications')
@click.option('--sender-email', '-s', default=None,
              help='SES sender email (default: from env)')
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
@click.option('--pid-file', '-p', default=str(DEFAULT_PID_FILE),
              help='Path to PID file')
@click.option('--log-file', '-l', default=str(DEFAULT_LOG_FILE),
              help='Path to log file')
@click.option('--foreground', '-f', is_flag=True,
              help='Run in foreground (no daemonization)')
@click.option('--scan-hour', default=9, type=int,
              help='Hour to run daily scan (default: 9 = 09:00 AM)')
@click.option('--scan-minute', default=0, type=int,
              help='Minute to run daily scan (default: 0)')
def start(config, recipient_email, sender_email, db_path, pid_file, log_file,
          foreground, scan_hour, scan_minute):
    """Start the ConBOT daemon."""
    try:
        from .scheduling.daemon import ConBOTDaemon

        click.echo("Starting ConBOT daemon...")

        daemon = ConBOTDaemon(
            config_path=config,
            recipient_email=recipient_email,
            sender_email=sender_email,
            db_path=db_path,
            pid_file=pid_file,
            log_file=log_file,
            scan_hour=scan_hour,
            scan_minute=scan_minute,
        )

        daemon.start(foreground=foreground)

        if foreground:
            click.echo("Daemon started in foreground mode (Press Ctrl+C to stop)")
        else:
            click.echo(f"✓ Daemon started successfully")
            click.echo(f"  PID file: {pid_file}")
            click.echo(f"  Log file: {log_file}")
            click.echo(f"  Daily scans at: {scan_hour:02d}:{scan_minute:02d}")

    except Exception as e:
        click.echo(f"✗ Failed to start daemon: {e}", err=True)
        sys.exit(1)


@daemon.command()
@click.option('--pid-file', '-p', default=str(DEFAULT_PID_FILE),
              help='Path to PID file')
def stop(pid_file):
    """Stop the ConBOT daemon."""
    try:
        from .scheduling.daemon import ConBOTDaemon

        click.echo("Stopping ConBOT daemon...")

        daemon = ConBOTDaemon(
            config_path=str(DEFAULT_CONFIG_PATH),
            recipient_email="dummy",  # Not used for stop
            pid_file=pid_file,
        )

        daemon.stop()
        click.echo("✓ Daemon stopped successfully")

    except Exception as e:
        click.echo(f"✗ Failed to stop daemon: {e}", err=True)
        sys.exit(1)


@daemon.command()
@click.option('--config', '-c', default=str(DEFAULT_CONFIG_PATH),
              help='Path to conferences.yaml')
@click.option('--recipient-email', '-r', required=True,
              help='Email address for notifications')
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
@click.option('--pid-file', '-p', default=str(DEFAULT_PID_FILE),
              help='Path to PID file')
@click.option('--foreground', '-f', is_flag=True,
              help='Run in foreground after restart')
def restart(config, recipient_email, db_path, pid_file, foreground):
    """Restart the ConBOT daemon."""
    try:
        from .scheduling.daemon import ConBOTDaemon

        click.echo("Restarting ConBOT daemon...")

        daemon = ConBOTDaemon(
            config_path=config,
            recipient_email=recipient_email,
            db_path=db_path,
            pid_file=pid_file,
        )

        daemon.restart(foreground=foreground)
        click.echo("✓ Daemon restarted successfully")

    except Exception as e:
        click.echo(f"✗ Failed to restart daemon: {e}", err=True)
        sys.exit(1)


@daemon.command()
@click.option('--pid-file', '-p', default=str(DEFAULT_PID_FILE),
              help='Path to PID file')
def status(pid_file):
    """Check daemon status."""
    try:
        from .scheduling.daemon import ConBOTDaemon
        from .utils.daemonize import get_daemon_status

        daemon_status = get_daemon_status(pid_file)

        if daemon_status['running']:
            click.echo("✓ Daemon is running")
            click.echo(f"  PID: {daemon_status['pid']}")
            click.echo(f"  PID file: {pid_file}")

            # Try to get next run time
            daemon = ConBOTDaemon(
                config_path=str(DEFAULT_CONFIG_PATH),
                recipient_email="dummy",
                pid_file=pid_file,
            )
            status_info = daemon.status()
            if status_info.get('next_run'):
                click.echo(f"  Next scan: {status_info['next_run']}")
        else:
            click.echo("✗ Daemon is not running")
            if daemon_status['pid_file_exists']:
                click.echo(f"  Stale PID file exists: {pid_file}")

    except Exception as e:
        click.echo(f"✗ Error checking status: {e}", err=True)
        sys.exit(1)


@daemon.command()
@click.option('--pid-file', '-p', default=str(DEFAULT_PID_FILE),
              help='Path to PID file')
@click.option('--log-file', '-l', default=str(DEFAULT_LOG_FILE),
              help='Path to log file')
@click.option('--lines', '-n', default=50, type=int,
              help='Number of lines to show (default: 50)')
@click.option('--follow', '-f', is_flag=True,
              help='Follow log output (like tail -f)')
def logs(pid_file, log_file, lines, follow):
    """View daemon logs."""
    try:
        if not Path(log_file).exists():
            click.echo(f"✗ Log file does not exist: {log_file}", err=True)
            sys.exit(1)

        if follow:
            # Follow log file (tail -f behavior)
            click.echo(f"Following {log_file} (Press Ctrl+C to stop)")
            import subprocess
            subprocess.run(['tail', '-f', log_file])
        else:
            # Show last N lines
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:]
                click.echo(''.join(recent_lines))

    except KeyboardInterrupt:
        click.echo("\nStopped following logs")
    except Exception as e:
        click.echo(f"✗ Error reading logs: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Scan Commands
# ============================================================================

@cli.command()
@click.option('--config', '-c', default=str(DEFAULT_CONFIG_PATH),
              help='Path to conferences.yaml')
@click.option('--recipient-email', '-r', required=True,
              help='Email address for notifications')
@click.option('--sender-email', '-s', default=None,
              help='SES sender email (default: from env)')
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
@click.option('--all', 'scan_all', is_flag=True,
              help='Scan all conferences')
@click.option('--id', 'conference_id', default=None,
              help='Scan specific conference by ID')
@click.option('--force', '-f', is_flag=True,
              help='Force scan (ignore next_run_at)')
def scan(config, recipient_email, sender_email, db_path, scan_all, conference_id, force):
    """Run manual conference scan."""
    try:
        from .main import ConferenceScanOrchestrator

        if not scan_all and not conference_id:
            click.echo("✗ Must specify either --all or --id", err=True)
            sys.exit(1)

        click.echo("Initializing orchestrator...")
        orchestrator = ConferenceScanOrchestrator(
            config_path=config,
            recipient_email=recipient_email,
            sender_email=sender_email,
            db_path=db_path,
        )

        if scan_all:
            click.echo("Scanning all conferences...")
            results = orchestrator.run_daily_scan()

            click.echo("\nScan Results:")
            click.echo(f"  Scanned: {results['scanned']}")
            click.echo(f"  Succeeded: {results['succeeded']}")
            click.echo(f"  Failed: {results['failed']}")

        elif conference_id:
            click.echo(f"Scanning conference: {conference_id}")
            success = orchestrator.scan_single_conference(conference_id, force=force)

            if success:
                click.echo(f"✓ Scan completed for {conference_id}")
            else:
                click.echo(f"✗ Scan failed for {conference_id}", err=True)
                sys.exit(1)

    except Exception as e:
        click.echo(f"✗ Scan failed: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Database Commands
# ============================================================================

@cli.group()
def db():
    """Database management commands."""
    pass


@db.command()
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
def init(db_path):
    """Initialize database schema."""
    try:
        from .db.migrations import initialize_database

        click.echo(f"Initializing database: {db_path}")
        initialize_database(db_path)
        click.echo("✓ Database initialized successfully")

    except Exception as e:
        click.echo(f"✗ Failed to initialize database: {e}", err=True)
        sys.exit(1)


@db.command()
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
def vacuum(db_path):
    """Vacuum database to reclaim space."""
    try:
        from .db.migrations import vacuum_database

        click.echo(f"Vacuuming database: {db_path}")
        vacuum_database(db_path)
        click.echo("✓ Database vacuumed successfully")

    except Exception as e:
        click.echo(f"✗ Failed to vacuum database: {e}", err=True)
        sys.exit(1)


@db.command()
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
@click.option('--output-dir', '-o', default=None,
              help='Output directory for backup (default: ./backup_TIMESTAMP)')
def backup(db_path, output_dir):
    """Backup database to JSON files."""
    try:
        from .db.migrations import export_to_json

        click.echo(f"Backing up database: {db_path}")
        files = export_to_json(db_path, output_dir=output_dir)

        click.echo("✓ Backup complete:")
        for table, file_path in files.items():
            click.echo(f"  {table}: {file_path}")

    except Exception as e:
        click.echo(f"✗ Backup failed: {e}", err=True)
        sys.exit(1)


@db.command()
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
@click.option('--current', default=None, help='Path to current.json')
@click.option('--audit', default=None, help='Path to audit.json')
@click.option('--history', default=None, help='Path to history.json')
def restore(db_path, current, audit, history):
    """Restore database from JSON files."""
    try:
        from .db.migrations import import_from_json

        if not any([current, audit, history]):
            click.echo("✗ Must specify at least one JSON file to restore", err=True)
            sys.exit(1)

        click.echo(f"Restoring database: {db_path}")
        counts = import_from_json(
            db_path,
            current_file=current,
            audit_file=audit,
            history_file=history
        )

        click.echo("✓ Restore complete:")
        for table, count in counts.items():
            click.echo(f"  {table}: {count} records")

    except Exception as e:
        click.echo(f"✗ Restore failed: {e}", err=True)
        sys.exit(1)


@db.command()
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
def stats(db_path):
    """Show database statistics."""
    try:
        from .state.sqlite_store import SQLiteStore
        from sqlalchemy import text

        store = SQLiteStore(db_path=db_path)

        click.echo("Database Statistics:")
        click.echo("=" * 60)

        # Get conference counts
        result = store.query(text("SELECT COUNT(*) as count FROM conferences_current"))
        total_conferences = list(result)[0][0]
        click.echo(f"Total conferences: {total_conferences}")

        result = store.query(text("SELECT COUNT(*) as count FROM conferences_current WHERE is_active = 1"))
        active_conferences = list(result)[0][0]
        click.echo(f"Active conferences: {active_conferences}")

        # Get audit counts
        result = store.query(text("SELECT COUNT(*) as count FROM conferences_audit"))
        total_scans = list(result)[0][0]
        click.echo(f"Total scans: {total_scans}")

        # Get scan history
        result = store.query(text("SELECT COUNT(*) as count FROM scan_history"))
        history_count = list(result)[0][0]
        click.echo(f"History records: {history_count}")

        # Database file size
        if Path(db_path).exists():
            size_mb = Path(db_path).stat().st_size / (1024 * 1024)
            click.echo(f"Database size: {size_mb:.2f} MB")

        store.close()

    except Exception as e:
        click.echo(f"✗ Failed to get statistics: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Config Commands
# ============================================================================

@cli.group()
def config():
    """Configuration management commands."""
    pass


@config.command()
@click.option('--config', '-c', default=str(DEFAULT_CONFIG_PATH),
              help='Path to conferences.yaml')
def show(config):
    """Show current configuration."""
    try:
        from .utils.config import load_conference_config

        conferences = load_conference_config(config)

        click.echo("Conference Configuration:")
        click.echo("=" * 60)
        click.echo(f"Config file: {config}")
        click.echo(f"Total conferences: {len(conferences)}")
        click.echo()

        for conf in conferences:
            click.echo(f"  • {conf.id}")
            click.echo(f"    Name: {conf.name}")
            click.echo(f"    URL: {conf.url}")
            click.echo()

    except Exception as e:
        click.echo(f"✗ Failed to load config: {e}", err=True)
        sys.exit(1)


@config.command()
@click.option('--config', '-c', default=str(DEFAULT_CONFIG_PATH),
              help='Path to conferences.yaml')
def validate(config):
    """Validate configuration file."""
    try:
        from .utils.config import load_conference_config

        click.echo(f"Validating config: {config}")
        conferences = load_conference_config(config)

        click.echo(f"✓ Configuration valid ({len(conferences)} conferences)")

    except Exception as e:
        click.echo(f"✗ Configuration invalid: {e}", err=True)
        sys.exit(1)


@config.command()
@click.option('--config', '-c', default=str(DEFAULT_CONFIG_PATH),
              help='Path to conferences.yaml')
@click.option('--db-path', '-d', default=str(DEFAULT_DB_PATH),
              help='Path to SQLite database')
def init_conferences(config, db_path):
    """Initialize conferences from YAML config."""
    try:
        from .utils.config import load_conference_config
        from .state.sqlite_store import SQLiteStore
        from .models.conference import ConferenceState, WatchMode
        from datetime import datetime, timedelta

        click.echo("Loading configuration...")
        conferences = load_conference_config(config)

        click.echo("Initializing database...")
        store = SQLiteStore(db_path=db_path)

        for conf in conferences:
            # Create initial state
            state = ConferenceState(
                conference_id=conf.id,
                url=conf.url,
                watch_mode=WatchMode.MONTHLY,
                next_run_at=datetime.now(),  # Scan immediately
                is_active=True,
            )

            store.upsert_conference(state)
            click.echo(f"  ✓ Initialized: {conf.id}")

        store.close()
        click.echo(f"\n✓ Initialized {len(conferences)} conferences")

    except Exception as e:
        click.echo(f"✗ Initialization failed: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Utility Commands
# ============================================================================

@cli.command()
@click.option('--recipient-email', '-r', required=True,
              help='Email address to send test to')
@click.option('--sender-email', '-s', default=None,
              help='SES sender email (default: from env)')
def test_email(recipient_email, sender_email):
    """Send a test email via AWS SES."""
    try:
        from .notification.email_client import SESEmailClient
        from .utils.secrets import get_secret

        sender = sender_email or get_secret("email-credentials", "sender-email")

        click.echo(f"Sending test email...")
        click.echo(f"  From: {sender}")
        click.echo(f"  To: {recipient_email}")

        client = SESEmailClient(sender_email=sender)

        # Send test email
        success = client.send_email(
            to_email=recipient_email,
            subject="ConBOT Test Email",
            html_body="""
            <h1>ConBOT Test Email</h1>
            <p>This is a test email from ConBOT.</p>
            <p>If you received this, AWS SES is configured correctly!</p>
            <p><em>Sent at: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</em></p>
            """
        )

        if success:
            click.echo("✓ Test email sent successfully!")
            click.echo("  Check your inbox (including spam folder)")
        else:
            click.echo("✗ Failed to send test email", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"✗ Test email failed: {e}", err=True)
        sys.exit(1)


@cli.command()
def version():
    """Show ConBOT version."""
    click.echo(f"ConBOT version {__version__}")


if __name__ == '__main__':
    cli()
