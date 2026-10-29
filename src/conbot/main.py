"""
Main orchestrator for conference tracking bot.

Entry point for scanning conferences and sending notifications.
"""

import os
import sys
import argparse
from datetime import datetime
from typing import Dict, List, Optional
import logging

from pydantic import HttpUrl, TypeAdapter

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
from .state.sqlite_store import SQLiteStore
from .state.transitions import StateTransitionEngine
from .state.audit import AuditLogger
from .scheduling.dispatcher import ScheduleDispatcher
from .scheduling.calculator import NextRunCalculator
from .notification.email_client import SMTPEmailClient
from .notification.formatter import EmailFormatter

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "~/.conbot/conbot.db"
_HTTP_URL = TypeAdapter(HttpUrl)  # Normalises URLs the same way ConferenceState does


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

    Only the first URL of each conference in conferences.yaml is fetched;
    ``secondary_urls`` and ``link_discovery`` are not used yet.

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
        llm_api_key: Optional[str] = None,
        db_path: Optional[str] = None,
        simhash_threshold: int = 5,
        email_client: Optional[SMTPEmailClient] = None,
        fetcher: Optional[Fetcher] = None,
    ):
        """
        Initialize orchestrator with configuration.

        Args:
            config_path: Path to conferences.yaml
            recipient_email: Email address for notifications
            sender_email: From address (optional, defaults to SENDER_EMAIL / SMTP_USERNAME)
            llm_api_key: OpenAI API key (optional, uses OPENAI_API_KEY if None)
            db_path: Path to SQLite database (default: $CONBOT_DB_PATH or ~/.conbot/conbot.db)
            simhash_threshold: Hamming distance threshold for semantic changes
            email_client: Pre-built email client (default: built from SMTP_* env vars)
            fetcher: Pre-built fetcher (default: built from conferences.yaml defaults)
        """
        logger.info("Initializing ConferenceScanOrchestrator")

        # Load conference configurations (list of dicts, defaults already merged in)
        self.conferences_config = load_conference_config(config_path)
        logger.info(f"Loaded {len(self.conferences_config)} conference configurations")
        defaults = self.conferences_config[0]

        # Initialize components
        self.fetcher = fetcher or Fetcher(
            throttle_seconds=defaults.get("throttle_seconds", 1.5),
            timeout_seconds=defaults.get("request_timeout_seconds", 25),
            max_retries=defaults.get("max_retries", 3),
            backoff_factor=defaults.get("backoff_seconds", 2),
        )
        self.date_extractor = DateExtractor()
        self.change_detector = ChangeDetector(simhash_threshold=simhash_threshold)
        self.state_engine = StateTransitionEngine()
        self.schedule_calculator = NextRunCalculator()

        # Initialize LLM client (optional)
        self.llm_client = None
        try:
            api_key = llm_api_key or get_secret("llm-credentials", "openai-api-key", default="")
            if api_key:
                self.llm_client = LLMClient(api_key=api_key)
                logger.info("LLM client initialized")
        except Exception as e:
            logger.warning(f"LLM client not available: {e}")

        # Initialize SQLite store
        db_file = db_path or os.getenv("CONBOT_DB_PATH") or DEFAULT_DB_PATH
        db_file = os.path.expanduser(db_file)
        os.makedirs(os.path.dirname(os.path.abspath(db_file)), exist_ok=True)
        self.store = SQLiteStore(db_path=db_file)
        logger.info(f"SQLite store initialized: {db_file}")

        # Initialize audit logger and scheduler
        self.audit_logger = AuditLogger(self.store)
        self.dispatcher = ScheduleDispatcher(delta_store=self.store)

        # Initialize email client
        try:
            self.email_client = email_client or SMTPEmailClient.from_env(sender_email)
            self.email_formatter = EmailFormatter(
                email_client=self.email_client,
                recipient_email=recipient_email
            )
        except Exception as e:
            logger.error(f"Failed to initialize email client: {e}")
            raise

        # Make sure every conference in the YAML has a state row
        self.initialize_conferences()

        logger.info("ConferenceScanOrchestrator initialization complete")

    def run_daily_scan(self, force: bool = False) -> dict:
        """
        Run scheduled scan for all conferences that are due.

        Queries the store for conferences where next_run_at <= now,
        scans each one, updates state, and sends notifications.

        Args:
            force: If True, scan every active conference regardless of next_run_at

        Returns:
            Dict with summary statistics

        Example:
            >>> results = orchestrator.run_daily_scan()
            >>> print(f"Scanned {results['scanned']} conferences")
        """
        logger.info("=" * 80)
        logger.info("Starting daily conference scan")
        logger.info("=" * 80)

        results = {"scanned": 0, "succeeded": 0, "failed": 0}

        if force:
            due_conferences = [c for c in self.store.get_all_conferences() if c.is_active]
        else:
            due_conferences = self.dispatcher.get_conferences_to_scan()

        if not due_conferences:
            logger.info("No conferences due for scanning")
            return results

        logger.info(f"Found {len(due_conferences)} conferences due for scanning")

        try:
            for conference_state in due_conferences:
                results["scanned"] += 1
                if self.scan_conference(conference_state):
                    results["succeeded"] += 1
                else:
                    results["failed"] += 1
        finally:
            self.fetcher.close()

        logger.info(
            f"Daily scan complete: {results['succeeded']} succeeded, "
            f"{results['failed']} failed, {results['scanned']} total"
        )
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
        7. Update store and audit trail
        8. Send email notification

        The first scan of a conference is a baseline: it only counts as a
        change if it already finds deadlines.

        Args:
            conference_state: Current state of conference

        Returns:
            True if scan completed successfully, False otherwise
        """
        conference_id = conference_state.conference_id
        conf_config = self._get_conference_config(conference_id)
        conference_state = conference_state.model_copy(
            update={"conference_name": conf_config.get("name", conference_id)}
        )
        logger.info(f"Scanning {conference_id} ({conference_state.watch_mode.value} mode)")

        start_time = datetime.now()

        try:
            # Step 1: Fetch content
            force_playwright = (
                bool(conf_config.get("js_required"))
                or conf_config.get("fetch_mode") == "playwright"
            )
            html, fetch_method = self.fetcher.fetch(
                str(conference_state.url), force_playwright=force_playwright
            )

            # Step 2: Extract content
            extractor = ContentExtractor(keyword_groups=conf_config.get("keyword_groups", {}))
            main_content, snippets = extractor.extract(html)
            filtered_content = extractor.get_filtered_content(html)

            # Step 3: Generate fingerprints
            new_fingerprints = self.change_detector.compute_fingerprints(
                raw_html=html,
                filtered_content=filtered_content
            )

            # Step 4: Detect changes
            is_baseline = conference_state.binary_hash is None
            hamming_dist = None
            if is_baseline:
                change_detected = False
                change_type = ChangeType.NONE
            else:
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

            logger.info(
                f"{conference_id}: baseline={is_baseline}, change_detected={change_detected}, "
                f"type={change_type.value}, hamming_dist={hamming_dist}"
            )

            # Step 5: Extract dates (on change, and on the baseline scan)
            deadlines = []
            if change_detected or is_baseline:
                deadlines = self.date_extractor.extract_deadlines(
                    main_text=main_content,
                    snippets=snippets
                )
                logger.info(f"{conference_id}: Extracted {len(deadlines)} deadlines")

                # A baseline that already shows deadlines is worth reporting
                if is_baseline and deadlines:
                    change_detected = True
                    change_type = ChangeType.BINARY

            # Step 6: LLM summary (if changed and LLM available)
            summary = None
            llm_called = False

            if change_detected and self.llm_client:
                try:
                    summary, _meta = self.llm_client.analyze_change(
                        conference_id=conference_id,
                        conference_name=conference_state.conference_name,
                        snippets=snippets,
                        deadlines=deadlines,
                        keywords=conf_config.get("cfp_keywords", [])
                    )
                    llm_called = True
                    logger.info(f"{conference_id}: LLM summary generated")
                except Exception as e:
                    logger.warning(f"{conference_id}: LLM call failed: {e}")

            # Step 7: Create scan result
            scan_duration = (datetime.now() - start_time).total_seconds()

            scan_result = ScanResult(
                conference_id=conference_id,
                url=str(conference_state.url),
                scan_timestamp=start_time,
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

            # Step 8: Determine new state and next run
            previous_mode = conference_state.watch_mode

            new_mode, transition_reason = self.state_engine.determine_new_mode(
                current_mode=previous_mode,
                scan_result=scan_result
            )

            logger.info(
                f"{conference_id}: State transition: {previous_mode.value} -> {new_mode.value} "
                f"(reason: {transition_reason})"
            )

            now = datetime.now()
            # Midnight, so the conference is due at the start of that day's run
            next_run_at = self.schedule_calculator.calculate_next_run(
                new_mode, base_time=now, hour=0, minute=0
            )

            # Step 9: Update conference state
            updated_state = conference_state.model_copy(update={
                "watch_mode": new_mode,
                "next_run_at": next_run_at,
                "last_scan_at": now,
                "binary_hash": new_fingerprints["binary_hash"],
                "filtered_hash": new_fingerprints["filtered_hash"],
                "simhash_signature": new_fingerprints["simhash_signature"],
                "current_deadlines": deadlines if deadlines else conference_state.current_deadlines,
                "current_summary": summary if summary else conference_state.current_summary,
                "consecutive_no_change_count": (
                    0 if change_detected or is_baseline
                    else conference_state.consecutive_no_change_count + 1
                ),
                "consecutive_error_count": 0,
                "updated_at": now,
            })

            self.store.upsert_conference(updated_state)
            self.store.update_conference(conference_id, str(updated_state.url), {"last_error": None})
            logger.info(f"{conference_id}: State updated")

            # Step 10: Send email notification
            should_send, email_type = self.state_engine.should_send_email(
                current_mode=previous_mode,
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

            # Step 11: Log to audit trail
            self.audit_logger.log_scan(
                conference_state=updated_state,
                scan_result=scan_result,
                previous_watch_mode=previous_mode,
                new_watch_mode=new_mode,
                transition_reason=transition_reason,
                email_sent=email_sent,
                email_type=email_type if should_send else None
            )

            logger.info(
                f"{conference_id}: Scan complete (duration: {scan_duration:.2f}s, "
                f"email_sent: {email_sent})"
            )

            return True

        except Exception as e:
            logger.error(f"Error scanning {conference_id}: {e}", exc_info=True)
            self._record_failure(conference_state, e, start_time)
            return False

    def _record_failure(
        self,
        conference_state: ConferenceState,
        error: Exception,
        started_at: datetime
    ) -> None:
        """
        Record a failed scan: bump the error counter, audit it, and email.

        next_run_at is left alone, so the conference is retried on the next run.
        To avoid a daily email for a site that stays down, only the first
        failure and every 7th consecutive failure are emailed.
        """
        conference_id = conference_state.conference_id
        error_count = conference_state.consecutive_error_count + 1

        try:
            self.store.update_conference(
                conference_id,
                str(conference_state.url),
                {"consecutive_error_count": error_count, "last_error": str(error)[:1000]}
            )
            self.audit_logger.log_error(
                conference_id=conference_id,
                url=str(conference_state.url),
                error_message=str(error),
                previous_watch_mode=conference_state.watch_mode,
                started_at=started_at
            )
        except Exception as store_error:
            logger.error(f"{conference_id}: Failed to record scan failure: {store_error}")

        if error_count == 1 or error_count % 7 == 0:
            try:
                self.email_formatter.send_error_notification(
                    conference_id=conference_id,
                    conference_name=conference_state.conference_name or conference_id,
                    error_message=str(error),
                    url=str(conference_state.url)
                )
            except Exception as email_error:
                logger.error(f"Failed to send error notification: {email_error}")

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

        conference_state = self.store.get_conference_state(conference_id)

        if not conference_state:
            logger.error(f"Conference not found: {conference_id}")
            return False

        if not force and conference_state.next_run_at > datetime.now():
            logger.warning(
                f"{conference_id} not due until {conference_state.next_run_at}. "
                f"Use --force to scan anyway."
            )
            return False

        try:
            return self.scan_conference(conference_state)
        finally:
            self.fetcher.close()

    def initialize_conferences(self) -> int:
        """
        Create state rows for conferences in conferences.yaml that have none,
        and deactivate rows for conferences no longer in the YAML.

        If the primary URL of an existing conference changed in the YAML, the
        stored URL is updated and fingerprints are cleared so the next scan
        takes a fresh baseline.

        Returns:
            Number of conferences newly initialized
        """
        initialized = 0

        for conf in self.conferences_config:
            conference_id = conf["id"]
            url = conf["primary_url"]

            existing = self.store.get_conference_state(conference_id)

            if existing:
                if str(existing.url) != str(_HTTP_URL.validate_python(url)):
                    logger.info(f"{conference_id}: URL changed in config, resetting baseline")
                    self.store.update_conference(conference_id, url, {
                        "url": url,
                        "binary_hash": None,
                        "filtered_hash": None,
                        "simhash_signature": None,
                    })
                continue

            self.store.upsert_conference(ConferenceState(
                conference_id=conference_id,
                url=url,
                watch_mode=WatchMode.MONTHLY,
                next_run_at=datetime.now(),  # Scan immediately
            ))

            initialized += 1
            logger.info(f"{conference_id}: Initialized in MONTHLY mode")

        # Conferences removed from the YAML stop being scanned (and resume if re-added)
        configured_ids = {conf["id"] for conf in self.conferences_config}
        for state in self.store.get_all_conferences():
            should_be_active = state.conference_id in configured_ids
            if state.is_active != should_be_active:
                logger.info(
                    f"{state.conference_id}: "
                    f"{'re-activated' if should_be_active else 'deactivated (not in config)'}"
                )
                self.store.update_conference(
                    state.conference_id, str(state.url), {"is_active": should_be_active}
                )

        if initialized:
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
        "--db-path",
        default=None,
        help="Path to SQLite database (default: $CONBOT_DB_PATH or ~/.conbot/conbot.db)"
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
        help="Force scan even if not due"
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
    recipient_email = args.recipient_email or get_secret(
        "email-credentials", "recipient-email", default=""
    )

    if not recipient_email:
        logger.error("Recipient email not provided (use --recipient-email or set secret)")
        sys.exit(1)

    try:
        # Initialize orchestrator
        orchestrator = ConferenceScanOrchestrator(
            config_path=args.config,
            recipient_email=recipient_email,
            db_path=args.db_path,
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
            results = orchestrator.run_daily_scan(force=args.force)

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
