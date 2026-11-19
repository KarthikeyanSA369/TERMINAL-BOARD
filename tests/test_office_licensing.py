"""
Tests for Microsoft Office Activation Detection & OSPP Telemetry.
Validates script discovery, raw cscript output parsing, status normalization,
multi-product handling, and error/timeout safety.
"""
import pytest
from unittest.mock import patch, MagicMock
from backend.core.office_licensing import (
    normalize_office_license_status,
    parse_ospp_dstatus_output,
    query_office_activation,
    find_office_ospp_script
)

SAMPLE_OSPP_ACTIVATED_OUTPUT = """
Microsoft (R) Windows Script Host Version 5.812
Copyright (C) Microsoft Corporation. All rights reserved.

---Processing--------------------------
---------------------------------------
SKU ID: 2b88c4f2-4cfd-4119-a4d6-08168d304245
LICENSE NAME: Office 16, Office16ProPlusMSDNR_Retail edition
LICENSE DESCRIPTION: Office 16, RETAIL channel
BETA EXPIRATION: 01-01-1601
LICENSE STATUS:  ---LICENSED--- 
ERROR CODE: 0x4004FC04 (for information purposes only, as the status is licensed)
ERROR DESCRIPTION: The Software Licensing Service reported that the application is running within the valid grace period.
Last 5 characters of installed product key: WFG99
---------------------------------------
---------------------------------------
---Exiting-----------------------------
"""

SAMPLE_OSPP_NOTIFICATION_OUTPUT = """
Microsoft (R) Windows Script Host Version 5.812
Copyright (C) Microsoft Corporation. All rights reserved.

---Processing--------------------------
---------------------------------------
SKU ID: 8c762649-97d1-4953-aab0-8240409bc142
LICENSE NAME: Office 15, OfficeStandardVL_KMS_Client edition
LICENSE DESCRIPTION: Office 15, VOLUME_KMSCLIENT channel
LICENSE STATUS:  ---NOTIFICATIONS--- 
ERROR CODE: 0xC004F00F
ERROR DESCRIPTION: The Software Licensing Service reported that the hardware ID binding is beyond level of tolerance.
Last 5 characters of installed product key: 92CD4
---------------------------------------
---Exiting-----------------------------
"""

SAMPLE_OSPP_GRACE_PERIOD_OUTPUT = """
---Processing--------------------------
---------------------------------------
SKU ID: aaaa-bbbb-cccc-dddd
LICENSE NAME: Office 19, Office19HomeBusiness2019R_Retail edition
LICENSE DESCRIPTION: Office 19, RETAIL channel
LICENSE STATUS:  ---OOB_GRACE--- 
REMAINING GRACE: 14 days  (20160 minute(s) before expiring)
Last 5 characters of installed product key: ABCDE
---------------------------------------
---Exiting-----------------------------
"""

SAMPLE_OSPP_UNLICENSED_OUTPUT = """
---Processing--------------------------
---------------------------------------
SKU ID: 1111-2222-3333-4444
LICENSE NAME: Office 16, Office16StandardVL_KMS_Client edition
LICENSE DESCRIPTION: Office 16, VOLUME_KMSCLIENT channel
LICENSE STATUS:  ---UNLICENSED--- 
ERROR CODE: 0xC004F014
ERROR DESCRIPTION: The Software Licensing Service reported that the product key is not available.
---------------------------------------
---Exiting-----------------------------
"""


def test_normalize_office_status():
    """Verify that raw OSPP status strings normalize to documented values."""
    assert normalize_office_license_status("---LICENSED---") == "ACTIVATED"
    assert normalize_office_license_status("LICENSED") == "ACTIVATED"
    assert normalize_office_license_status("---NOTIFICATIONS---") == "NOTIFICATIONS"
    assert normalize_office_license_status("---OOB_GRACE---") == "GRACE_PERIOD"
    assert normalize_office_license_status("---UNLICENSED---") == "NOT_ACTIVATED"
    assert normalize_office_license_status("RANDOM_STRING") == "UNKNOWN"


def test_parse_activated_output():
    """Verify parsing of standard activated retail Office output."""
    records = parse_ospp_dstatus_output(SAMPLE_OSPP_ACTIVATED_OUTPUT)
    assert len(records) == 1
    r = records[0]
    assert r["normalized_status"] == "ACTIVATED"
    assert r["last_5_key"] == "WFG99"
    assert "Office16ProPlusMSDNR_Retail" in r["license_name"]
    assert "Retail" in r["license_channel"]


def test_parse_notification_kms_output():
    """Verify parsing of real KMS notification output with hardware binding error code."""
    records = parse_ospp_dstatus_output(SAMPLE_OSPP_NOTIFICATION_OUTPUT)
    assert len(records) == 1
    r = records[0]
    assert r["normalized_status"] == "NOTIFICATIONS"
    assert r["last_5_key"] == "92CD4"
    assert "OfficeStandardVL_KMS_Client" in r["license_name"]
    assert "Volume KMS" in r["license_channel"]
    assert r["error_code"] == "0xC004F00F"
    assert "hardware id binding" in r["error_description"].lower()


def test_parse_grace_period_output():
    """Verify parsing of out-of-box grace period with countdown days."""
    records = parse_ospp_dstatus_output(SAMPLE_OSPP_GRACE_PERIOD_OUTPUT)
    assert len(records) == 1
    r = records[0]
    assert r["normalized_status"] == "GRACE_PERIOD"
    assert r["last_5_key"] == "ABCDE"
    assert r["remaining_grace_days"] == 14


def test_parse_unlicensed_output():
    """Verify parsing of unlicensed product."""
    records = parse_ospp_dstatus_output(SAMPLE_OSPP_UNLICENSED_OUTPUT)
    assert len(records) == 1
    r = records[0]
    assert r["normalized_status"] == "NOT_ACTIVATED"
    assert r["error_code"] == "0xC004F014"


def test_parse_empty_or_error_output():
    """Verify robust handling of empty, error, or uninstalled output."""
    res_empty = parse_ospp_dstatus_output("")
    assert res_empty == []

    res_err = parse_ospp_dstatus_output("Input Error: Can not find script file OSPP.VBS")
    assert res_err == []


@patch("os.path.isfile", return_value=True)
@patch("backend.core.office_licensing.find_office_ospp_script")
@patch("subprocess.run")
def test_query_office_activation_subprocess_timeout(mock_run, mock_find_path, mock_isfile):
    """Verify timeout safety (never hangs application indefinitely)."""
    import subprocess
    mock_find_path.return_value = r"C:\Program Files\Microsoft Office\Office16\OSPP.VBS"
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["cscript"], timeout=25)

    result = query_office_activation(force_refresh=True)
    assert result["is_installed"] is True
    assert result["primary_status"] == "UNKNOWN"
    assert "timed out" in result["diagnostic_reason"].lower()


def test_live_office_activation_query_safe():
    """Run live read-only Office activation query without crashing or altering state."""
    result = query_office_activation()
    assert isinstance(result, dict)
    assert "primary_status" in result
    assert "is_installed" in result
    assert result["primary_status"] in [
        "ACTIVATED", "NOT_ACTIVATED", "GRACE_PERIOD", "NOTIFICATIONS", "UNKNOWN", "UNSUPPORTED"
    ]
