"""Test Diagnostics and Safe Actions Engine"""
import pytest
from backend.core.diagnostics import (
    run_all_diagnostics, execute_safe_action, diagnose_memory_pressure,
    diagnose_temp_storage, diagnose_dns_and_network_path
)

def test_run_all_diagnostics():
    findings = run_all_diagnostics()
    assert len(findings) >= 4
    for f in findings:
        assert "what_happened" in f
        assert "supporting_evidence" in f
        assert "possible_causes" in f
        assert "recommended_steps" in f
        assert "confidence" in f

def test_safe_action_rejection_without_confirmation():
    # Attempting to execute an action without user_confirmed must be rejected!
    res = execute_safe_action("flush_dns", {}, user_confirmed=False)
    assert res["success"] is False
    assert "User did not provide explicit confirmation" in res["message"]

def test_safe_action_flush_dns_confirmed():
    res = execute_safe_action("flush_dns", {}, user_confirmed=True)
    assert "action_id" in res
    assert res["action_id"] == "flush_dns"

def test_protected_pid_termination_denial():
    # Attempting to terminate PID 0 or PID 4 (System) must be denied
    res = execute_safe_action("kill_process", {"pid": 4}, user_confirmed=True)
    assert res["success"] is False
    assert "Protected System Process" in res["message"]
