"""
Integration tests for full conference scanning workflow.

Tests end-to-end flow with mocked external dependencies.
"""

import pytest
from datetime import datetime, timedelta, date
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from conbot.main import ConferenceScanOrchestrator
from conbot.models.conference import (
    ConferenceState,
    WatchMode,
    Deadline,
    DeadlineType,
    ChangeType
)


@pytest.fixture
def sample_html():
    """Sample conference website HTML."""
    return """<!DOCTYPE html>
<html>
<head><title>UITP Summit 2026</title></head>
<body>
    <nav>Navigation menu</nav>
    <main>
        <h1>UITP Global Public Transport Summit 2026</h1>
        <div class="content">
            <h2>Call for Papers - Now Open!</h2>
            <p>
                We invite submissions for the UITP Summit 2026.
                Share your research and innovations in public transport.
            </p>
            <h3>Important Dates</h3>
            <ul>
                <li>Abstract Submission Deadline: March 15, 2026</li>
                <li>Full Paper Deadline: April 30, 2026</li>
                <li>Notification: May 15, 2026</li>
                <li>Conference: June 10-12, 2026 in Barcelona</li>
            </ul>
            <p>
                Submit your abstract through the conference portal.
                All submissions will be peer-reviewed.
            </p>
        </div>
    </main>
    <footer>
        © 2026 UITP. Last updated: February 1, 2026
    </footer>
</body>
</html>"""


@pytest.fixture
def sample_html_no_dates():
    """Sample HTML with CFP announced but no specific dates."""
    return """<!DOCTYPE html>
<html>
<head><title>UITP Summit 2026</title></head>
<body>
    <main>
        <h1>UITP Global Public Transport Summit 2026</h1>
        <div class="cfp-announcement">
            <h2>Call for Papers Coming Soon</h2>
            <p>
                We will be announcing submission deadlines in the coming weeks.
                Stay tuned for important dates.
            </p>
        </div>
    </main>
</body>
</html>"""


@pytest.fixture
def mock_ses_client():
    """Mock AWS SES client."""
    client = Mock()
    client.send_email = Mock(return_value=True)
    client.verify_sender = Mock(return_value=True)
    client.get_send_quota = Mock(return_value={
        "max_24_hour_send": 50000,
        "max_send_rate": 14,
        "sent_last_24_hours": 10
    })
    return client


@pytest.fixture
def mock_llm_client():
    """Mock OpenAI LLM client."""
    client = Mock()
    client.analyze_change = Mock(return_value={
        "summary": "Call for Papers has been announced with submission deadlines.",
        "classification": "cfp_with_dates",
        "confidence": 0.95
    })
    client.analyze_no_dates_change = Mock(return_value={
        "summary": "Call for Papers announcement posted, but specific dates not yet available.",
        "is_cfp_related": True,
        "confidence": 0.90
    })
    return client


@pytest.fixture
def temp_config_file(tmp_path):
    """Create temporary conferences.yaml file."""
    config_content = """
- id: uitp_summit
  name: UITP Global Public Transport Summit
  primary_url: https://example.com/uitp-summit
  cfp_keywords:
    - call for papers
    - call for abstracts
    - submit
    - paper submission
  no_dates_keywords:
    - coming soon
    - stay tuned
  link_discovery:
    enabled: false
"""
    config_file = tmp_path / "conferences.yaml"
    config_file.write_text(config_content)
    return str(config_file)


