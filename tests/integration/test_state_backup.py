"""
Round-trip test for the JSON state backup used by the GitHub Actions workflow.

The workflow restores state from JSON into a brand-new SQLite file, scans,
then exports the state again, so this path has to be lossless.
"""

import pytest
from click.testing import CliRunner

from conbot.cli import cli
from conbot.main import ConferenceScanOrchestrator

from .test_full_scan_flow import (  # noqa: F401  (fixtures)
    FakeEmailClient,
    FakeFetcher,
    NO_DATES_PAGE,
    _deadline_page,
    config_file,
)


def _orchestrator(config_file, db_path, fetcher, mailer):
    return ConferenceScanOrchestrator(
        config_path=config_file,
        recipient_email="me@example.org",
        db_path=db_path,
        email_client=mailer,
        fetcher=fetcher,
    )


def test_backup_restore_roundtrip(config_file, tmp_path):
    fetcher = FakeFetcher()
    fetcher.pages = {
        "https://alpha.example.org/": _deadline_page(),
        "https://beta.example.org/": NO_DATES_PAGE,
    }
    mailer = FakeEmailClient()

    # Run 1: fresh DB, baseline scan, then back up
    db1 = str(tmp_path / "run1.db")
    first = _orchestrator(config_file, db1, fetcher, mailer)
    first.run_daily_scan()
    expected = {s.conference_id: s for s in first.store.get_all_conferences()}
    first.store.close()

    state_dir = tmp_path / "state"
    runner = CliRunner()
    result = runner.invoke(cli, ["db", "backup", "-d", db1, "-o", str(state_dir)])
    assert result.exit_code == 0, result.output

    # Run 2: brand-new DB file, restore, then construct the orchestrator
    db2 = str(tmp_path / "run2.db")
    result = runner.invoke(cli, [
        "db", "restore", "-d", db2,
        "--current", str(state_dir / "current.json"),
        "--audit", str(state_dir / "audit.json"),
        "--history", str(state_dir / "history.json"),
    ])
    assert result.exit_code == 0, result.output

    mailer.sent.clear()
    second = _orchestrator(config_file, db2, fetcher, mailer)

    restored = {s.conference_id: s for s in second.store.get_all_conferences()}
    assert restored.keys() == expected.keys()
    for conference_id, state in expected.items():
        got = restored[conference_id]
        assert got.watch_mode == state.watch_mode
        assert got.next_run_at == state.next_run_at
        assert got.binary_hash == state.binary_hash
        assert got.simhash_signature == state.simhash_signature  # unsigned 64-bit survives
        assert got.current_deadlines == state.current_deadlines

    # Nothing is due, so the restored run must not re-baseline or send mail
    assert second.run_daily_scan()["scanned"] == 0
    assert mailer.sent == []

    # Audit/history came across too
    from sqlalchemy import text
    with second.store.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM conferences_audit")).scalar() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM scan_history")).scalar() == 2


def test_restore_twice_is_harmless(config_file, tmp_path):
    fetcher = FakeFetcher()
    fetcher.pages = {
        "https://alpha.example.org/": NO_DATES_PAGE,
        "https://beta.example.org/": NO_DATES_PAGE,
    }
    db1 = str(tmp_path / "a.db")
    orch = _orchestrator(config_file, db1, fetcher, FakeEmailClient())
    orch.run_daily_scan()
    orch.store.close()

    runner = CliRunner()
    state_dir = tmp_path / "state"
    runner.invoke(cli, ["db", "backup", "-d", db1, "-o", str(state_dir)])

    args = ["db", "restore", "-d", str(tmp_path / "b.db"),
            "--current", str(state_dir / "current.json"),
            "--audit", str(state_dir / "audit.json"),
            "--history", str(state_dir / "history.json")]
    assert runner.invoke(cli, args).exit_code == 0
    assert runner.invoke(cli, args).exit_code == 0
