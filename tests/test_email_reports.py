"""
Unit Tests for SYSFIX Daily Full-System Report Generator
Tests HTML compilation, attached CSV/HTML reports, and strict Cryptic terminology.
"""

import unittest
from unittest.mock import patch

from backend.database import init_db
from backend.core.email_reports import (
    generate_daily_report_email,
    send_daily_full_system_report,
    preview_full_system_report
)


class TestEmailReports(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_generate_daily_report_email_content(self):
        subject, html, attachments = generate_daily_report_email()

        self.assertIn("SYSFIX", subject)
        self.assertIn("Diagnostic Report", subject)
        self.assertTrue(len(html) > 500)

        # Verify HTML contains all critical system sections
        self.assertIn("Executive Diagnostic Summary", html)
        self.assertIn("Core Resource Utilization", html)
        self.assertIn("Storage Health &amp; Telemetry", html)
        self.assertIn("Hardware &amp; Driver Health Status", html)
        self.assertIn("Operating System &amp; Software Licensing", html)

        # Verify attachments are generated
        self.assertTrue(len(attachments) >= 1)
        filenames = [a["filename"] for a in attachments]
        self.assertTrue(any(f.endswith(".csv") for f in filenames))
        self.assertTrue(any(f.endswith(".html") for f in filenames))

        # Strict Cryptic Terminology Check
        self.assertNotIn(">UNKNOWN<", html)
        self.assertNotIn("Unknown", html)

    def test_preview_full_system_report(self):
        preview = preview_full_system_report()
        self.assertIn("subject", preview)
        self.assertIn("html", preview)
        self.assertIn("attachment_names", preview)
        self.assertTrue(len(preview["attachment_names"]) > 0)


if __name__ == "__main__":
    unittest.main()
