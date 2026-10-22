"""
Unit tests for SYSFIX SMTP Protocol Stage Tracking and Diagnostics.
Tests failure handling and connection closure at every individual stage:
1. DNS resolution
2. TCP connection & timeouts
3. SMTP greeting banner validation
4. EHLO before TLS
5. STARTTLS capability & negotiation
6. EHLO after TLS
7. Authentication (535, SMTPServerDisconnected)
8. Message transmission (RCPT TO, DATA, SMTPServerDisconnected)
9. Windows SMTP environment diagnostics
"""

import os
import ssl
import socket
import smtplib
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_test_vault = None

def setUpModule():
    global _test_vault
    _test_vault = os.path.join(tempfile.gettempdir(), f"sysfix_stages_vault_{os.getpid()}_{id(setUpModule)}.dat")
    os.environ["SYSFIX_VAULT_PATH"] = _test_vault

def tearDownModule():
    global _test_vault
    if _test_vault and os.path.exists(_test_vault):
        try:
            os.remove(_test_vault)
        except Exception:
            pass
    os.environ.pop("SYSFIX_VAULT_PATH", None)

from backend.database import init_db, update_email_settings
from backend.core.credential_store import store_smtp_credentials, delete_smtp_credentials
from backend.core.email_service import (
    create_authenticated_smtp_session,
    test_smtp_connection as execute_test_smtp_connection,
    send_email_message,
    diagnose_smtp_environment,
    sanitize_smtp_password
)


class TestSmtpProtocolStages(unittest.TestCase):
    def setUp(self):
        init_db()
        delete_smtp_credentials()
        store_smtp_credentials("karthikeyansa369@gmail.com", "app_password_mock")
        update_email_settings({
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": 1,
            "smtp_use_ssl": 0,
            "smtp_sender": "karthikeyansa369@gmail.com",
            "smtp_username": "karthikeyansa369@gmail.com",
            "recipient_email": "karthikeyansa369@gmail.com"
        })

    def tearDown(self):
        delete_smtp_credentials()

    def test_sanitize_smtp_password_strips_internal_spaces_for_gmail(self):
        # 16-character Google App Password with standard 4-group formatting
        spaced = "abcd efgh ijkl mnop"
        self.assertEqual(sanitize_smtp_password(spaced, "smtp.gmail.com", "karthikeyansa369@gmail.com"), "abcdefghijklmnop")

        # Non-gmail normal password preserves internal spaces
        normal = "my secret password"
        self.assertEqual(sanitize_smtp_password(normal, "mail.company.com", "user@company.com"), "my secret password")

    @patch("socket.getaddrinfo")
    def test_stage_dns_resolution_failure(self, mock_gai):
        mock_gai.side_effect = socket.gaierror(11001, "getaddrinfo failed")
        server, stage, err = create_authenticated_smtp_session(
            host="invalid-smtp-host.example.com",
            port=587,
            use_tls=True,
            use_ssl=False
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "DNS resolution")
        self.assertIn("Could not resolve SMTP server hostname", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_tcp_connection_timeout(self, mock_gai, mock_smtp):
        mock_smtp.side_effect = socket.timeout("timed out")
        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False,
            timeout=5
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "TCP connection")
        self.assertIn("timed out", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_greeting_sock_closed(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.sock = None
        mock_smtp.return_value = mock_server

        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "SMTP greeting")
        self.assertIn("Socket closed by server before greeting", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_ehlo_before_tls_failure(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (500, b"Command not recognized")
        mock_smtp.return_value = mock_server

        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "EHLO/HELO before TLS")
        self.assertIn("Server rejected initial EHLO", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_starttls_not_supported(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (250, b"OK")
        mock_server.has_extn.return_value = False
        mock_smtp.return_value = mock_server

        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "STARTTLS capability check")
        self.assertIn("does not support STARTTLS", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_starttls_ssl_error(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (250, b"OK")
        mock_server.has_extn.return_value = True
        mock_server.starttls.side_effect = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
        mock_smtp.return_value = mock_server

        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "STARTTLS negotiation")
        self.assertIn("SSL/TLS validation failed", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_auth_server_disconnected_gmail_behavior(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (250, b"OK")
        mock_server.has_extn.return_value = True
        mock_server.starttls.return_value = (220, b"Ready for TLS")
        # Gmail drops socket on bad credentials in AUTH PLAIN
        mock_server.login.side_effect = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        mock_smtp.return_value = mock_server

        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False,
            username="karthikeyansa369@gmail.com",
            password="bad_password"
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "SMTP authentication")
        self.assertIn("Authentication failed", err)
        self.assertIn("Google App Password", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_auth_535_rejection(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (250, b"OK")
        mock_server.has_extn.return_value = True
        mock_server.starttls.return_value = (220, b"Ready for TLS")
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"5.7.8 Bad Credentials")
        mock_smtp.return_value = mock_server

        server, stage, err = create_authenticated_smtp_session(
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            use_ssl=False,
            username="karthikeyansa369@gmail.com",
            password="bad_password"
        )
        self.assertIsNone(server)
        self.assertEqual(stage, "SMTP authentication")
        self.assertIn("Authentication failed", err)
        self.assertIn("5.7.8 Bad Credentials", err)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_message_transmission_recipient_refusal(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (250, b"OK")
        mock_server.has_extn.return_value = True
        mock_server.starttls.return_value = (220, b"Ready for TLS")
        mock_server.sendmail.return_value = {"bad_recipient@example.com": (550, b"User not found")}
        mock_smtp.return_value = mock_server

        ok, msg = send_email_message(
            subject="Test Subject",
            body_html="<p>Test Body</p>",
            recipient="bad_recipient@example.com",
            allow_queue=False
        )
        self.assertFalse(ok)
        self.assertIn("[RCPT TO]", msg)

    @patch("smtplib.SMTP")
    @patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587))])
    def test_stage_message_transmission_disconnect(self, mock_gai, mock_smtp):
        mock_server = MagicMock()
        mock_server.ehlo.return_value = (250, b"OK")
        mock_server.has_extn.return_value = True
        mock_server.starttls.return_value = (220, b"Ready for TLS")
        mock_server.sendmail.side_effect = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        mock_smtp.return_value = mock_server

        ok, msg = send_email_message(
            subject="Test Subject",
            body_html="<p>Test Body</p>",
            recipient="karthikeyansa369@gmail.com",
            allow_queue=False
        )
        self.assertFalse(ok)
        self.assertIn("[Message transmission]", msg)
        self.assertIn("transmitting message body", msg)

    def test_environment_diagnostics(self):
        diag = diagnose_smtp_environment(host="smtp.gmail.com", port=587, timeout=10)
        self.assertIn("dns", diag)
        self.assertIn("tcp", diag)
        self.assertIn("clock", diag)
        self.assertIn("tls", diag)
        self.assertTrue(diag["dns"]["ok"])
        self.assertTrue(diag["tcp"]["ok"])
        self.assertTrue(diag["clock"]["ok"])
        self.assertTrue(diag["tls"]["ok"])
        self.assertTrue(diag["healthy"])


if __name__ == "__main__":
    unittest.main()
