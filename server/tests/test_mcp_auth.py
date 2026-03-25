import pytest
from routers.mcp_auth import verify_domain


def test_verify_domain_allowed():
    assert verify_domain("alice@company.com", "company.com") is True


def test_verify_domain_rejected():
    assert verify_domain("alice@other.com", "company.com") is False


def test_verify_domain_empty_allowed_domain():
    """Empty ALLOWED_DOMAIN means allow all."""
    assert verify_domain("anyone@anywhere.com", "") is True
