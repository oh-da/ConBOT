"""
Email formatter for conference scan notifications.

Formats ScanResult data into emails using templates and sends via SES.
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
from .email_client import SESEmailClient

logger = logging.getLogger(__name__)


class EmailFormatter:
    """
    Format and send conference scan notification emails.

    Combines ScanResult data with email templates and sends via SES.

    Example:
        >>> formatter = EmailFormatter(
        ...     ses_client=ses_client,
        ...     recipient_email="user@example.com"
        ... )
        >>> formatter.send_scan_notification(
        ...     conference_state=state,
        ...     scan_result=result,
        ...     email_type="CHANGE_WITH_DATES",
        ...     previous_mode=WatchMode.MONTHLY
        ... )
    """

    def __init__(
        self,
        ses_client: SESEmailClient,
        recipient_email: str,
        templates: Optional[EmailTemplates] = None
    ):
        """
        Initialize email formatter.

        Args:
            ses_client: Configured SES email client
            recipient_email: Default recipient email address
            templates: Email templates (optional, creates new if None)
        """
        self.ses_client = ses_client
        self.recipient_email = recipient_email
        self.templates = templates or EmailTemplates()

        logger.info(f"EmailFormatter initialized for {recipient_email}")

    def send_scan_notification(
        self,
        conference_state: ConferenceState,
        scan_result: ScanResult,
        email_type: str,
        previous_mode: WatchMode,
        to_addresses: Optional[List[str]] = None
    ) -> bool:
        """
        Format and send scan notification email.

        Args:
            conference_state: Current conference state (with next_run_at)
            scan_result: Result of latest scan
            email_type: Email type (NO_CHANGE, CHANGE_NO_DATES, CHANGE_WITH_DATES)
            previous_mode: Previous watch mode (for transition info)
            to_addresses: Override recipient addresses (optional)

        Returns:
            True if email sent successfully, False otherwise

        Example:
            >>> success = formatter.send_scan_notification(
            ...     conference_state=state,
            ...     scan_result=result,
            ...     email_type="CHANGE_WITH_DATES",
            ...     previous_mode=WatchMode.MONTHLY
            ... )
        """
        recipients = to_addresses or [self.recipient_email]

        try:
            # Format template variables
            template_vars = self._build_template_vars(
                conference_state=conference_state,
                scan_result=scan_result,
                previous_mode=previous_mode
            )

            # Render appropriate template
            if email_type == "NO_CHANGE":
                html_body = self.templates.render_no_change(**template_vars)
                subject = f"✓ {conference_state.conference_name} - No Changes"

            elif email_type == "CHANGE_NO_DATES":
                html_body = self.templates.render_change_no_dates(**template_vars)
                subject = f"⚠️ {conference_state.conference_name} - Website Updated"

            elif email_type == "CHANGE_WITH_DATES":
                html_body = self.templates.render_change_with_dates(**template_vars)
                subject = f"🚨 {conference_state.conference_name} - DEADLINES PUBLISHED"

            else:
                logger.error(f"Unknown email type: {email_type}")
                return False

            # Generate plain text fallback
            text_body = SESEmailClient.strip_html(html_body)

            # Send email
            success = self.ses_client.send_email(
                to_addresses=recipients,
                subject=subject,
                html_body=html_body,
                text_body=text_body
            )

            if success:
                logger.info(
                    f"Sent {email_type} email for {conference_state.conference_id} "
                    f"to {recipients[0]}"
                )
            else:
                logger.error(
                    f"Failed to send {email_type} email for {conference_state.conference_id}"
                )

            return success

        except Exception as e:
            logger.error(
                f"Error formatting/sending email for {conference_state.conference_id}: {e}",
                exc_info=True
            )
            return False

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

    def send_error_notification(
        self,
        conference_id: str,
        conference_name: str,
        error_message: str,
        url: str,
        to_addresses: Optional[List[str]] = None
    ) -> bool:
        """
        Send error notification when scan fails.

        Args:
            conference_id: Conference identifier
            conference_name: Human-readable name
            error_message: Error details
            url: Conference URL that failed
            to_addresses: Override recipient addresses (optional)

        Returns:
            True if email sent successfully, False otherwise

        Example:
            >>> formatter.send_error_notification(
            ...     conference_id="uitp_summit",
            ...     conference_name="UITP Summit",
            ...     error_message="HTTP 503 Service Unavailable",
            ...     url="https://example.com"
            ... )
        """
        recipients = to_addresses or [self.recipient_email]

        subject = f"⚠️ ConBOT Error - {conference_name}"

        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #dc3545; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .header h2 {{ margin: 0; }}
        .error-box {{ background: #f8d7da; padding: 15px; border-left: 4px solid #dc3545; margin: 15px 0; }}
        .footer {{ color: #999; font-size: 12px; padding: 20px; text-align: center; border-top: 1px solid #eee; margin-top: 20px; }}
        code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>❌ Scan Error</h2>
        </div>
        <div class="content">
            <p>An error occurred while scanning the following conference:</p>

            <p>
                <strong>Conference:</strong> {conference_name}<br>
                <strong>ID:</strong> <code>{conference_id}</code><br>
                <strong>URL:</strong> <a href="{url}">{url}</a><br>
                <strong>Time:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}
            </p>

            <div class="error-box">
                <strong>Error Details:</strong><br>
                <code>{error_message}</code>
            </div>

            <p><strong>Next Action:</strong> The system will retry on the next scheduled run.</p>

            <p>If this error persists, check:</p>
            <ul>
                <li>Conference website is accessible</li>
                <li>URL is correct in configuration</li>
                <li>Databricks cluster has network access</li>
                <li>AWS credentials are valid</li>
            </ul>
        </div>
        <div class="footer">
            ConBOT - Automated Conference Monitoring
        </div>
    </div>
</body>
</html>"""

        text_body = f"""
ConBOT Scan Error

Conference: {conference_name}
ID: {conference_id}
URL: {url}
Time: {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}

Error Details:
{error_message}

Next Action: The system will retry on the next scheduled run.

If this error persists, check:
- Conference website is accessible
- URL is correct in configuration
- Databricks cluster has network access
- AWS credentials are valid
"""

        success = self.ses_client.send_email(
            to_addresses=recipients,
            subject=subject,
            html_body=html_body,
            text_body=text_body
        )

        if success:
            logger.info(f"Sent error notification for {conference_id}")
        else:
            logger.error(f"Failed to send error notification for {conference_id}")

        return success

    def send_test_email(
        self,
        to_addresses: Optional[List[str]] = None
    ) -> bool:
        """
        Send test email to verify SES configuration.

        Args:
            to_addresses: Override recipient addresses (optional)

        Returns:
            True if email sent successfully, False otherwise

        Example:
            >>> if formatter.send_test_email():
            ...     print("SES is configured correctly")
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
                <li>AWS SES credentials are valid</li>
                <li>Sender email is verified</li>
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
- AWS SES credentials are valid
- Sender email is verified
- Email delivery is functional
- Templates are rendering correctly

You're ready to receive conference monitoring alerts."""

        success = self.ses_client.send_email(
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