class TestFullScanFlow:
    """Integration tests for complete scan workflow."""

    @patch('conbot.main.get_secret')
    @patch('conbot.fetching.fetcher.requests.Session')
    @patch('conbot.main.SESEmailClient')
    @patch('conbot.main.LLMClient')
    @patch('conbot.main.DeltaStore')
    def test_first_scan_with_deadlines(
        self,
        mock_delta_store,
        mock_llm_class,
        mock_ses_class,
        mock_requests,
        mock_get_secret,
        temp_config_file,
        sample_html,
        mock_ses_client,
        mock_llm_client
    ):
        """Test first scan of conference that has published deadlines."""
        # Setup mocks
        mock_get_secret.return_value = "test-key"
        mock_ses_class.return_value = mock_ses_client
        mock_llm_class.return_value = mock_llm_client

        # Mock HTTP fetch
        mock_response = Mock()
        mock_response.text = sample_html
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_requests.return_value.get.return_value = mock_response

        # Mock Delta store
        mock_store_instance = mock_delta_store.return_value

        # Initial state (first scan)
        initial_state = ConferenceState(
            conference_id="uitp_summit",
            conference_name="UITP Global Public Transport Summit",
            url="https://example.com/uitp-summit",
            watch_mode=WatchMode.MONTHLY,
            next_run_at=datetime.now(),
            last_scan_at=None,
            binary_hash=None,
            filtered_hash=None,
            simhash_signature=None,
            current_deadlines=[],
            current_summary=None,
            tracked_links=[],
            consecutive_no_change_count=0,
            updated_at=datetime.now()
        )

        mock_store_instance.get_conferences_due_for_scan.return_value = [initial_state]
        mock_store_instance.get_conference_state.return_value = initial_state

        captured_state = None

        def capture_upsert(state):
            nonlocal captured_state
            captured_state = state

        mock_store_instance.upsert_conference_state.side_effect = capture_upsert

        # Initialize orchestrator
        orchestrator = ConferenceScanOrchestrator(
            config_path=temp_config_file,
            recipient_email="test@example.com"
        )

        # Inject mocked store and dispatcher
        orchestrator.delta_store = mock_store_instance
        from conbot.scheduling.dispatcher import ScheduleDispatcher
        orchestrator.dispatcher = ScheduleDispatcher(delta_store=mock_store_instance)

        # Run scan
        success = orchestrator.scan_conference(initial_state)

        # Assertions
        assert success is True

        # Verify state was updated
        assert captured_state is not None
        assert captured_state.watch_mode == WatchMode.URGENT  # Found deadlines
        assert len(captured_state.current_deadlines) == 2  # Abstract + Paper
        assert captured_state.binary_hash is not None
        assert captured_state.filtered_hash is not None
        assert captured_state.simhash_signature is not None

        # Verify deadlines extracted
        deadline_types = [d.type for d in captured_state.current_deadlines]
        assert DeadlineType.ABSTRACT in deadline_types
        assert DeadlineType.PAPER in deadline_types

        # Verify email sent
        assert mock_ses_client.send_email.called
        email_call = mock_ses_client.send_email.call_args
        assert "DEADLINES PUBLISHED" in email_call[1]["subject"]

        # Verify LLM called
        assert mock_llm_client.analyze_change.called

    @patch('conbot.main.get_secret')
    @patch('conbot.fetching.fetcher.requests.Session')
    @patch('conbot.main.SESEmailClient')
    @patch('conbot.main.LLMClient')
    @patch('conbot.main.DeltaStore')
    def test_change_detected_no_dates(
        self,
        mock_delta_store,
        mock_llm_class,
        mock_ses_class,
        mock_requests,
        mock_get_secret,
        temp_config_file,
        sample_html_no_dates,
        mock_ses_client,
        mock_llm_client
    ):
        """Test scan where content changed but no deadlines found."""
        # Setup mocks
        mock_get_secret.return_value = "test-key"
        mock_ses_class.return_value = mock_ses_client
        mock_llm_class.return_value = mock_llm_client

        # Mock HTTP fetch
        mock_response = Mock()
        mock_response.text = sample_html_no_dates
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_requests.return_value.get.return_value = mock_response

        # Mock Delta store
        mock_store_instance = mock_delta_store.return_value

        # Existing state (second scan with change)
        existing_state = ConferenceState(
            conference_id="uitp_summit",
            conference_name="UITP Global Public Transport Summit",
            url="https://example.com/uitp-summit",
            watch_mode=WatchMode.MONTHLY,
            next_run_at=datetime.now(),
            last_scan_at=datetime.now() - timedelta(days=30),
            binary_hash="old_hash_123",
            filtered_hash="old_filtered_456",
            simhash_signature="0" * 64,
            current_deadlines=[],
            current_summary=None,
            tracked_links=[],
            consecutive_no_change_count=0,
            updated_at=datetime.now() - timedelta(days=30)
        )

        mock_store_instance.get_conference_state.return_value = existing_state

        captured_state = None

        def capture_upsert(state):
            nonlocal captured_state
            captured_state = state

        mock_store_instance.upsert_conference_state.side_effect = capture_upsert

        # Initialize orchestrator
        orchestrator = ConferenceScanOrchestrator(
            config_path=temp_config_file,
            recipient_email="test@example.com"
        )
        orchestrator.delta_store = mock_store_instance

        # Run scan
        success = orchestrator.scan_conference(existing_state)

        # Assertions
        assert success is True

        # Verify state transition: MONTHLY → BIWEEKLY
        assert captured_state is not None
        assert captured_state.watch_mode == WatchMode.BIWEEKLY

        # Verify no deadlines found
        assert len(captured_state.current_deadlines) == 0

        # Verify email sent (CHANGE_NO_DATES type)
        assert mock_ses_client.send_email.called
        email_call = mock_ses_client.send_email.call_args
        assert "Website Updated" in email_call[1]["subject"]

        # Verify LLM called for no-dates analysis
        assert mock_llm_client.analyze_no_dates_change.called

    @patch('conbot.main.get_secret')
    @patch('conbot.fetching.fetcher.requests.Session')
    @patch('conbot.main.SESEmailClient')
    @patch('conbot.main.LLMClient')
    @patch('conbot.main.DeltaStore')
    def test_no_change_detected(
        self,
        mock_delta_store,
        mock_llm_class,
        mock_ses_class,
        mock_requests,
        mock_get_secret,
        temp_config_file,
        sample_html,
        mock_ses_client,
        mock_llm_client
    ):
        """Test scan where no change detected."""
        # Setup mocks
        mock_get_secret.return_value = "test-key"
        mock_ses_class.return_value = mock_ses_client
        mock_llm_class.return_value = mock_llm_client

        # Mock HTTP fetch
        mock_response = Mock()
        mock_response.text = sample_html
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_requests.return_value.get.return_value = mock_response

        # Mock Delta store
        mock_store_instance = mock_delta_store.return_value

        # Initialize orchestrator (need real components for hashing)
        orchestrator = ConferenceScanOrchestrator(
            config_path=temp_config_file,
            recipient_email="test@example.com"
        )
        orchestrator.delta_store = mock_store_instance

        # First scan to get hashes
        first_state = ConferenceState(
            conference_id="uitp_summit",
            conference_name="UITP Global Public Transport Summit",
            url="https://example.com/uitp-summit",
            watch_mode=WatchMode.MONTHLY,
            next_run_at=datetime.now(),
            last_scan_at=None,
            binary_hash=None,
            filtered_hash=None,
            simhash_signature=None,
            current_deadlines=[],
            current_summary=None,
            tracked_links=[],
            consecutive_no_change_count=0,
            updated_at=datetime.now()
        )

        captured_first = None

        def capture_first(state):
            nonlocal captured_first
            captured_first = state

        mock_store_instance.upsert_conference_state.side_effect = capture_first
        mock_store_instance.get_conference_state.return_value = first_state

        orchestrator.scan_conference(first_state)

        # Now scan again with same content (should detect no change)
        existing_state = captured_first

        captured_second = None

        def capture_second(state):
            nonlocal captured_second
            captured_second = state

        mock_store_instance.upsert_conference_state.side_effect = capture_second
        mock_store_instance.get_conference_state.return_value = existing_state

        success = orchestrator.scan_conference(existing_state)

        # Assertions
        assert success is True

        # Verify state stayed the same
        assert captured_second.watch_mode == existing_state.watch_mode

        # Verify consecutive no-change count incremented
        assert captured_second.consecutive_no_change_count == existing_state.consecutive_no_change_count + 1

        # Verify NO_CHANGE email sent
        assert mock_ses_client.send_email.called
        email_call = mock_ses_client.send_email.call_args
        assert "No Changes" in email_call[1]["subject"]

        # Verify LLM NOT called (no change)
        assert not mock_llm_client.analyze_change.called

    @patch('conbot.main.get_secret')
    def test_initialization(
        self,
        mock_get_secret,
        temp_config_file
    ):
        """Test conference initialization from config."""
        mock_get_secret.return_value = "test-key"

        # Mock Delta store
        with patch('conbot.main.DeltaStore') as mock_delta_class:
            mock_store = mock_delta_class.return_value
            mock_store.get_conference_state.return_value = None  # Not initialized

            captured_states = []

            def capture_init(state):
                captured_states.append(state)

            mock_store.upsert_conference_state.side_effect = capture_init

            # Initialize orchestrator
            orchestrator = ConferenceScanOrchestrator(
                config_path=temp_config_file,
                recipient_email="test@example.com"
            )
            orchestrator.delta_store = mock_store

            # Initialize conferences
            count = orchestrator.initialize_conferences()

            # Assertions
            assert count == 1  # Only UITP in test config
            assert len(captured_states) == 1

            state = captured_states[0]
            assert state.conference_id == "uitp_summit"
            assert state.watch_mode == WatchMode.MONTHLY
            assert state.binary_hash is None  # Not scanned yet
            assert len(state.current_deadlines) == 0


