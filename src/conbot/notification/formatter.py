"""
Email formatter for conference scan notifications.

Collects the results of a run into one report email and sends it via SMTP.
"""

from datetime import datetime
from typing import List, Optional
import logging
from ..models.conference import (
    ConferenceState,
    ScanResult,
    WatchMode,
    Deadline
)
from .templates import EmailTemplates
from .email_client import SMTPEmailClient

logger = logging.getLogger(__name__)


class EmailFormatter:
    """
    Format and send the per-run scan report email.

    Example:
        >>> formatter = EmailFormatter(
        ...     email_client=email_client,
        ...     recipient_email="user@example.com"
        ... )
        >>> entry = formatter.report_entry(state, result, "CHANGE_WITH_DATES", WatchMode.MONTHLY)
        >>> formatter.send_report([entry])
    """

    # Section order in the report and subject, most important first:
    # email_type -> (subject icon, subject label)
    REPORT_SECTIONS = {
        "CHANGE_WITH_DATES": ("🚨", "deadlines published"),
        "CHANGE_NO_DATES": ("⚠️", "updated"),
        "ERROR": ("⚠️", "error"),
        "NO_CHANGE": ("✓", "no change"),
    }

    def __init__(
        self,
        email_client: SMTPEmailClient,
        recipient_email: str,
        templates: Optional[EmailTemplates] = None
    ):
        """
        Initialize email formatter.

        Args:
            email_client: Configured SMTP email client
            recipient_email: Default recipient email address
            templates: Email templates (optional, creates new if None)
        """
        self.email_client = email_client
        self.recipient_email = recipient_email
        self.templates = templates or EmailTemplates()

        logger.info(f"EmailFormatter initialized for {recipient_email}")

    def report_entry(
        self,
        conference_state: ConferenceState,
        scan_result: ScanResult,
        email_type: str,
        previous_mode: WatchMode
    ) -> dict:
        """
        Build the report entry for one successful scan.

        Args:
            conference_state: Current conference state (with next_run_at)
            scan_result: Result of latest scan
            email_type: NO_CHANGE, CHANGE_NO_DATES or CHANGE_WITH_DATES
            previous_mode: Previous watch mode (for transition info)

        Returns:
            Dict of template variables plus "email_type"
        """
        entry = self._build_template_vars(
            conference_state=conference_state,
            scan_result=scan_result,
            previous_mode=previous_mode
        )
        entry["email_type"] = email_type
        return entry

    @staticmethod
    def error_entry(
        conference_name: str,
        url: str,
        error_message: str,
        error_count: int
    ) -> dict:
        """Build the report entry for a failed scan."""
        return {
            "email_type": "ERROR",
            "conference_name": conference_name,
            "url": url,
            "error_message": error_message,
            "error_count": error_count,
        }

    def send_report(
        self,
        entries: List[dict],
        to_addresses: Optional[List[str]] = None
    ) -> bool:
        """
        Send one email covering every conference scanned in a run.

        Args:
            entries: Entries from report_entry() / error_entry()
            to_addresses: Override recipient addresses (optional)

        Returns:
            True if email sent successfully, False otherwise (or if no entries)
        """
        if not entries:
            return False

        recipients = to_addresses or [self.recipient_email]

        sections = {t: [e for e in entries if e["email_type"] == t] for t in self.REPORT_SECTIONS}

        try:
            html_body = self.templates.render_report(
                scan_date=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
                total=len(entries),
                with_dates=sections["CHANGE_WITH_DATES"],
                no_dates=sections["CHANGE_NO_DATES"],
                errors=sections["ERROR"],
                no_change=sections["NO_CHANGE"],
            )
            text_body = SMTPEmailClient.strip_html(html_body)

            success = self.email_client.send_email(
                to_addresses=recipients,
                subject=self._report_subject(sections),
                html_body=html_body,
                text_body=text_body
            )
        except Exception as e:
            logger.error(f"Error formatting/sending scan report: {e}", exc_info=True)
            return False

        if success:
            logger.info(f"Sent scan report ({len(entries)} conferences) to {recipients[0]}")
        else:
            logger.error("Failed to send scan report")
        return success

    @classmethod
    def _report_subject(cls, sections: dict) -> str:
        """E.g. '🚨 ConBOT report: 1 deadlines published, 3 no change'."""
        present = [t for t in cls.REPORT_SECTIONS if sections[t]]
        icon = cls.REPORT_SECTIONS[present[0]][0]
        counts = ", ".join(f"{len(sections[t])} {cls.REPORT_SECTIONS[t][1]}" for t in present)
        return f"{icon} ConBOT report: {counts}"

    def _build_template_vars(
        self,
        conference_state: ConferenceState,
        scan_result: ScanResult,
        previous_mode: WatchMode
    ) -> dict:
        """
        Build template variables from conference state and scan result.

        Args:
            conference_state: Current conference state
            scan_result: Latest scan result
            previous_mode: Previous watch mode

        Returns:
            Dict of template variables for Jinja2

        Example:
            >>> vars = formatter._build_template_vars(state, result, WatchMode.MONTHLY)
            >>> print(vars['conference_name'])
        """
        # Format timestamps
        scan_date = scan_result.scan_timestamp.strftime("%Y-%m-%d %H:%M UTC")
        next_run_date = conference_state.next_run_at.strftime("%Y-%m-%d %H:%M UTC")

        # Base variables (all templates)
        vars_dict = {
            "conference_name": conference_state.conference_name,
            "url": str(conference_state.url),
            "scan_date": scan_date,
            "next_run_date": next_run_date,
            "watch_mode": conference_state.watch_mode.value,
            "previous_watch_mode": previous_mode.value,
        }

        # Add deadlines if present
        if scan_result.deadlines_found:
            vars_dict["deadlines"] = [
                {
                    "date": deadline.date.strftime("%B %d, %Y"),  # "March 15, 2026"
                    "type": deadline.type.value,
                    "confidence": deadline.confidence,
                    "source_text": deadline.source_text
                }
                for deadline in scan_result.deadlines_found
            ]
        else:
            vars_dict["deadlines"] = []

        # Add last known deadlines for NO_CHANGE template
        if conference_state.current_deadlines:
            vars_dict["last_known_deadlines"] = [
                {
                    "date": deadline.date.strftime("%B %d, %Y"),
                    "type": deadline.type.value
                }
                for deadline in conference_state.current_deadlines
            ]
        else:
            vars_dict["last_known_deadlines"] = []

        # Add summary if available
        if scan_result.summary:
            # Convert plain text summary to HTML paragraphs
            summary_html = self._format_summary_html(scan_result.summary)
            vars_dict["summary"] = summary_html
        else:
            vars_dict["summary"] = None

        # Add change type for debugging
        if scan_result.change_detected:
            vars_dict["change_type"] = scan_result.change_type.value
        else:
            vars_dict["change_type"] = "none"

        return vars_dict

    @staticmethod
    def _format_summary_html(summary: str) -> str:
        """
        Convert plain text summary to HTML paragraphs.

        Args:
            summary: Plain text summary

        Returns:
            HTML-formatted summary

        Example:
            >>> html = EmailFormatter._format_summary_html("Line 1\\n\\nLine 2")
            >>> print(html)  # "<p>Line 1</p><p>Line 2</p>"
        """
        # Split on double newlines (paragraph breaks)
        paragraphs = summary.split("\n\n")

        # Wrap each paragraph in <p> tags
        html_paragraphs = [f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()]

        return "\n".join(html_paragraphs)

    def send_test_email(
        self,
        to_addresses: Optional[List[str]] = None
    ) -> bool:
        """
        Send test email to verify SMTP configuration.

        Args:
            to_addresses: Override recipient addresses (optional)

        Returns:
            True if email sent successfully, False otherwise

        Example:
            >>> if formatter.send_test_email():
            ...     print("SMTP is configured correctly")
        """
        recipients = to_addresses or [self.recipient_email]

        subject = "ConBOT Test Email"

        html_body = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #28a745; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
        .header h2 { margin: 0; }
        .success-box { background: #d4edda; padding: 15px; border-left: 4px solid #28a745; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>✅ Test Email</h2>
        </div>
        <div class="content">
            <div class="success-box">
                <strong>Success!</strong> Your ConBOT email notification system is working correctly.
            </div>
            <p>This test email confirms that:</p>
            <ul>
                <li>SMTP credentials are valid</li>
                <li>SMTP server accepted the message</li>
                <li>Email delivery is functional</li>
                <li>Templates are rendering correctly</li>
            </ul>
            <p>You're ready to receive conference monitoring alerts.</p>
        </div>
    </div>
</body>
</html>"""

        text_body = """ConBOT Test Email

Success! Your ConBOT email notification system is working correctly.

This test email confirms that:
- SMTP credentials are valid
- SMTP server accepted the message
- Email delivery is functional
- Templates are rendering correctly

You're ready to receive conference monitoring alerts."""

        success = self.email_client.send_email(
            to_addresses=recipients,
            subject=subject,
            html_body=html_body,
            text_body=text_body
        )

        if success:
            logger.info(f"Test email sent successfully to {recipients[0]}")
        else:
            logger.error(f"Test email failed for {recipients[0]}")

        return success
