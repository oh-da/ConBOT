"""
SMTP email client for conference notifications.

Sends HTML + plain text emails through any SMTP server (Gmail, Outlook,
Fastmail, Mailgun, ...) using only the standard library.
"""

import logging
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import List, Optional

logger = logging.getLogger(__name__)


class SMTPEmailClient:
    """
    SMTP email client with retry and error handling.

    Port 465 uses implicit TLS (SMTP_SSL); any other port connects in
    plain text and upgrades with STARTTLS (587 is the usual choice).

    Example:
        >>> client = SMTPEmailClient(
        ...     host="smtp.gmail.com",
        ...     port=587,
        ...     username="me@gmail.com",
        ...     password="app-password",
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
        host: str,
        username: str,
        password: str,
        sender_email: Optional[str] = None,
        port: int = 587,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        """
        Initialize SMTP email client.

        Args:
            host: SMTP server hostname
            username: SMTP login (usually the full email address)
            password: SMTP password or app password
            sender_email: From address (default: username)
            port: SMTP port (587 = STARTTLS, 465 = implicit TLS)
            timeout: Socket timeout in seconds
            max_retries: Maximum attempts for transient failures
            retry_delay: Initial delay between retries (seconds, doubles each retry)

        Raises:
            ValueError: If host, username or password is empty
        """
        if not host:
            raise ValueError("host cannot be empty")
        if not username or not password:
            raise ValueError("username and password cannot be empty")

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender_email = sender_email or username
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        logger.info(
            f"SMTP client initialized: host={host}:{port}, sender={self.sender_email}"
        )

    @classmethod
    def from_env(cls, sender_email: Optional[str] = None) -> "SMTPEmailClient":
        """
        Build a client from environment variables / ~/.conbot/.env.

        Variables (also accepted with an EMAIL_CREDENTIALS_ prefix):
            SMTP_HOST      server hostname (default: smtp.gmail.com)
            SMTP_PORT      587 = STARTTLS, 465 = implicit TLS (default: 587)
            SMTP_USERNAME  login (required)
            SMTP_PASSWORD  password / app password (required)
            SENDER_EMAIL   From address (default: SMTP_USERNAME)

        Raises:
            SecretsError: If SMTP_USERNAME or SMTP_PASSWORD is missing
        """
        from ..utils.secrets import get_secret

        return cls(
            host=get_secret("email-credentials", "smtp_host", default="smtp.gmail.com"),
            port=int(get_secret("email-credentials", "smtp_port", default="587")),
            username=get_secret("email-credentials", "smtp_username"),
            password=get_secret("email-credentials", "smtp_password"),
            sender_email=sender_email or get_secret(
                "email-credentials", "sender_email", default=""
            ) or None,
        )

    def _connect(self) -> smtplib.SMTP:
        """Open an authenticated SMTP connection."""
        context = ssl.create_default_context()

        if self.port == 465:
            server = smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            )
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()

        server.login(self.username, self.password)
        return server

    def _build_message(
        self,
        to_addresses: List[str],
        subject: str,
        html_body: str,
        text_body: Optional[str],
        cc_addresses: Optional[List[str]],
        reply_to_addresses: Optional[List[str]],
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(to_addresses)
        if cc_addresses:
            msg["Cc"] = ", ".join(cc_addresses)
        if reply_to_addresses:
            msg["Reply-To"] = ", ".join(reply_to_addresses)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()

        msg.set_content(text_body or self.strip_html(html_body))
        msg.add_alternative(html_body, subtype="html")
        return msg

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
        Send an email, retrying on transient errors.

        Args:
            to_addresses: List of recipient email addresses
            subject: Email subject line
            html_body: HTML version of email body
            text_body: Plain text version (optional, defaults to stripped HTML)
            cc_addresses: List of CC recipients (optional)
            bcc_addresses: List of BCC recipients (optional, not shown in headers)
            reply_to_addresses: List of Reply-To addresses (optional)

        Returns:
            True if the server accepted the message, False otherwise
        """
        if not to_addresses:
            logger.error("Cannot send email: to_addresses is empty")
            return False

        msg = self._build_message(
            to_addresses, subject, html_body, text_body,
            cc_addresses, reply_to_addresses
        )
        recipients = list(to_addresses) + list(cc_addresses or []) + list(bcc_addresses or [])

        for attempt in range(self.max_retries):
            try:
                server = self._connect()
                try:
                    refused = server.send_message(msg, to_addrs=recipients)
                finally:
                    try:
                        server.quit()
                    except smtplib.SMTPException:
                        pass

                if refused:
                    logger.error(f"SMTP server refused some recipients: {refused}")
                    return len(refused) < len(recipients)

                logger.info(
                    f"Email sent successfully: to={to_addresses[0]}, subject='{subject}'"
                )
                return True

            except smtplib.SMTPAuthenticationError as e:
                # Retrying a bad password only risks locking the account
                logger.error(
                    f"SMTP authentication failed for {self.username}: {e}. "
                    f"Check SMTP_USERNAME / SMTP_PASSWORD (Gmail needs an app password)."
                )
                return False

            except smtplib.SMTPRecipientsRefused as e:
                logger.error(f"SMTP recipients refused: {e.recipients}")
                return False

            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                    smtplib.SMTPResponseException, OSError) as e:
                # 5xx replies are permanent; everything else here is transient
                code = getattr(e, "smtp_code", None)
                if code is not None and 500 <= code < 600:
                    logger.error(f"SMTP permanent error ({code}): {e}")
                    return False

                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        f"SMTP error (attempt {attempt + 1}/{self.max_retries}): {e}, "
                        f"retrying in {wait_time}s"
                    )
                    time.sleep(wait_time)
                    continue

                logger.error(f"SMTP error: max retries exceeded: {e}")
                return False

            except Exception as e:
                logger.error(f"Unexpected error sending email: {e}", exc_info=True)
                return False

        return False

    def send_batch_emails(
        self,
        emails: List[dict],
        throttle_delay: float = 0.5
    ) -> dict:
        """
        Send multiple emails with throttling.

        Args:
            emails: List of email dicts with keys: to_addresses, subject, html_body, text_body
            throttle_delay: Delay between emails (seconds)

        Returns:
            Dict with 'sent', 'failed', and 'total' counts
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

            if i < len(emails) - 1:
                time.sleep(throttle_delay)

        logger.info(
            f"Batch send complete: {sent} sent, {failed} failed, {len(emails)} total"
        )

        return {"sent": sent, "failed": failed, "total": len(emails)}

    def verify_connection(self) -> bool:
        """
        Check that the server is reachable and the credentials are accepted.

        Returns:
            True if connect + login succeeded, False otherwise
        """
        try:
            server = self._connect()
            server.quit()
            logger.info(f"SMTP connection verified: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"SMTP connection check failed: {e}")
            return False

    @staticmethod
    def strip_html(html: str) -> str:
        """
        Strip HTML tags to create plain text version.

        Simple tag removal for fallback text body.

        Example:
            >>> SMTPEmailClient.strip_html("<p>Hello <b>world</b>!</p>")
            'Hello world!'
        """
        text = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
