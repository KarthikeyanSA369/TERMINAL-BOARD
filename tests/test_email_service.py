"""
Unit & Integration Tests for SYSFIX Secure SMTP & Email Service
Tests Windows DPAPI credential store, cryptic terminology sanitization,
offline email queue persistence, and SMTP dispatch logic.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

from backend.database import init_db, get_email_settings, update_email_settings, get_recent_email_deliveries
from backend.core.credential_store import (
    store_smtp_credentials, retrieve_smtp_credentials,
    delete_smtp_credentials, has_smtp_credentials, mask_password
)
from backend.core.cryptic import to_cryptic, sanitize_report_text, apply_cryptic_to_dict
from backend.core.email_service import (
    send_email_message, test_smtp_connection as execute_smtp_connection_test,
    DEFAULT_RECIPIENT, process_offline_email_queue
)


import tempfile

_test_vault = None

def setUpModule():
    global _test_vault
    _test_vault = os.path.join(tempfile.gettempdir(), f"sysfix_test_vault_{os.getpid()}_{id(setUpModule)}.dat")
    os.environ["SYSFIX_VAULT_PATH"] = _test_vault

def tearDownModule():
    global _test_vault
    if _test_vault and os.path.exists(_test_vault):
        try:
            os.remove(_test_vault)
        except Exception:
            pass
    os.environ.pop("SYSFIX_VAULT_PATH", None)


class TestCredentialStore(unittest.TestCase):
    def setUp(self):
        delete_smtp_credentials()

    def tearDown(self):
        delete_smtp_credentials()

    def test_dpapi_store_and_retrieve(self):
        ok = store_smtp_credentials("test_user@example.com", "SecretP@ssw0rd123!")
        self.assertTrue(ok)
        self.assertTrue(has_smtp_credentials())

        creds = retrieve_smtp_credentials()
        self.assertEqual(creds.get("username"), "test_user@example.com")
        self.assertEqual(creds.get("password"), "SecretP@ssw0rd123!")

        # Test deletion
        self.assertTrue(delete_smtp_credentials())
        empty = retrieve_smtp_credentials()
        self.assertEqual(empty.get("password"), "")

    def test_password_masking(self):
        self.assertEqual(mask_password(""), "")
        self.assertEqual(mask_password("123"), "••••••••")
        self.assertEqual(mask_password("SecretLongPassword"), "••••••••")


class TestCrypticTerminology(unittest.TestCase):
    def test_to_cryptic_string(self):
        self.assertEqual(to_cryptic("Unknown"), "Cryptic")
        self.assertEqual(to_cryptic("UNKNOWN"), "Cryptic")
        self.assertEqual(to_cryptic("unknown"), "Cryptic")
        self.assertEqual(to_cryptic("Unknown Device"), "Cryptic Device")
        self.assertEqual(to_cryptic("Healthy"), "Healthy")
        self.assertEqual(to_cryptic(None), "Cryptic")
        self.assertEqual(to_cryptic(""), "Cryptic")

    def test_sanitize_report_text(self):
        text = "Hardware state: Unknown. Status: UNKNOWN. System is healthy."
        sanitized = sanitize_report_text(text)
        self.assertNotIn("Unknown", sanitized)
        self.assertNotIn("UNKNOWN", sanitized)
        self.assertIn("Cryptic", sanitized)

    def test_apply_cryptic_to_dict(self):
        data = {
            "name": "Test Device",
            "status": "Unknown",
            "nested": {"provider": "UNKNOWN"}
        }
        res = apply_cryptic_to_dict(data)
        self.assertEqual(res["status"], "Cryptic")
        self.assertEqual(res["nested"]["provider"], "Cryptic")


class TestEmailService(unittest.TestCase):
    def setUp(self):
        init_db()
        update_email_settings({
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": 1,
            "smtp_sender": "sysfix-alerts@gmail.com",
            "smtp_username": "test_user@gmail.com",
            "recipient_email": DEFAULT_RECIPIENT
        })

    def test_default_recipient(self):
        settings = get_email_settings()
        self.assertEqual(settings.get("recipient_email"), "karthikeyansa369@gmail.com")

    def test_missing_credentials_failure(self):
        delete_smtp_credentials()
        success, msg = send_email_message(
            subject="Test Alert",
            body_html="<p>Test Content</p>",
            allow_queue=False
        )
        self.assertFalse(success)
        self.assertIn("credentials", msg.lower())

    @patch("smtplib.SMTP")
    def test_smtp_send_success(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        store_smtp_credentials("test_user@gmail.com", "app_password_mock")

        success, msg = send_email_message(
            subject="SYSFIX Test Diagnostic Alert",
            body_html="<p>Test email body</p>",
            recipient="karthikeyansa369@gmail.com",
            alert_type="TEST_EMAIL",
            allow_queue=False
        )

        self.assertTrue(success)
        self.assertIn("successfully", msg.lower())
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_with("test_user@gmail.com", "app_password_mock")
        mock_server.sendmail.assert_called_once()

        # Check delivery history record
        deliveries = get_recent_email_deliveries(limit=5)
        self.assertTrue(len(deliveries) > 0)
        self.assertEqual(deliveries[0]["status"], "SENT")
        self.assertEqual(deliveries[0]["recipient"], "karthikeyansa369@gmail.com")

    @patch("smtplib.SMTP")
    def test_smtp_connection_override_settings(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_server.has_extn.return_value = True
        mock_smtp_cls.return_value = mock_server

        # Test calling with override_settings keyword argument (reproduces and tests the fixed bug)
        ok, msg = execute_smtp_connection_test(override_settings={
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "smtp_username": "karthikeyansa369@gmail.com",
            "smtp_password": "custom_app_password"
        })
        self.assertTrue(ok)
        self.assertIn("Successfully connected", msg)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_with("karthikeyansa369@gmail.com", "custom_app_password")

    @patch("smtplib.SMTP")
    def test_smtp_connection_no_args_uses_defaults(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_server.has_extn.return_value = True
        mock_smtp_cls.return_value = mock_server

        store_smtp_credentials("karthikeyansa369@gmail.com", "saved_vault_pwd")
        update_email_settings({
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": 1,
            "smtp_username": "karthikeyansa369@gmail.com"
        })

        ok, msg = execute_smtp_connection_test()
        self.assertTrue(ok)
        self.assertIn("Successfully connected", msg)
        mock_server.login.assert_called_with("karthikeyansa369@gmail.com", "saved_vault_pwd")

    @patch("smtplib.SMTP")
    def test_smtp_connection_auth_failure(self, mock_smtp_cls):
        import smtplib
        mock_server = MagicMock()
        mock_server.has_extn.return_value = True
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Invalid credentials")
        mock_smtp_cls.return_value = mock_server

        ok, msg = execute_smtp_connection_test(override_settings={
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_username": "bad_user@gmail.com",
            "smtp_password": "bad_password"
        })
        self.assertFalse(ok)
        self.assertIn("Authentication failed", msg)

    @patch("smtplib.SMTP")
    def test_send_test_email(self, mock_smtp_cls):
        from backend.core.email_service import send_test_email
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        store_smtp_credentials("karthikeyansa369@gmail.com", "test_app_pwd")
        ok, msg = send_test_email("karthikeyansa369@gmail.com")
        self.assertTrue(ok)
        self.assertIn("successfully", msg.lower())

    @patch("smtplib.SMTP")
    def test_offline_queue_drain_success(self, mock_smtp_cls):
        from backend.database import enqueue_email, get_pending_email_queue
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server
        store_smtp_credentials("karthikeyansa369@gmail.com", "app_pwd")

        # Enqueue an item
        q_id = enqueue_email("TEST_ALERT", "karthikeyansa369@gmail.com", "Queued Test", "<p>Body</p>")
        pending_before = get_pending_email_queue()
        self.assertTrue(any(item["id"] == q_id for item in pending_before))

        # Drain queue
        count = process_offline_email_queue()
        self.assertTrue(count >= 1)

        # Queue should now have fewer pending items
        pending_after = get_pending_email_queue()
        self.assertFalse(any(item["id"] == q_id for item in pending_after))


class TestApiEmailEndpoints(unittest.TestCase):
    def setUp(self):
        init_db()
        from backend.api import SYSFIXApi
        self.api = SYSFIXApi()

    @patch("smtplib.SMTP")
    def test_api_test_smtp_connection(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_server.has_extn.return_value = True
        mock_smtp_cls.return_value = mock_server

        store_smtp_credentials("karthikeyansa369@gmail.com", "my_pwd")
        res = self.api.test_smtp_connection({
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_username": "karthikeyansa369@gmail.com"
        })
        self.assertTrue(res["success"])

    def test_api_save_and_reload_email_settings(self):
        res = self.api.update_email_settings({
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": 1,
            "smtp_use_ssl": 0,
            "smtp_sender": "karthikeyansa369@gmail.com",
            "smtp_username": "karthikeyansa369@gmail.com",
            "recipient_email": "karthikeyansa369@gmail.com",
            "smtp_password": "secure_app_pwd_123"
        })
        self.assertTrue(res["success"])

        loaded = self.api.get_email_settings()
        self.assertEqual(loaded["smtp_host"], "smtp.gmail.com")
        self.assertEqual(loaded["smtp_port"], 587)
        self.assertEqual(loaded["smtp_sender"], "karthikeyansa369@gmail.com")
        self.assertEqual(loaded["smtp_username"], "karthikeyansa369@gmail.com")
        self.assertEqual(loaded["recipient_email"], "karthikeyansa369@gmail.com")
        self.assertTrue(loaded["has_password"])
        self.assertEqual(loaded["smtp_password_masked"], "••••••••")

    @patch("smtplib.SMTP")
    def test_api_send_daily_report_now(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server
        store_smtp_credentials("karthikeyansa369@gmail.com", "pwd")

        res = self.api.send_daily_report_now("karthikeyansa369@gmail.com")
        self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()
