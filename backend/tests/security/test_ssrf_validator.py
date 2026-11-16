"""Security Test: SSRF Validator (TST-09 / ISS-022).

Verifies that MCP URL validation blocks direct private/link-local/cloud-metadata IP addresses
as well as hostnames that resolve via DNS to private or cloud-metadata IP addresses.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from app.core.errors import APIError, ErrorCode
from app.services.mcp_elicitation_service import validate_mcp_url


def test_tst09_ssrf_direct_ip_addresses_rejected() -> None:
    """Direct IP addresses targeting private ranges, loopback, or metadata must be rejected."""
    blocked_cases = [
        "https://10.0.0.1/mcp",
        "https://172.16.0.1/mcp",
        "https://192.168.1.1/mcp",
        "https://169.254.169.254/latest/meta-data/",
        "https://100.100.100.200/metadata",
        "https://0.0.0.0/mcp",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://service.internal/api",
        "https://worker.local/sse",
    ]

    for url in blocked_cases:
        with pytest.raises(APIError) as exc_info:
            validate_mcp_url(url)
        assert exc_info.value.code == ErrorCode.MCP_SECURITY_VIOLATION
        assert exc_info.value.status_code == 403


def test_tst09_ssrf_stub_dns_resolver_private_ranges_rejected() -> None:
    """Hostnames that resolve via DNS to private or cloud metadata IPs must be rejected."""
    rebind_test_cases = [
        ("https://mock-rebind.attacker.com/sse", "10.0.0.1"),
        ("https://mock-meta.attacker.com/sse", "169.254.169.254"),
        ("https://mock-private-172.attacker.com/mcp", "172.16.5.10"),
        ("https://mock-private-192.attacker.com/mcp", "192.168.0.50"),
        ("https://mock-loopback.attacker.com/mcp", "127.0.0.2"),
    ]

    for url, resolved_ip in rebind_test_cases:
        mock_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved_ip, 443))]
        with patch("socket.getaddrinfo", return_value=mock_addrinfo):
            with pytest.raises(APIError) as exc_info:
                validate_mcp_url(url)
            assert exc_info.value.code == ErrorCode.MCP_SECURITY_VIOLATION
            assert exc_info.value.status_code == 403


def test_tst09_ssrf_valid_public_https_mcp_allowed() -> None:
    """Valid external HTTPS URLs that resolve to public IPs must be accepted."""
    mock_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        validated = validate_mcp_url("https://example.com/mcp")
        assert validated == "https://example.com/mcp"