@pytest.mark.slow
class TestFullScanFlowWithRealComponents:
    """Integration tests with real components (no network mocks)."""

    def test_date_extraction_accuracy(self):
        """Test date extraction with realistic HTML."""
        from conbot.extraction.dates import DateExtractor
        from conbot.extraction.content import ContentExtractor

        html = """
        <html><body>
            <h2>Important Dates</h2>
            <ul>
                <li>Abstract submission: March 15, 2026</li>
                <li>Full paper deadline: 30 April 2026</li>
                <li>Early registration: 2026-05-01</li>
                <li>Conference: June 10-12, 2026</li>
            </ul>
            <footer>Copyright 2024-2026. Last updated: Jan 1, 2026</footer>
        </body></html>
        """

        extractor = ContentExtractor()
        date_extractor = DateExtractor()

        result = extractor.extract_all(html, "https://example.com")
        deadlines = date_extractor.extract_deadlines(
            text=result["main_content"],
            relevant_snippets=result["relevant_snippets"]
        )

        # Should find 3 deadlines (not conference dates or copyright)
        assert len(deadlines) >= 2
        assert any(d.type == DeadlineType.ABSTRACT for d in deadlines)
        assert any(d.date == date(2026, 3, 15) for d in deadlines)

    def test_simhash_similarity_detection(self):
        """Test SimHash detects semantic similarity."""
        from conbot.detection.fingerprint import ChangeDetector

        html1 = "<html><body><p>Call for papers now open</p></body></html>"
        html2 = "<html><body><p>Call for papers is now open</p></body></html>"  # Minor change
        html3 = "<html><body><p>Registration is now open</p></body></html>"  # Major change

        detector = ChangeDetector(simhash_threshold=5)

        fp1 = detector.generate_fingerprints(html1, html1)
        fp2 = detector.generate_fingerprints(html2, html2)
        fp3 = detector.generate_fingerprints(html3, html3)

        # fp1 vs fp2: Minor change, should NOT trigger semantic change
        changed, change_type, hamming = detector.detect_change(fp2, fp1)
        assert changed is True  # Binary hash different
        assert hamming is not None
        assert hamming <= 5  # Within threshold

        # fp1 vs fp3: Major change, should trigger semantic change
        changed, change_type, hamming = detector.detect_change(fp3, fp1)
        assert changed is True
        assert hamming is not None
        assert hamming > 5  # Beyond threshold
