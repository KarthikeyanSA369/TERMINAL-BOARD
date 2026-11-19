import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.core.notifications import (
    init_notifications_schema,
    is_category_enabled,
    dispatch_desktop_toast,
    get_notification_history,
    clear_notification_history
)

class TestNotifications(unittest.TestCase):
    def setUp(self):
        init_notifications_schema()

    def test_category_filtering(self):
        """Verify notification categories respect user settings toggles."""
        settings_all_on = {
            "notifications_enabled": "1",
            "notify_resource_alerts": "1",
            "notify_hardware_alerts": "1",
            "notify_network_alerts": "1"
        }
        self.assertTrue(is_category_enabled("resource", settings_all_on))
        self.assertTrue(is_category_enabled("hardware", settings_all_on))

        settings_disabled = {"notifications_enabled": "0"}
        self.assertFalse(is_category_enabled("resource", settings_disabled))
        self.assertFalse(is_category_enabled("system", settings_disabled))

    def test_toast_dispatch_and_history(self):
        """Verify toast dispatch records to history and handles duplicate suppression."""
        clear_notification_history()
        res1 = dispatch_desktop_toast("System Health OK", "All monitors nominal", "system")
        self.assertTrue(res1.get("success", False))

        # Duplicate dispatch within suppression window
        res2 = dispatch_desktop_toast("System Health OK", "All monitors nominal", "system")
        self.assertFalse(res2.get("success", True))
        self.assertIn("Suppressed", res2.get("reason", ""))

        history = get_notification_history(limit=10)
        self.assertIsInstance(history, list)
        self.assertGreaterEqual(len(history), 1)

        clear_notification_history()
        history_after = get_notification_history(limit=10)
        self.assertEqual(len(history_after), 0)

if __name__ == "__main__":
    unittest.main()
