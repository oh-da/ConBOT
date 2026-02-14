"""
Main orchestrator for conference tracking bot.

Entry point for scanning conferences and sending notifications.
"""

import sys
import argparse
from datetime import datetime
from typing import List, Optional
import logging
from pathlib import Path

from .models.conference import (
    ConferenceState,
    ScanResult,
    WatchMode,
    ChangeType
)
from .utils.config import load_conference_config
from .utils.logging import setup_logging
from .utils.secrets import get_secret
from .fetching.fetcher import Fetcher
from .extraction.content import ContentExtractor
from .extraction.dates import DateExtractor
from .detection.fingerprint import ChangeDetector
from .llm.client import LLMClient
from .discovery.link_finder import LinkDiscovery
from .state.delta_store import DeltaStore
from .state.transitions import StateTransitionEngine
from .state.audit import AuditLogger
from .scheduling.dispatcher import ScheduleDispatcher
from .scheduling.calculator import ScheduleCalculator
from .notification.email_client import SESEmailClient
from .notification.formatter import EmailFormatter

logger = logging.getLogger(__name__)


class ConferenceScanOrchestrator:
    """
    Main orchestrator for conference scanning workflow.

    Coordinates all components to:
    1. Fetch conference websites
    2. Extract and analyze content
    3. Detect changes
    4. Extract deadlines
    5. Update state machine
    6. Send email notifications

    Example:
        >>> orchestrator = ConferenceScanOrchestrator(
        ...     config_path="config/conferences.yaml",
        ...     recipient_email="user@example.com"
        ... )
        >>> orchestrator.run_daily_scan()
    """

    def __init__(
        self,
        config_path: str,
        recipient_email: str,
        sender_email: Optional[str] = None,
        aws_region: str = "us-east-1",
        llm_api_key: Optional[str] = None,
        delta_table_path: Optional[str] = None,
        simhash_threshold: int = 5
    ):
        """
        Initialize orchestrator with configuration.

        Args:
            config_path: Path to conferences.yaml
            recipient_email: Email address for notifications
            sender_email: SES sender email (optional, uses secrets if None)
            aws_region: AWS region for SES
            llm_api_key: OpenAI API key (optional, uses secrets if None)
            delta_table_path: Path to Delta tables (optional, uses default if None)
            simhash_threshold: Hamming distance threshold for semantic changes
        """
        logger.info("Initializing ConferenceScanOrchestrator")

        # Load conference configurations
        self.conferences_config = load_conference_config(config_path)
        logger.info(f"Loaded {len(self.conferences_config)} conference configurations")

        # Initialize components
        self.fetcher = Fetcher()
        self.content_extractor = ContentExtractor()
        self.date_extractor = DateExtractor()
        self.change_detector = ChangeDetector(simhash_threshold=simhash_threshold)
        self.state_engine = StateTransitionEngine()
        self.schedule_calculator = ScheduleCalculator()

        # Initialize LLM client (optional)
        try:
            api_key = llm_api_key or get_secret("llm-credentials", "openai-api-key")
            self.llm_client = LLMClient(api_key=api_key) if api_key else None
            if self.llm_client:
                logger.info("LLM client initialized")
        except Exception as e:
            logger.warning(f"LLM client not available: {e}")
            self.llm_client = None

        # Initialize Delta store
        self.delta_store = DeltaStore(base_path=delta_table_path)
        logger.info("Delta store initialized")

        # Initialize audit logger
        self.audit_logger = AuditLogger(delta_store=self.delta_store)

        # Initialize scheduler
        self.dispatcher = ScheduleDispatcher(delta_store=self.delta_store)

        # Initialize email client
        try:
            sender = sender_email or get_secret("email-credentials", "sender-email")
            self.ses_client = SESEmailClient(
                sender_email=sender,
                aws_region=aws_region
            )
            self.email_formatter = EmailFormatter(
                ses_client=self.ses_client,
                recipient_email=recipient_email
            )
            logger.info(f"Email client initialized: sender={sender}")
        except Exception as e:
            logger.error(f"Failed to initialize email client: {e}")
            raise

        logger.info("ConferenceScanOrchestrator initialization complete")

    def run_daily_scan(self) -> dict:
        """
        Run daily scheduled scan for all due conferences.

        Queries Delta store for conferences where next_run_at <= now,
        scans each one, updates state, and sends notifications.

        Returns:
            Dict with summary statistics

        Example:
            >>> results = orchestrator.run_daily_scan()
            >>> print(f"Scanned {results['scanned']} conferences")
        """
        logger.info("=" * 80)
        logger.info("Starting daily conference scan")
        logger.info("=" * 80)

        # Get conferences due for scanning
        due_conferences = self.dispatcher.get_conferences_due_for_scan()

        if not due_conferences:
            logger.info("No conferences due for scanning")
            return {
                "scanned": 0,
                "succeeded": 0,
                "failed": 0,
                "changes_detected": 0,
                "deadlines_found": 0,
                "emails_sent": 0
            }

        logger.info(f"Found {len(due_conferences)} conferences due for scanning")

        # Scan each conference
        results = {
            "scanned": 0,
            "succeeded": 0,
            "failed": 0,
            "changes_detected": 0,
            "deadlines_found": 0,
            "emails_sent": 0
        }

        for conference_state in due_conferences:
            try:
                success = self.scan_conference(conference_state)

                results["scanned"] += 1

                if success:
                    results["succeeded"] += 1
                else:
                    results["failed"] += 1

            except Exception as e:
                logger.error(
                    f"Unexpected error scanning {conference_state.conference_id}: {e}",
                    exc_info=True
                )
                results["scanned"] += 1
                results["failed"] += 1

                # Send error notification
                try:
                    self.email_formatter.send_error_notification(
                        conference_id=conference_state.conference_id,
                        conference_name=conference_state.conference_name,
                        error_message=str(e),
                        url=str(conference_state.url)
                    )
                except Exception as email_error:
                    logger.error(f"Failed to send error notification: {email_error}")

        logger.info("=" * 80)
        logger.info(
            f"Daily scan complete: {results['succeeded']} succeeded, "
            f"{results['failed']} failed, {results['scanned']} total"
        )
        logger.info("=" * 80)

        return results

    def scan_conference(self, conference_state: ConferenceState) -> bool:
        """
        Scan a single conference and update state.

        Main workflow:
        1. Fetch content
        2. Extract main content and snippets
        3. Detect changes (three-tier fingerprinting)
        4. Extract dates if changed
        5. Call LLM for summary if changed
        6. Determine new state
        7. Update Delta tables
        8. Send email notification

        Args:
            conference_state: Current state of conference

        Returns:
            True if scan completed successfully, False otherwise
        """
        conference_id = conference_state.conference_id
        logger.info(f"Scanning {conference_id} ({conference_state.watch_mode.value} mode)")

        start_time = datetime.now()

        try:
            # Step 1: Fetch content
            html, fetch_method = self.fetcher.fetch(str(conference_state.url))

            # Step 2: Extract content
            extraction_result = self.content_extractor.extract_all(
                html=html,
                url=str(conference_state.url)
            )

            main_content = extraction_result["main_content"]
            filtered_content = extraction_result["filtered_content"]
            snippets = extraction_result["relevant_snippets"]

            # Step 3: Generate fingerprints
            new_fingerprints = self.change_detector.generate_fingerprints(
                raw_html=html,
                filtered_content=filtered_content
            )

            # Step 4: Detect changes
            if conference_state.binary_hash:
                old_fingerprints = {
                    "binary_hash": conference_state.binary_hash,
                    "filtered_hash": conference_state.filtered_hash,
                    "simhash_signature": conference_state.simhash_signature
                }

                change_detected, change_type_str, hamming_dist = self.change_detector.detect_change(
                    new_fingerprints=new_fingerprints,
                    old_fingerprints=old_fingerprints
                )

                change_type = ChangeType[change_type_str]
            else:
                # First scan - treat as change to get baseline
                change_detected = False
                change_type = ChangeType.NONE
                hamming_dist = None

            logger.info(
                f"{conference_id}: change_detected={change_detected}, "
                f"type={change_type.value}, hamming_dist={hamming_dist}"
            )

            # Step 5: Extract dates if changed (or if no deadlines known)
            deadlines = []
            if change_detected or not conference_state.current_deadlines:
                conf_config = self._get_conference_config(conference_id)
                keywords = conf_config.get("cfp_keywords", [])

                deadlines = self.date_extractor.extract_deadlines(
                    text=main_content,
                    relevant_snippets=snippets,
                    context_keywords=keywords
                )

                logger.info(f"{conference_id}: Extracted {len(deadlines)} deadlines")

            # Step 6: LLM summary (if changed and LLM available)
            summary = None
            llm_called = False

            if change_detected and self.llm_client:
                try:
                    conf_config = self._get_conference_config(conference_id)

                    if deadlines:
                        # Deadlines found - get full analysis
                        cfp_keywords = conf_config.get("cfp_keywords", [])
                        summary_data = self.llm_client.analyze_change(
                            conference_id=conference_id,
                            conference_name=conference_state.conference_name,
                            snippets=snippets,
                            deadlines=deadlines,
                            keywords=cfp_keywords
                        )
                        summary = summary_data.get("summary", "")
                    else:
                        # No deadlines - check if it's CFP-related
                        no_dates_keywords = conf_config.get("no_dates_keywords", [])
                        analysis = self.llm_client.analyze_no_dates_change(
                            conference_id=conference_id,
                            conference_name=conference_state.conference_name,
                            snippets=snippets,
                            keywords=no_dates_keywords
                        )
                        summary = analysis.get("summary", "")

                    llm_called = True
                    logger.info(f"{conference_id}: LLM summary generated")

                except Exception as e:
                    logger.warning(f"{conference_id}: LLM call failed: {e}")

            # Step 7: Create scan result
            scan_duration = (datetime.now() - start_time).total_seconds()

            scan_result = ScanResult(
                conference_id=conference_id,
                url=str(conference_state.url),
                scan_timestamp=datetime.now(),
                main_content=main_content[:5000],  # Truncate for storage
                relevant_snippets=snippets[:50],  # Limit snippets
                change_detected=change_detected,
                change_type=change_type,
                hamming_distance=hamming_dist,
                deadlines_found=deadlines,
                summary=summary,
                fetch_method=fetch_method,
                scan_duration_seconds=scan_duration,
                llm_api_called=llm_called
            )

            # Step 8: Determine new state
            previous_mode = conference_state.watch_mode

            new_mode, transition_reason = self.state_engine.determine_new_mode(
                current_mode=previous_mode,
                scan_result=scan_result
            )

            logger.info(
                f"{conference_id}: State transition: {previous_mode.value} → {new_mode.value} "
                f"(reason: {transition_reason})"
            )

            # Step 9: Calculate next run time
            next_run_at = self.schedule_calculator.calculate_next_run(new_mode)

            # Step 10: Update conference state
            updated_state = ConferenceState(
                conference_id=conference_id,
                conference_name=conference_state.conference_name,
                url=conference_state.url,
                watch_mode=new_mode,
                next_run_at=next_run_at,
                last_scan_at=datetime.now(),
                binary_hash=new_fingerprints["binary_hash"],
                filtered_hash=new_fingerprints["filtered_hash"],
                simhash_signature=new_fingerprints["simhash_signature"],
                current_deadlines=deadlines if deadlines else conference_state.current_deadlines,
                current_summary=summary if summary else conference_state.current_summary,
                tracked_links=conference_state.tracked_links,  # TODO: Update via link discovery
                consecutive_no_change_count=(
                    conference_state.consecutive_no_change_count + 1 if not change_detected else 0
                ),
                updated_at=datetime.now()
            )

            self.delta_store.upsert_conference_state(updated_state)
            logger.info(f"{conference_id}: State updated in Delta table")

            # Step 11: Log to audit trail
            self.audit_logger.log_scan(
                conference_state=updated_state,
                scan_result=scan_result,
                previous_mode=previous_mode,
                transition_reason=transition_reason
            )

            # Step 12: Send email notification
            should_send, email_type = self.state_engine.should_send_email(
                old_mode=previous_mode,
                new_mode=new_mode,
                scan_result=scan_result
            )

            email_sent = False
            if should_send:
                email_sent = self.email_formatter.send_scan_notification(
                    conference_state=updated_state,
                    scan_result=scan_result,
                    email_type=email_type,
                    previous_mode=previous_mode
                )

                if email_sent:
                    logger.info(f"{conference_id}: {email_type} email sent")
                else:
                    logger.error(f"{conference_id}: Email send failed")

            logger.info(
                f"{conference_id}: Scan complete (duration: {scan_duration:.2f}s, "
                f"email_sent: {email_sent})"
            )

            return True

        except Exception as e:
            logger.error(
                f"Error scanning {conference_id}: {e}",
                exc_info=True
            )
            return False

    def scan_single_conference(
        self,
        conference_id: str,
        force: bool = False
    ) -> bool:
        """
        Scan a specific conference by ID (manual mode).

        Args:
            conference_id: Conference identifier
            force: If True, scan even if not due

        Returns:
            True if scan succeeded, False otherwise

        Example:
            >>> orchestrator.scan_single_conference("uitp_summit", force=True)
        """
        logger.info(f"Manual scan requested for {conference_id}")

        # Get current state
        conference_state = self.delta_store.get_conference_state(conference_id)

        if not conference_state:
            logger.error(f"Conference not found: {conference_id}")
            return False

        # Check if due (unless forced)
        if not force:
            if conference_state.next_run_at > datetime.now():
                logger.warning(
                    f"{conference_id} not due until {conference_state.next_run_at}. "
                    f"Use --force to scan anyway."
                )
                return False

        return self.scan_conference(conference_state)

    def initialize_conferences(self) -> int:
        """
        Initialize conference states in Delta table from config.

        Creates initial ConferenceState records for all conferences
        in conferences.yaml if they don't exist.

        Returns:
            Number of conferences initialized

        Example:
            >>> count = orchestrator.initialize_conferences()
            >>> print(f"Initialized {count} conferences")
        """
        logger.info("Initializing conference states from config")

        initialized = 0

        for conf in self.conferences_config:
            conference_id = conf["id"]

            # Check if already exists
            existing = self.delta_store.get_conference_state(conference_id)

            if existing:
                logger.info(f"{conference_id}: Already initialized, skipping")
                continue

            # Create initial state
            initial_state = ConferenceState(
                conference_id=conference_id,
                conference_name=conf["name"],
                url=conf["primary_url"],
                watch_mode=WatchMode.MONTHLY,
                next_run_at=datetime.now(),  # Scan immediately
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

            self.delta_store.upsert_conference_state(initial_state)

            initialized += 1
            logger.info(f"{conference_id}: Initialized in MONTHLY mode")

        logger.info(f"Initialized {initialized} conferences")
        return initialized

    def _get_conference_config(self, conference_id: str) -> dict:
        """
        Get configuration dict for a conference.

        Args:
            conference_id: Conference identifier

        Returns:
            Config dict or empty dict if not found
        """
        for conf in self.conferences_config:
            if conf["id"] == conference_id:
                return conf
        return {}


def main():
    """
    CLI entry point for ConBOT.

    Usage:
        # Daily scan (all due conferences)
        python -m conbot.main

        # Manual scan of specific conference
        python -m conbot.main --manual --conference-id uitp_summit

        # Initialize conferences from config
        python -m conbot.main --initialize

        # Send test email
        python -m conbot.main --test-email
    """
    parser = argparse.ArgumentParser(description="ConBOT - Conference Tracking Bot")

    parser.add_argument(
        "--config",
        default="config/conferences.yaml",
        help="Path to conferences.yaml (default: config/conferences.yaml)"
    )

    parser.add_argument(
        "--recipient-email",
        help="Recipient email for notifications (overrides environment)"
    )

    parser.add_argument(
        "--mode",
        choices=["daily", "manual", "initialize", "test-email"],
        default="daily",
        help="Execution mode (default: daily)"
    )

    parser.add_argument(
        "--conference-id",
        help="Conference ID for manual scan"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force scan even if not due (manual mode)"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )

    parser.add_argument(
        "--simhash-threshold",
        type=int,
        default=5,
        help="SimHash hamming distance threshold (default: 5)"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level)

    # Get recipient email
    recipient_email = args.recipient_email or get_secret("email-credentials", "recipient-email")

    if not recipient_email:
        logger.error("Recipient email not provided (use --recipient-email or set secret)")
        sys.exit(1)

    try:
        # Initialize orchestrator
        orchestrator = ConferenceScanOrchestrator(
            config_path=args.config,
            recipient_email=recipient_email,
            simhash_threshold=args.simhash_threshold
        )

        # Execute based on mode
        if args.mode == "initialize":
            count = orchestrator.initialize_conferences()
            logger.info(f"Initialization complete: {count} conferences")

        elif args.mode == "test-email":
            success = orchestrator.email_formatter.send_test_email()
            if success:
                logger.info("Test email sent successfully")
                sys.exit(0)
            else:
                logger.error("Test email failed")
                sys.exit(1)

        elif args.mode == "manual":
            if not args.conference_id:
                logger.error("--conference-id required for manual mode")
                sys.exit(1)

            success = orchestrator.scan_single_conference(
                conference_id=args.conference_id,
                force=args.force
            )

            if success:
                logger.info(f"Manual scan complete: {args.conference_id}")
                sys.exit(0)
            else:
                logger.error(f"Manual scan failed: {args.conference_id}")
                sys.exit(1)

        elif args.mode == "daily":
            results = orchestrator.run_daily_scan()

            logger.info(f"Daily scan results: {results}")

            # Exit with error if any scans failed
            if results["failed"] > 0:
                sys.exit(1)
            else:
                sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
