"""Test Network Diagnostics Engine"""
import pytest
from backend.core.network import (
    test_dns_resolution as probe_dns, get_default_gateway, ping_host,
    get_network_interfaces, check_localhost_ports,
    run_comprehensive_network_diagnosis
)

def test_dns_resolution_query():
    res = probe_dns("cloudflare.com")
    assert "success" in res
    assert "latency_ms" in res
    assert res["host"] == "cloudflare.com"

def test_network_interfaces():
    interfaces = get_network_interfaces()
    assert isinstance(interfaces, list)
    if interfaces:
        i = interfaces[0]
        assert "name" in i
        assert "ipv4" in i

def test_localhost_ports_scan():
    ports = check_localhost_ports([5000, 8000, 8080])
    assert len(ports) == 3
    assert all("is_active" in p for p in ports)

def test_comprehensive_network_diagnosis():
    diag = run_comprehensive_network_diagnosis()
    assert "health_status" in diag
    assert "root_cause" in diag
    assert "recommendation" in diag
    assert "adapters" in diag
