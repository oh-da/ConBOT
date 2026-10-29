"""Unit tests for the SMTP email client."""

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from conbot.notification.email_client import SMTPEmailClient


@pytest.fixture
def client():
    return SMTPEmailClient(
        host="smtp.example.org",
        port=587,
        username="bot@example.org",
        password="secret",
        retry_delay=0,
    )


class TestSending:
    @patch("conbot.notification.email_client.smtplib.SMTP")
    def test_starttls_login_and_multipart_message(self, smtp_cls, client):
        server = smtp_cls.return_value
        server.send_message.return_value = {}

        ok = client.send_email(
            to_addresses=["me@example.org"],
            subject="Hello ✓",
            html_body="<p>Hi <b>there</b></p>",
        )

        assert ok is True
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("bot@example.org", "secret")
        server.quit.assert_called_once()

        msg = server.send_message.call_args.args[0]
        assert msg["From"] == "bot@example.org"
        assert msg["To"] == "me@example.org"
        assert msg["Subject"] == "Hello ✓"
        assert msg.get_body(("plain",)).get_content().strip() == "Hi there"
        assert "<b>there</b>" in msg.get_body(("html",)).get_content()

    @patch("conbot.notification.email_client.smtplib.SMTP_SSL")
    def test_port_465_uses_implicit_tls(self, ssl_cls):
        c = SMTPEmailClient("smtp.example.org", "u@example.org", "pw", port=465)
        ssl_cls.return_value.send_message.return_value = {}

        assert c.send_email(["me@example.org"], "s", "<p>x</p>") is True
        ssl_cls.assert_called_once()
        ssl_cls.return_value.starttls.assert_not_called()

    @patch("conbot.notification.email_client.smtplib.SMTP")
    def test_bcc_is_an_envelope_recipient_but_not_a_header(self, smtp_cls, client):
        server = smtp_cls.return_value
        server.send_message.return_value = {}

        client.send_email(["a@example.org"], "s", "<p>x</p>", bcc_addresses=["hidden@example.org"])

        msg = server.send_message.call_args.args[0]
        assert server.send_message.call_args.kwargs["to_addrs"] == ["a@example.org", "hidden@example.org"]
        assert "hidden@example.org" not in str(msg)

    def test_empty_recipients_is_rejected(self, client):
        assert client.send_email([], "s", "<p>x</p>") is False


class TestFailures:
    @patch("conbot.notification.email_client.smtplib.SMTP")
    def test_auth_failure_is_not_retried(self, smtp_cls, client):
        smtp_cls.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")

        assert client.send_email(["me@example.org"], "s", "<p>x</p>") is False
        assert smtp_cls.call_count == 1

    @patch("conbot.notification.email_client.smtplib.SMTP")
    def test_transient_error_is_retried_then_succeeds(self, smtp_cls, client):
        good = MagicMock()
        good.send_message.return_value = {}
        smtp_cls.side_effect = [smtplib.SMTPServerDisconnected("dropped"), good]

        assert client.send_email(["me@example.org"], "s", "<p>x</p>") is True
        assert smtp_cls.call_count == 2

    @patch("conbot.notification.email_client.smtplib.SMTP")
    def test_gives_up_after_max_retries(self, smtp_cls, client):
        smtp_cls.side_effect = ConnectionRefusedError("down")

        assert client.send_email(["me@example.org"], "s", "<p>x</p>") is False
        assert smtp_cls.call_count == client.max_retries

    @patch("conbot.notification.email_client.smtplib.SMTP")
    def test_permanent_5xx_is_not_retried(self, smtp_cls, client):
        server = smtp_cls.return_value
        server.send_message.side_effect = smtplib.SMTPResponseException(554, b"rejected")

        assert client.send_email(["me@example.org"], "s", "<p>x</p>") is False
        assert smtp_cls.call_count == 1


class TestConfig:
    def test_requires_credentials(self):
        with pytest.raises(ValueError):
            SMTPEmailClient("smtp.example.org", "", "")

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.fastmail.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_USERNAME", "bot@example.org")
        monkeypatch.setenv("SMTP_PASSWORD", "pw")
        monkeypatch.setenv("SENDER_EMAIL", "alerts@example.org")

        c = SMTPEmailClient.from_env()

        assert (c.host, c.port, c.username) == ("smtp.fastmail.com", 465, "bot@example.org")
        assert c.sender_email == "alerts@example.org"

    def test_from_env_defaults_sender_to_username(self, monkeypatch):
        monkeypatch.delenv("SENDER_EMAIL", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_PORT", raising=False)
        monkeypatch.setenv("SMTP_USERNAME", "bot@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "pw")

        c = SMTPEmailClient.from_env()

        assert (c.host, c.port, c.sender_email) == ("smtp.gmail.com", 587, "bot@gmail.com")

    def test_from_env_missing_credentials(self, monkeypatch):
        from conbot.utils.secrets import SecretsError

        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("EMAIL_CREDENTIALS_SMTP_USERNAME", raising=False)

        with pytest.raises(SecretsError):
            SMTPEmailClient.from_env()
