"""
Integration tests for the full conference scanning workflow.

Real SQLite store, real extraction/fingerprinting/state machine; only the
network (fetcher) and the SMTP client are faked.
"""

from datetime import date, datetime, timedelta

import pytest

from conbot.main import ConferenceScanOrchestrator
from conbot.models.conference import WatchMode
from conbot.notification.email_client import SMTPEmailClient


def _page(body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Test Summit</title></head>
<body>
  <nav>Home | About | Contact</nav>
  <main><h1>Test Summit</h1>{body}</main>
  <footer>Copyright</footer>
</body></html>"""


def _deadline_page() -> str:
    d = date.today() + timedelta(days=60)
    return _page(
        "<h2>Call for Papers</h2>"
        "<p>We invite submissions for the Test Summit in the field of transport planning.</p>"
        "<h3>Important Dates</h3>"
        f"<ul><li>Abstract submission deadline: {d.strftime('%B')} {d.day}, {d.year}</li></ul>"
    )


NO_DATES_PAGE = _page(
    "<h2>Call for Papers coming soon</h2>"
    "<p>The call for papers will be announced in the coming weeks. Stay tuned.</p>"
)
CHANGED_NO_DATES_PAGE = _page(
    "<h2>Call for Papers coming soon</h2>"
    "<p>A completely different announcement: sponsors, venue details, keynote speakers "
    "and registration information are now published on this page. Stay tuned for more.</p>"
)


class FakeFetcher:
    """Serves pages from a dict; a value that is an Exception is raised."""

    def __init__(self):
        self.pages = {}
        self.calls = []

    def fetch(self, url, force_playwright=False):
        self.calls.append((url, force_playwright))
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page, "requests"

    def close(self):
        pass


class FakeEmailClient:
    """Records emails instead of sending them."""

    def __init__(self):
        self.sent = []

    def send_email(self, to_addresses, subject, html_body, text_body=None, **kwargs):
        self.sent.append({"to": to_addresses, "subject": subject, "html": html_body})
        return True

    strip_html = staticmethod(SMTPEmailClient.strip_html)


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "conferences.yaml"
    path.write_text("""
version: 1
defaults:
  throttle_seconds: 0
  keyword_groups:
    cfp: ["call for papers", "submission", "important dates", "deadline"]
    no_dates: ["coming soon", "stay tuned"]
conferences:
  - id: alpha
    name: "Alpha Summit"
    urls: ["https://alpha.example.org/"]
  - id: beta
    name: "Beta Congress"
    urls: ["https://beta.example.org/"]
    js_required: true
""")
    return str(path)


@pytest.fixture
def env(config_file, tmp_path):
    fetcher = FakeFetcher()
    fetcher.pages = {
        "https://alpha.example.org/": NO_DATES_PAGE,
        "https://beta.example.org/": NO_DATES_PAGE,
    }
    mailer = FakeEmailClient()
    db_path = str(tmp_path / "conbot.db")

    def make():
        return ConferenceScanOrchestrator(
            config_path=config_file,
            recipient_email="me@example.org",
            db_path=db_path,
            email_client=mailer,
            fetcher=fetcher,
        )

    return make, fetcher, mailer


def _state(orch, conference_id):
    return orch.store.get_conference_state(conference_id)


def _count(orch, table):
    from sqlalchemy import text
    with orch.store.engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


class TestInitialization:
    def test_creates_state_for_each_conference(self, env):
        make, _, _ = env
        orch = make()

        assert {s.conference_id for s in orch.store.get_all_conferences()} == {"alpha", "beta"}
        assert _state(orch, "alpha").watch_mode == WatchMode.MONTHLY

    def test_is_idempotent(self, env):
        make, _, _ = env
        make()
        orch = make()

        assert orch.initialize_conferences() == 0
        assert len(orch.store.get_all_conferences()) == 2

    def test_removed_conference_is_deactivated_and_can_return(self, env):
        make, _, _ = env
        orch = make()
        removed = orch.conferences_config.pop()  # beta

        orch.initialize_conferences()
        assert _state(orch, "beta").is_active is False
        assert [s.conference_id for s in orch.store.get_conferences_due_for_scan()] == ["alpha"]

        orch.conferences_config.append(removed)
        orch.initialize_conferences()
        assert _state(orch, "beta").is_active is True

    def test_url_change_resets_baseline(self, env):
        make, _, _ = env
        orch = make()
        orch.run_daily_scan()
        assert _state(orch, "alpha").binary_hash is not None

        orch.conferences_config[0]["primary_url"] = "https://alpha.example.org/new"
        orch.initialize_conferences()

        state = _state(orch, "alpha")
        assert str(state.url) == "https://alpha.example.org/new"
        assert state.binary_hash is None


class TestScanFlow:
    def test_baseline_without_dates_stays_monthly(self, env):
        make, _, mailer = env
        orch = make()

        results = orch.run_daily_scan()

        assert results == {"scanned": 2, "succeeded": 2, "failed": 0}
        state = _state(orch, "alpha")
        assert state.watch_mode == WatchMode.MONTHLY
        assert state.binary_hash is not None
        assert state.next_run_at > datetime.now() + timedelta(days=28)
        assert state.next_run_at.hour == 0
        assert all("No Changes" in m["subject"] for m in mailer.sent)

    def test_baseline_with_deadlines_goes_urgent_and_emails_dates(self, env):
        make, fetcher, mailer = env
        fetcher.pages["https://alpha.example.org/"] = _deadline_page()
        orch = make()

        orch.run_daily_scan()

        state = _state(orch, "alpha")
        assert state.watch_mode == WatchMode.URGENT
        assert len(state.current_deadlines) == 1
        assert state.next_run_at < datetime.now() + timedelta(days=2)
        alpha_mail = [m for m in mailer.sent if "Alpha Summit" in m["subject"]]
        assert len(alpha_mail) == 1
        assert "DEADLINES PUBLISHED" in alpha_mail[0]["subject"]
        assert alpha_mail[0]["to"] == ["me@example.org"]

    def test_only_due_conferences_are_scanned(self, env):
        make, _, _ = env
        orch = make()
        orch.run_daily_scan()

        assert orch.run_daily_scan()["scanned"] == 0

    def test_unchanged_page_is_no_change(self, env):
        make, _, mailer = env
        orch = make()
        orch.run_daily_scan()
        mailer.sent.clear()

        assert orch.scan_single_conference("alpha", force=True)

        assert _state(orch, "alpha").consecutive_no_change_count == 1
        assert "No Changes" in mailer.sent[0]["subject"]

    def test_change_without_dates_goes_biweekly(self, env):
        make, fetcher, mailer = env
        orch = make()
        orch.run_daily_scan()
        mailer.sent.clear()

        fetcher.pages["https://alpha.example.org/"] = CHANGED_NO_DATES_PAGE
        assert orch.scan_single_conference("alpha", force=True)

        assert _state(orch, "alpha").watch_mode == WatchMode.BIWEEKLY
        assert "Website Updated" in mailer.sent[0]["subject"]

    def test_scan_not_due_is_skipped_without_force(self, env):
        make, fetcher, _ = env
        orch = make()
        orch.run_daily_scan()
        fetcher.calls.clear()

        assert orch.scan_single_conference("alpha") is False
        assert fetcher.calls == []

    def test_js_required_forces_playwright(self, env):
        make, fetcher, _ = env
        make().run_daily_scan()

        flags = dict(fetcher.calls)
        assert flags["https://alpha.example.org/"] is False
        assert flags["https://beta.example.org/"] is True

    def test_state_survives_restart(self, env):
        make, fetcher, mailer = env
        make().run_daily_scan()
        mailer.sent.clear()

        orch = make()  # new process, same DB file
        assert orch.run_daily_scan()["scanned"] == 0
        assert _state(orch, "alpha").binary_hash is not None

    def test_audit_and_history_are_written(self, env):
        make, _, _ = env
        orch = make()
        orch.run_daily_scan()

        assert _count(orch, "conferences_audit") == 2
        assert _count(orch, "scan_history") == 2


class TestFailures:
    def test_failure_records_error_and_retries_next_run(self, env):
        make, fetcher, mailer = env
        fetcher.pages["https://alpha.example.org/"] = RuntimeError("boom")
        orch = make()

        results = orch.run_daily_scan()

        assert results == {"scanned": 2, "succeeded": 1, "failed": 1}
        state = _state(orch, "alpha")
        assert state.consecutive_error_count == 1
        assert state.next_run_at <= datetime.now()  # still due
        assert any("ConBOT Error" in m["subject"] for m in mailer.sent)

    def test_repeated_failures_do_not_email_every_time(self, env):
        make, fetcher, mailer = env
        fetcher.pages["https://alpha.example.org/"] = RuntimeError("boom")
        orch = make()

        for _ in range(3):
            orch.scan_single_conference("alpha", force=True)

        error_mails = [m for m in mailer.sent if "ConBOT Error" in m["subject"]]
        assert len(error_mails) == 1
        assert _state(orch, "alpha").consecutive_error_count == 3

    def test_success_resets_error_count(self, env):
        make, fetcher, _ = env
        fetcher.pages["https://alpha.example.org/"] = RuntimeError("boom")
        orch = make()
        orch.scan_single_conference("alpha", force=True)

        fetcher.pages["https://alpha.example.org/"] = NO_DATES_PAGE
        orch.scan_single_conference("alpha", force=True)

        assert _state(orch, "alpha").consecutive_error_count == 0


class TestForce:
    def test_force_scans_everything_even_if_not_due(self, env):
        make, fetcher, _ = env
        orch = make()
        orch.run_daily_scan()
        fetcher.calls.clear()

        assert orch.run_daily_scan()["scanned"] == 0
        assert orch.run_daily_scan(force=True)["scanned"] == 2
        assert len(fetcher.calls) == 2
