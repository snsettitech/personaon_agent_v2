"""Tests for modules.email_validation.is_valid_email.

Pattern mirrors test_phase_0_security.py:229-257 (the email-format check
the auth pipeline already enforces).
"""

from __future__ import annotations

from modules.email_validation import is_valid_email


def test_valid_emails_pass() -> None:
    assert is_valid_email("user@example.com") is True
    assert is_valid_email("a.b+tag@sub.domain.com") is True
    assert is_valid_email("first.last@company.co.uk") is True


def test_obviously_invalid_emails_fail() -> None:
    assert is_valid_email("") is False
    assert is_valid_email("plainstring") is False
    assert is_valid_email("a@b") is False  # no dot in domain
    assert is_valid_email("a@b.") is False  # trailing dot, empty tld
    assert is_valid_email("@nodomain.com") is False  # empty local
    assert is_valid_email("user@@double.com") is False  # double @
    assert is_valid_email("user@") is False  # missing domain


def test_whitespace_and_none_fail() -> None:
    assert is_valid_email(None) is False  # type: ignore[arg-type]
    assert is_valid_email("  ") is False
    assert is_valid_email("user @example.com") is False  # internal space
    assert is_valid_email(" leadingspace@example.com") is True  # stripped first
    assert is_valid_email("trailing@example.com ") is True  # stripped first


def test_non_string_types_fail() -> None:
    assert is_valid_email(123) is False  # type: ignore[arg-type]
    assert is_valid_email(["a@b.com"]) is False  # type: ignore[arg-type]
    assert is_valid_email({"email": "a@b.com"}) is False  # type: ignore[arg-type]


# F6.6 (review fix): the prior regex was too permissive — it accepted
# clearly malformed domains. Tighter regex rejects:
def test_tightened_regex_rejects_malformed_domains() -> None:
    # Dot-leading domain
    assert is_valid_email("a@.b.com") is False
    # Consecutive dots in domain
    assert is_valid_email("a@b..com") is False
    # IP literal style (RFC 5321 allows it, we don't — we are not a mail server)
    assert is_valid_email("a@[127.0.0.1]") is False
    # Single-letter TLD
    assert is_valid_email("a@b.c") is False
    # Hyphen-leading label
    assert is_valid_email("a@-b.com") is False
    # Hyphen-trailing label
    assert is_valid_email("a@b-.com") is False
    # Consecutive dots in local part
    assert is_valid_email("a..b@c.com") is False
    # Leading dot in local part
    assert is_valid_email(".a@c.com") is False


# F6.6 / S4 review fix: cap address length at 254 octets per RFC 5321.
def test_oversized_addresses_rejected() -> None:
    from modules.email_validation import _MAX_EMAIL_LENGTH

    # Build something definitively over the cap.
    local = "a" * (_MAX_EMAIL_LENGTH + 10)
    long_address = f"{local}@example.com"
    assert len(long_address) > _MAX_EMAIL_LENGTH
    assert is_valid_email(long_address) is False

    # Exactly at the cap — still valid format.
    short_local = "a" * (_MAX_EMAIL_LENGTH - len("@example.com"))
    fits = f"{short_local}@example.com"
    assert len(fits) == _MAX_EMAIL_LENGTH
    assert is_valid_email(fits) is True
