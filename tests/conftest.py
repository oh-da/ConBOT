"""
Pytest fixtures for ConBOT tests.

Provides reusable test fixtures for mocking external dependencies
and creating sample data.
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock
from conbot.models.conference import (
    ConferenceState,
    WatchMode,
    Deadline,
    DeadlineType,
    ScanResult,
    ChangeType,
)


@pytest.fixture
def sample_html():
    """Sample HTML content for testing."""
    return """
    <html>
    <head><title>UITP Summit 2026</title></head>
    <body>
        <nav>Navigation menu</nav>
        <main>
            <h1>UITP Global Public Transport Summit 2026</h1>
            <p>The premier event for public transport professionals.</p>

            <h2>Call for Papers</h2>
            <p>We are pleased to announce that the call for papers is now open!</p>

            <h3>Important Dates</h3>
            <ul>
                <li>Abstract submission deadline: March 15, 2026</li>
                <li>Full paper deadline: April 30, 2026</li>
                <li>Early bird registration closes: May 15, 2026</li>
            </ul>
        </main>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """


@pytest.fixture
def sample_conference_state():
    """Sample ConferenceState for testing."""
    return ConferenceState(
        conference_id="uitp_summit",
        url="https://www.uitpsummit.org/",
        watch_mode=WatchMode.MONTHLY,
        next_run_at=datetime.now() + timedelta(days=30),
        last_scan_at=None,
        binary_hash=None,
        filtered_hash=None,
        simhash_signature=None,
        current_deadlines=[],
        current_summary=None,
        tracked_links=[],
        consecutive_no_change_count=0,
        consecutive_error_count=0,
        is_active=True,
        updated_at=datetime.now(),
    )


@pytest.fixture
def sample_deadlines():
    """Sample deadlines for testing."""
    return [
        Deadline(
            date=date(2026, 3, 15),
            type=DeadlineType.ABSTRACT,
            confidence=0.9,
            source_text="Abstract submission deadline: March 15, 2026"
        ),
        Deadline(
            date=date(2026, 4, 30),
            type=DeadlineType.PAPER,
            confidence=0.9,
            source_text="Full paper deadline: April 30, 2026"
        ),
        Deadline(
            date=date(2026, 5, 15),
            type=DeadlineType.REGISTRATION,
            confidence=0.8,
            source_text="Early bird registration closes: May 15, 2026"
        ),
    ]


@pytest.fixture
def keyword_groups():
    """Sample keyword groups for testing."""
    return {
        'cfp': [
            'call for papers',
            'call for abstracts',
            'submission',
            'deadline',
            'important dates',
        ],
        'no_dates': [
            'upcoming',
            'tba',
            'to be announced',
            'coming soon',
        ]
    }


@pytest.fixture
def mock_requests_response():
    """Mock requests Response object."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = """
    <html><body>
    <h1>Conference Page</h1>
    <p>Call for papers deadline: June 1, 2026</p>
    </body></html>
    """
    return mock_response


@pytest.fixture
def mock_ses_client():
    """Mock AWS SES client."""
    from moto import mock_ses
    import boto3

    with mock_ses():
        client = boto3.client('ses', region_name='us-east-1')
        # Verify a sender email
        client.verify_email_identity(EmailAddress='test@example.com')
        yield client
