"""Shared email-format validation.

Mirrors the pattern in `backend/tests/test_phase_0_security.py:229` (regex
check before storing addresses) so the auth pipeline and the outbound
action-item-reminder pipeline use the same rule.

This is a *format* guard only — it does not verify the address resolves to
a real mailbox. Production code that sends mail still needs to handle
Resend bounces / Recall webhook delivery failures.
"""

from __future__ import annotations

import re

# Tightened regex (F6.6 review fix). The prior `^[^@\s]+@[^@\s]+\.[^@\s]+$`
# accepted obviously malformed domains: `a@.b.com` (dot-leading domain),
# `a@b..com` (consecutive dots), `a@[127.0.0.1]` (IP literals). The
# open-relay finding (Bug 1) is about NOT enqueueing bad input in the
# first place — Resend rejecting at send time is too late.
#
# The pattern below enforces:
#   - local part: standard RFC 5322 atoms, dot-separated, no leading/
#     trailing dot, no consecutive dots
#   - exactly one @ (the `[^@]` in domain labels handles this)
#   - domain: ≥ 2 dot-separated labels, each label LDH (letter-digit-hyphen)
#     starting and ending alphanumeric, TLD ≥ 2 alphabetic chars
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,}$"
)

# RFC 5321 § 4.5.3.1.3 caps a forward path at 254 octets. Defense against
# oversized strings reaching Resend / the send pipeline (S4 review fix).
_MAX_EMAIL_LENGTH = 254


def is_valid_email(value: object) -> bool:
    """Return True iff `value` is a syntactically plausible email address.

    Defensive against None / non-str / whitespace-only / oversized inputs.
    """
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or " " in candidate:
        return False
    if len(candidate) > _MAX_EMAIL_LENGTH:
        return False
    return bool(_EMAIL_RE.match(candidate))
