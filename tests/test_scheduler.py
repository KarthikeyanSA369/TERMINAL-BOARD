"""
Unit Tests for SYSFIX Scheduler & Windows Task Scheduler Integration
Tests 7:00 PM next run time calculation, explicit user consent requirement,
and in-app schedule checks.
"""

import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from backend.database import init_db, update_email_settings, get_email_settings
from backend.core.scheduler import (
    get_next_daily_report_time,
    register_windows_scheduled_task,
    remove_windows_scheduled_task,
    query_windows_scheduled_task,
    check_and_execute_scheduled_tasks
)


class TestScheduler(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_next_daily_report_time_calculation(self):
        # Calculation for 19:00 (7:00 PM)
        next_dt = get_next_daily_report_time("19:00")
        self.assertIsInstance(next_dt, datetime)
        self.assertEqual(next_dt.hour, 19)
        self.assertEqual(next_dt.minute, 0)
        self.assertTrue(next_dt >= datetime.now())

    def test_explicit_consent_required_for_registration(self):
        # Attempt without consent must fail safely
        success, msg = register_windows_scheduled_task(time_str="19:00", user_consented=False)
        self.assertFalse(success)
        self.assertIn("consent is required", msg.lower())

    def test_explicit_consent_required_for_removal(self):
        # Attempt without consent must fail safely
        success, msg = remove_windows_scheduled_task(user_consented=False)
        self.assertFalse(success)
        self.assertIn("consent is required", msg.lower())

    @patch("subprocess.run")
    def test_register_windows_scheduled_task_with_consent(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        success, msg = register_windows_scheduled_task(time_str="19:00", user_consented=True)
        self.assertTrue(success)
        self.assertIn("successfully", msg.lower())

        settings = get_email_settings()
        self.assertTrue(settings.get("scheduler_registered"))

    @patch("subprocess.run")
    def test_remove_windows_scheduled_task_with_consent(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        success, msg = remove_windows_scheduled_task(user_consented=True)
        self.assertTrue(success)

        settings = get_email_settings()
        self.assertFalse(settings.get("scheduler_registered"))


if __name__ == "__main__":
    unittest.main()
