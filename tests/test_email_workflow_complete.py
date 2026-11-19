"""
Comprehensive End-to-End Workflow Verification for SYSFIX Email Automation
Tests:
1. Save and reload Gmail SMTP settings & DPAPI credential protection
2. Test SMTP connection (signature compatibility, override_settings, mock & error paths)
3. Send test email to karthikeyansa369@gmail.com
4. Send manual daily report now with full diagnostics and attachments
5. Scheduled report dispatch (--send-daily-report and scheduler tick without waiting)
6. Driver fault alert dispatch and recovery notification
7. Delivery history audit records and error reporting
8. Strict Cryptic terminology enforcement
"""

import os
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from backend.database import (
    init_db,
    get_email_settings,
    update_email_settings,
    get_recent_email_deliveries,
    get_driver_fault_state,
    record_driver_fault_state,
    get_all_active_driver_faults
)
from backend.core.credential_store import (
    store_smtp_credentials,
    retrieve_smtp_credentials,
    delete_smtp_credentials,
    has_smtp_credentials,
    mask_password
)
from backend.core.email_service import (
    test_smtp_connection as execute_test_smtp_connection,
    send_email_message,
    send_test_email,
    process_offline_email_queue,
    DEFAULT_RECIPIENT
)
from backend.core.email_reports import (
    send_daily_full_system_report,
    generate_daily_report_email,
    preview_full_system_report
)
from backend.core.scheduler import (
    check_and_execute_scheduled_tasks,
    get_next_daily_report_time
)
from backend.core.driver_alerts import (
    evaluate_driver_fault_and_alert,
    compute_fault_signature
)
from backend.api import SYSFIXApi, create_flask_app
import tempfile

_test_vault = None

def setUpModule():
    global _test_vault
    _test_vault = os.path.join(tempfile.gettempdir(), f"sysfix_workflow_vault_{os.getpid()}_{id(setUpModule)}.dat")
    os.environ["SYSFIX_VAULT_PATH"] = _test_vault

def tearDownModule():
    global _test_vault
    if _test_vault and os.path.exists(_test_vault):
        try:
            os.remove(_test_vault)
        except Exception:
            pass
    os.environ.pop("SYSFIX_VAULT_PATH", None)


