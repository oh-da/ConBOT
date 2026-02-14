"""
AWS SES email client for conference notifications.

Sends emails via AWS Simple Email Service with error handling.
"""

import boto3
from botocore.exceptions import ClientError, BotoCoreError
from typing import List, Optional
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class SESEmailClient:
    """
    AWS SES email client with retry and error handling.

    Sends HTML and plain text emails via AWS SES.
    Handles rate limits, bounces, and unverified sender errors.

    Example:
        >>> client = SESEmailClient(
        ...     sender_email="conbot@example.com",
        ...     aws_region="us-east-1"
        ... )
        >>> client.send_email(
        ...     to_addresses=["user@example.com"],
        ...     subject="Conference Update",
        ...     html_body="<h1>Important Update</h1>",
        ...     text_body="Important Update"
        ... )
    """

    def __init__(
        self,
        sender_email: str,
        aws_region: str = "us-east-1",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 2.0
    ):
        """
        Initialize SES email client.

        Args:
            sender_email: Verified SES sender email address
            aws_region: AWS region for SES (default: us-east-1)
            aws_access_key_id: AWS access key (optional, uses IAM role if None)
            aws_secret_access_key: AWS secret key (optional, uses IAM role if None)
            max_retries: Maximum retry attempts for throttling
            retry_delay: Initial delay between retries (seconds)

        Raises:
            ValueError: If sender_email is empty
        """
        if not sender_email:
            raise ValueError("sender_email cannot be empty")

        self.sender_email = sender_email
        self.aws_region = aws_region
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize boto3 SES client
        session_kwargs = {"region_name": aws_region}
        if aws_access_key_id and aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key

        self.ses_client = boto3.client("ses", **session_kwargs)

        logger.info(
            f"SES client initialized: sender={sender_email}, region={aws_region}"
        )

    def send_email(
        self,
        to_addresses: List[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        cc_addresses: Optional[List[str]] = None,
        bcc_addresses: Optional[List[str]] = None,
        reply_to_addresses: Optional[List[str]] = None
    ) -> bool:
        """
        Send email via AWS SES with retry logic.

        Args:
            to_addresses: List of recipient email addresses
            subject: Email subject line
            html_body: HTML version of email body
            text_body: Plain text version (optional, defaults to stripped HTML)
            cc_addresses: List of CC recipients (optional)
            bcc_addresses: List of BCC recipients (optional)
            reply_to_addresses: List of Reply-To addresses (optional)

        Returns:
            True if email sent successfully, False otherwise

        Example:
            >>> success = client.send_email(
            ...     to_addresses=["recipient@example.com"],
            ...     subject="Test Email",
            ...     html_body="<p>Hello!</p>",
            ...     text_body="Hello!"
            ... )
        """
        if not to_addresses:
            logger.error("Cannot send email: to_addresses is empty")
            return False

        # Build message structure
        message = {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": html_body, "Charset": "UTF-8"}
            }
        }

        # Add text version if provided
        if text_body:
            message["Body"]["Text"] = {"Data": text_body, "Charset": "UTF-8"}

        # Build destination
        destination = {"ToAddresses": to_addresses}
        if cc_addresses:
            destination["CcAddresses"] = cc_addresses
        if bcc_addresses:
            destination["BccAddresses"] = bcc_addresses

        # Retry loop for throttling
        for attempt in range(self.max_retries):
            try:
                response = self.ses_client.send_email(
                    Source=self.sender_email,
                    Destination=destination,
                    Message=message,
                    ReplyToAddresses=reply_to_addresses or []
                )

                message_id = response.get("MessageId", "unknown")
                logger.info(
                    f"Email sent successfully: to={to_addresses[0]}, "
                    f"subject='{subject}', message_id={message_id}"
                )
                return True

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_message = e.response["Error"]["Message"]

                if error_code == "Throttling":
                    # Rate limit - retry with exponential backoff
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (2 ** attempt)
                        logger.warning(
                            f"SES throttling (attempt {attempt + 1}/{self.max_retries}), "
                            f"retrying in {wait_time}s"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(
                            f"SES throttling: max retries exceeded for {to_addresses[0]}"
                        )
                        return False

                elif error_code == "MessageRejected":
                    # Unverified sender/recipient or bounce
                    logger.error(
                        f"SES message rejected: {error_message} "
                        f"(sender={self.sender_email}, to={to_addresses})"
                    )
                    return False

                elif error_code == "MailFromDomainNotVerified":
                    logger.error(
                        f"SES sender not verified: {self.sender_email}. "
                        f"Verify sender in AWS SES console."
                    )
                    return False

                elif error_code == "ConfigurationSetDoesNotExist":
                    logger.error(f"SES configuration set not found: {error_message}")
                    return False

                else:
                    # Unknown SES error
                    logger.error(
                        f"SES client error ({error_code}): {error_message}",
                        exc_info=True
                    )
                    return False

            except BotoCoreError as e:
                # Network or credential errors
                logger.error(
                    f"BotoCore error sending email: {str(e)}",
                    exc_info=True
                )
                return False

            except Exception as e:
                # Unexpected errors
                logger.error(
                    f"Unexpected error sending email: {str(e)}",
                    exc_info=True
                )
                return False

        return False

    def send_batch_emails(
        self,
        emails: List[dict],
        throttle_delay: float = 0.1
    ) -> dict:
        """
        Send multiple emails with throttling.

        Args:
            emails: List of email dicts with keys: to_addresses, subject, html_body, text_body
            throttle_delay: Delay between emails (seconds)

        Returns:
            Dict with 'sent', 'failed', and 'total' counts

        Example:
            >>> results = client.send_batch_emails([
            ...     {
            ...         "to_addresses": ["user1@example.com"],
            ...         "subject": "Alert 1",
            ...         "html_body": "<p>Message 1</p>"
            ...     },
            ...     {
            ...         "to_addresses": ["user2@example.com"],
            ...         "subject": "Alert 2",
            ...         "html_body": "<p>Message 2</p>"
            ...     }
            ... ])
            >>> print(f"Sent {results['sent']}/{results['total']} emails")
        """
        sent = 0
        failed = 0

        for i, email in enumerate(emails):
            success = self.send_email(
                to_addresses=email["to_addresses"],
                subject=email["subject"],
                html_body=email["html_body"],
                text_body=email.get("text_body"),
                cc_addresses=email.get("cc_addresses"),
                bcc_addresses=email.get("bcc_addresses"),
                reply_to_addresses=email.get("reply_to_addresses")
            )

            if success:
                sent += 1
            else:
                failed += 1

            # Throttle to avoid rate limits
            if i < len(emails) - 1:  # Don't sleep after last email
                time.sleep(throttle_delay)

        logger.info(
            f"Batch send complete: {sent} sent, {failed} failed, "
            f"{len(emails)} total"
        )

        return {
            "sent": sent,
            "failed": failed,
            "total": len(emails)
        }

    def verify_sender(self) -> bool:
        """
        Check if sender email is verified in SES.

        Returns:
            True if sender is verified, False otherwise

        Example:
            >>> if not client.verify_sender():
            ...     print("Sender email not verified in SES")
        """
        try:
            response = self.ses_client.get_identity_verification_attributes(
                Identities=[self.sender_email]
            )

            attrs = response.get("VerificationAttributes", {})
            status = attrs.get(self.sender_email, {}).get("VerificationStatus")

            verified = status == "Success"

            if verified:
                logger.info(f"Sender verified: {self.sender_email}")
            else:
                logger.warning(
                    f"Sender NOT verified: {self.sender_email} (status: {status})"
                )

            return verified

        except ClientError as e:
            logger.error(
                f"Error checking sender verification: {e.response['Error']['Message']}",
                exc_info=True
            )
            return False

    def get_send_quota(self) -> dict:
        """
        Get SES send quota (max 24h, max per second, sent in 24h).

        Returns:
            Dict with keys: max_24_hour_send, max_send_rate, sent_last_24_hours

        Example:
            >>> quota = client.get_send_quota()
            >>> print(f"Daily quota: {quota['sent_last_24_hours']}/{quota['max_24_hour_send']}")
        """
        try:
            response = self.ses_client.get_send_quota()

            quota = {
                "max_24_hour_send": response.get("Max24HourSend", 0),
                "max_send_rate": response.get("MaxSendRate", 0),
                "sent_last_24_hours": response.get("SentLast24Hours", 0)
            }

            logger.info(
                f"SES quota: {quota['sent_last_24_hours']}/{quota['max_24_hour_send']} "
                f"(rate: {quota['max_send_rate']}/sec)"
            )

            return quota

        except ClientError as e:
            logger.error(
                f"Error getting send quota: {e.response['Error']['Message']}",
                exc_info=True
            )
            return {
                "max_24_hour_send": 0,
                "max_send_rate": 0,
                "sent_last_24_hours": 0
            }

    @staticmethod
    def strip_html(html: str) -> str:
        """
        Strip HTML tags to create plain text version.

        Simple tag removal for fallback text body.

        Args:
            html: HTML string

        Returns:
            Plain text with tags removed

        Example:
            >>> text = SESEmailClient.strip_html("<p>Hello <b>world</b>!</p>")
            >>> print(text)  # "Hello world!"
        """
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
