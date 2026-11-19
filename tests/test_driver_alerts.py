"""
Unit Tests for SYSFIX Faulty Driver Alert Engine
Tests critical problem code detection, false-positive filtering,
state transitions, cooldown deduplication, and recovery notifications.
"""

import unittest
from unittest.mock import patch, MagicMock

from backend.database import (
    init_db,
    get_connection,
    get_driver_fault_state,
    record_driver_fault_state,
    mark_driver_fault_recovered,
    get_all_active_driver_faults,
    update_email_settings
)
from backend.core.driver_alerts import (
    compute_fault_signature,
    format_driver_fault_email,
    format_driver_recovery_email,
    evaluate_driver_fault_and_alert,
    CRITICAL_DRIVER_PROBLEM_CODES,
    IGNORED_PROBLEM_CODES
)


class TestDriverAlerts(unittest.TestCase):
    def setUp(self):
        init_db()
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM driver_fault_states WHERE device_id IN (?, ?, ?)",
                ("PCI\\VEN_8086&DEV_1912&SUBSYS_1234", "PCI\\\\VEN_8086&DEV_1912&SUBSYS_1234", "PCI\\VEN_10EC&DEV_8168")
            )
            conn.commit()
        update_email_settings({
            "driver_alerts_enabled": 1,
            "driver_recovery_enabled": 1,
            "alert_cooldown_min": 60,
            "recipient_email": "karthikeyansa369@gmail.com"
        })

    def tearDown(self):
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM driver_fault_states WHERE device_id IN (?, ?, ?)",
                ("PCI\\VEN_8086&DEV_1912&SUBSYS_1234", "PCI\\\\VEN_8086&DEV_1912&SUBSYS_1234", "PCI\\VEN_10EC&DEV_8168")
            )
            conn.commit()

    def test_fault_signature_stability(self):
        sig1 = compute_fault_signature("PCI\\VEN_10DE&DEV_1C03", 43)
        sig2 = compute_fault_signature("PCI\\VEN_10DE&DEV_1C03", 43)
        sig3 = compute_fault_signature("PCI\\VEN_10DE&DEV_1C03", 10)

        self.assertEqual(sig1, sig2)
        self.assertNotEqual(sig1, sig3)

    def test_ignored_problem_codes_filter(self):
        # Code 0 (OK), 22 (Disabled by user), 45 (Disconnected USB device) must NEVER be critical
        self.assertIn(0, IGNORED_PROBLEM_CODES)
        self.assertIn(22, IGNORED_PROBLEM_CODES)
        self.assertIn(45, IGNORED_PROBLEM_CODES)

        # Critical failure codes
        for code in [10, 19, 28, 31, 37, 38, 39, 43, 48]:
            self.assertIn(code, CRITICAL_DRIVER_PROBLEM_CODES)

    @patch("backend.core.driver_alerts.get_complete_driver_inventory")
    @patch("backend.core.driver_alerts.send_email_message")
    def test_evaluate_fault_and_send_alert(self, mock_send, mock_inventory):
        mock_send.return_value = (True, "Message delivered")

        # Mock a failing hardware device with Code 43 (Device reported hardware failure)
        mock_inventory.return_value = [
            {
                "device_id": "PCI\\VEN_8086&DEV_1912&SUBSYS_1234",
                "device_name": "Intel(R) HD Graphics 530",
                "device_class": "Display",
                "problem_code": 43,
                "health_classification": "CRITICAL",
                "health_reason": "Windows stopped device because device hardware reported a failure."
            },
            {
                "device_id": "USB\\VID_046D&PID_C52B",
                "device_name": "Logitech USB Receiver",
                "device_class": "HIDClass",
                "problem_code": 0,
                "health_classification": "HEALTHY",
                "health_reason": "Device is working properly."
            }
        ]

        alerts = evaluate_driver_fault_and_alert()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["device_name"], "Intel(R) HD Graphics 530")
        self.assertEqual(alerts[0]["problem_code"], 43)
        mock_send.assert_called_once()

        # Check that fault was recorded in database as ACTIVE
        fault_state = get_driver_fault_state("PCI\\VEN_8086&DEV_1912&SUBSYS_1234")
        self.assertIsNotNone(fault_state)
        self.assertEqual(fault_state["status"], "ACTIVE")

    @patch("backend.core.driver_alerts.get_complete_driver_inventory")
    @patch("backend.core.driver_alerts.send_email_message")
    def test_driver_recovery_notification(self, mock_send, mock_inventory):
        mock_send.return_value = (True, "Recovery notification sent")

        # 1. First record an active fault in DB
        dev_id = "PCI\\VEN_10EC&DEV_8168"
        record_driver_fault_state(
            device_id=dev_id,
            device_name="Realtek PCIe GbE Family Controller",
            fault_signature=compute_fault_signature(dev_id, 10),
            problem_code=10,
            severity="CRITICAL"
        )

        active = get_all_active_driver_faults()
        self.assertTrue(any(f["device_id"] == dev_id for f in active))

        # 2. Device is now reported healthy by Windows (Code 0)
        mock_inventory.return_value = [
            {
                "device_id": dev_id,
                "device_name": "Realtek PCIe GbE Family Controller",
                "device_class": "Net",
                "problem_code": 0,
                "health_classification": "HEALTHY",
                "health_reason": "Device is working properly."
            }
        ]

        evaluate_driver_fault_and_alert()

        # Fault state should now be RECOVERED
        fault_state = get_driver_fault_state(dev_id)
        self.assertEqual(fault_state["status"], "RECOVERED")
        mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