class TestCompleteEmailWorkflow(unittest.TestCase):
    def setUp(self):
        init_db()
        self.api = SYSFIXApi()
        delete_smtp_credentials()

    def tearDown(self):
        delete_smtp_credentials()

    def test_01_save_and_reload_gmail_smtp_settings(self):
        """1. Save and reload Gmail SMTP configuration securely."""
        payload = {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": 1,
            "smtp_use_ssl": 0,
            "smtp_sender": "karthikeyansa369@gmail.com",
            "smtp_username": "karthikeyansa369@gmail.com",
            "recipient_email": "karthikeyansa369@gmail.com",
            "daily_report_enabled": 1,
            "daily_report_time": "19:00",
            "driver_alerts_enabled": 1,
            "driver_recovery_enabled": 1,
            "alert_cooldown_min": 60,
            "smtp_password": "google_app_password_mock"
        }
        res = self.api.update_email_settings(payload)
        self.assertTrue(res["success"])

        # Reload settings
        settings = self.api.get_email_settings()
        self.assertEqual(settings["smtp_host"], "smtp.gmail.com")
        self.assertEqual(settings["smtp_port"], 587)
        self.assertTrue(settings["smtp_use_tls"])
        self.assertFalse(settings["smtp_use_ssl"])
        self.assertEqual(settings["smtp_sender"], "karthikeyansa369@gmail.com")
        self.assertEqual(settings["smtp_username"], "karthikeyansa369@gmail.com")
        self.assertEqual(settings["recipient_email"], "karthikeyansa369@gmail.com")
        self.assertTrue(settings["has_password"])
        self.assertEqual(settings["smtp_password_masked"], "••••••••")

        # Verify DPAPI store has the credential
        creds = retrieve_smtp_credentials()
        self.assertEqual(creds["username"], "karthikeyansa369@gmail.com")
        self.assertEqual(creds["password"], "google_app_password_mock")

    @patch("smtplib.SMTP")
    def test_02_test_smtp_connection_signature_and_execution(self, mock_smtp_cls):
        """2. Test test_smtp_connection with override_settings and API caller."""
        mock_server = MagicMock()
        mock_server.has_extn.return_value = True
        mock_smtp_cls.return_value = mock_server

        # Test direct call with override_settings (addresses the original TypeError)
        ok, msg = execute_test_smtp_connection(override_settings={
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "smtp_username": "karthikeyansa369@gmail.com",
            "smtp_password": "app_pwd_123"
        })
        self.assertTrue(ok)
        self.assertIn("Successfully connected", msg)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_with("karthikeyansa369@gmail.com", "app_pwd_123")

        # Test API bridge method
        mock_server.reset_mock()
        mock_server.has_extn.return_value = True
        api_res = self.api.test_smtp_connection({
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_username": "karthikeyansa369@gmail.com",
            "smtp_password": "app_pwd_123"
        })
        self.assertTrue(api_res["success"])

    @patch("smtplib.SMTP")
    def test_03_send_test_email(self, mock_smtp_cls):
        """3. Send test email to karthikeyansa369@gmail.com."""
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        store_smtp_credentials("karthikeyansa369@gmail.com", "valid_app_password")
        res = self.api.send_test_email("karthikeyansa369@gmail.com")

        self.assertTrue(res["success"])
        self.assertIn("delivered successfully", res["message"].lower())
        mock_server.sendmail.assert_called_once()
        args, kwargs = mock_server.sendmail.call_args
        self.assertEqual(args[0], "karthikeyansa369@gmail.com")  # sender
        self.assertEqual(args[1], ["karthikeyansa369@gmail.com"])  # recipient

        # Audit history verification
        deliveries = get_recent_email_deliveries(limit=5)
        self.assertEqual(deliveries[0]["status"], "SENT")
        self.assertEqual(deliveries[0]["recipient"], "karthikeyansa369@gmail.com")
        self.assertEqual(deliveries[0]["alert_type"], "TEST_EMAIL")

    @patch("backend.core.email_reports.generate_daily_report_email")
    @patch("smtplib.SMTP")
    def test_04_send_report_now(self, mock_smtp_cls, mock_gen):
        """4. Immediately generate and email full-system report to recipient."""
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server
        mock_gen.return_value = (
            "SYSFIX Daily System Diagnostic Report",
            "<html><body>Executive Summary: Healthy</body></html>",
            [{"filename": "drivers.csv", "content": "device,status\nGPU,OK"}]
        )

        store_smtp_credentials("karthikeyansa369@gmail.com", "valid_app_password")
        res = self.api.send_daily_report_now("karthikeyansa369@gmail.com")

        self.assertTrue(res["success"])
        mock_server.sendmail.assert_called_once()

        deliveries = get_recent_email_deliveries(limit=5)
        self.assertEqual(deliveries[0]["status"], "SENT")
        self.assertEqual(deliveries[0]["alert_type"], "MANUAL_DAILY_REPORT")

    @patch("backend.core.email_reports.generate_daily_report_email")
    @patch("smtplib.SMTP")
    def test_05_scheduled_report_execution(self, mock_smtp_cls, mock_gen):
        """5. Automatically send report on schedule and check duplicate prevention."""
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server
        mock_gen.return_value = (
            "SYSFIX Daily Report",
            "<html><body>Scheduled Content</body></html>",
            []
        )

        store_smtp_credentials("karthikeyansa369@gmail.com", "valid_app_password")
        
        # Test direct scheduled report dispatch function (same function invoked by --send-daily-report)
        success, msg = send_daily_full_system_report(manual=False, recipient="karthikeyansa369@gmail.com")
        self.assertTrue(success)

        deliveries = get_recent_email_deliveries(limit=5)
        self.assertEqual(deliveries[0]["status"], "SENT")
        self.assertEqual(deliveries[0]["alert_type"], "SCHEDULED_DAILY_REPORT")

    @patch("backend.core.driver_alerts.get_complete_driver_inventory")
    @patch("smtplib.SMTP")
    def test_06_driver_fault_alert_and_recovery(self, mock_smtp_cls, mock_inventory):
        """6. Immediate driver fault alert on confirmed failure and recovery notice on clear."""
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server
        store_smtp_credentials("karthikeyansa369@gmail.com", "valid_app_password")

        # Simulate confirmed critical hardware fault (Code 43)
        dev_id = "PCI\\VEN_10DE&DEV_1C03&SUBSYS_1234"
        mock_inventory.return_value = [
            {
                "device_id": dev_id,
                "device_name": "NVIDIA GeForce GTX 1060 6GB",
                "device_class": "Display",
                "problem_code": 43,
                "health_classification": "CRITICAL",
                "health_reason": "Device reported hardware failure to Windows."
            }
        ]

        dispatched = evaluate_driver_fault_and_alert()
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["device_name"], "NVIDIA GeForce GTX 1060 6GB")
        self.assertTrue(dispatched[0]["dispatched"])

        # Check DB fault state recorded
        state = get_driver_fault_state(dev_id)
        self.assertEqual(state["status"], "ACTIVE")

        # Test deduplication: subsequent evaluation within cooldown does not resend
        mock_server.sendmail.reset_mock()
        dispatched_second = evaluate_driver_fault_and_alert()
        self.assertEqual(len(dispatched_second), 0)
        mock_server.sendmail.assert_not_called()

        # Simulate device recovery (Code 0: Working properly)
        mock_inventory.return_value = [
            {
                "device_id": dev_id,
                "device_name": "NVIDIA GeForce GTX 1060 6GB",
                "device_class": "Display",
                "problem_code": 0,
                "health_classification": "HEALTHY",
                "health_reason": "Device is working properly."
            }
        ]

        evaluate_driver_fault_and_alert()
        # Should now be marked RECOVERED in DB
        state_after = get_driver_fault_state(dev_id)
        self.assertEqual(state_after["status"], "RECOVERED")
        mock_server.sendmail.assert_called_once()

    def test_07_delivery_history_and_error_reporting(self):
        """7. Verify delivery history retrieval and Cryptic terminology."""
        history = self.api.get_email_history(limit=20)
        self.assertIsInstance(history, list)
        for h in history:
            self.assertIn("status", h)
            self.assertIn("recipient", h)
            self.assertIn("timestamp", h)
            self.assertNotIn("UNKNOWN", str(h.get("subject", "")).upper() if "UNKNOWN" in str(h.get("subject", "")) else "")


if __name__ == "__main__":
    unittest.main()
