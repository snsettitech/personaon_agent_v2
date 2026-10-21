"""Flag real-looking personal data added to fixtures, test data and seed files.

Pilot step B4 (.github/workflows/security-scans.yml, job pii-scan). Stdlib only.

Scans only the lines a change ADDS, and only in data-like files: anything under
a fixtures/testdata/seed path, *.json/*.jsonl/*.ndjson/*.csv/*.tsv anywhere
(lockfiles excluded), *.yaml/*.yml under tests/, and string literals in
backend/tests/**/*.py.
Looks for emails, phone numbers, US SSNs and card numbers, with allowlists for
reserved/fake values only: emails at example.com/.org/.net, *.test, *.example,
*.invalid or localhost; 555-01xx phones; published test cards; invalid SSNs.

Usage:
    python scripts/ci/pii_scan.py --base <sha> --head <sha>
Exit 0 when clean, 1 on findings (printed as file:line plus a GitHub
annotation), 2 on usage/git errors. Values are masked in the output so the
scan never re-publishes the data it found.

Suppress a reviewed false positive by putting "pii-scan: allow" on the line
(only possible in formats with comments, e.g. YAML or Python seeds).

Run tests: python -m pytest scripts/ci/test_pii_scan.py -q
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Iterator

ALLOW_MARKER = "pii-scan: allow"

_DATA_DIR = re.compile(
    r"(^|/)(fixtures?|__fixtures__|testdata|test[_-]data|seeds?|mocks?|samples?)(/|$)",
    re.IGNORECASE,
)
_SEED_FILE = re.compile(r"(^|/)[^/]*seed[^/]*$", re.IGNORECASE)
_DATA_EXT = re.compile(r"\.(json|jsonl|ndjson|csv|tsv)$", re.IGNORECASE)
_TEST_YAML = re.compile(r"(^|/)tests?/(.*/)?[^/]+\.ya?ml$", re.IGNORECASE)
_TEST_PY = re.compile(r"^backend/tests/(.*/)?[^/]+\.py$")
_STRING_LITERAL = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
_SKIP_FILE = re.compile(
    r"(^|/)(node_modules/|package-lock\.json$|pnpm-lock\.yaml$|yarn\.lock$|bun\.lockb?$|"
    r"composer\.lock$|tsconfig[^/]*\.json$|\.vscode/)",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
# Reserved by RFC 2606 / RFC 6761. Nothing else is treated as fake.
_SAFE_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}
_SAFE_TLDS = ("test", "example", "invalid", "localhost")

# E.164 (+ then 10-15 digits, optional spaces/dashes) or North American
# (NNN) NNN-NNNN / NNN-NNN-NNNN / NNN.NNN.NNNN. Separators are required for the
# national form so plain numeric ids and timestamps don't match.
_PHONE = re.compile(
    r"(?<![\w+-])(\+\d[\d \-]{8,17}\d|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4})(?![\w-])"
)
_SSN = re.compile(r"(?<![\w-])(\d{3})-(\d{2})-(\d{4})(?![\w-])")
_CARD = re.compile(r"(?<![\w-])(\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,7}|[45]\d{15})(?![\w-])")

# Published test card numbers (Stripe, Braintree, etc.).
_TEST_CARDS = {
    "4242424242424242",
    "4000056655665556",
    "4111111111111111",
    "4012888888881881",
    "5555555555554444",
    "5200828282828210",
    "5105105105105100",
    "378282246310005",
    "371449635398431",
    "6011111111111117",
    "4000000000000002",
    "4000000000009995",
    "4000002500003155",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    masked: str


def is_target_path(path: str) -> bool:
    """True for data-like files the scan covers."""
    if _SKIP_FILE.search(path):
        return False
    return bool(
        _DATA_DIR.search(path)
        or _SEED_FILE.search(path)
        or _DATA_EXT.search(path)
        or _TEST_YAML.search(path)
        or _TEST_PY.search(path)
    )


def scannable_text(path: str, text: str) -> str:
    """The part of a line to scan: string literals only for backend test code."""
    if _TEST_PY.search(path) and not (_DATA_DIR.search(path) or _SEED_FILE.search(path)):
        literals = " ".join(m.group(1) for m in _STRING_LITERAL.finditer(text))
        return f"{literals} {ALLOW_MARKER}" if ALLOW_MARKER in text else literals
    return text


def _email_is_safe(domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    if domain in _SAFE_DOMAINS or domain.split(".")[-1] in _SAFE_TLDS:
        return True
    if any(domain.endswith("." + d) for d in _SAFE_DOMAINS):
        return True
    # Package/scoped names like "@scope/pkg" or versions "pkg@1.2.3" aren't emails.
    return not re.search(r"[A-Za-z]{2,}$", domain)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _phone_is_safe(raw: str) -> bool:
    d = _digits(raw)
    if len(set(d)) <= 2:  # 000-000-0000, 1111111111, 1212121212
        return True
    # 555-0100..555-0199 is reserved for fiction in the NANP.
    if re.search(r"55501\d\d$", d):
        return True
    national = d[-10:]
    if national in {"1234567890", "0123456789", "9876543210"}:
        return True
    if raw.startswith("+"):
        return False
    # National form must look like a valid NANP number: area/exchange 2-9.
    return national[0] in "01" or national[3] in "01"


def _ssn_is_real_looking(area: str, group: str, serial: str) -> bool:
    if area in {"000", "666"} or area.startswith("9"):
        return False
    if group == "00" or serial == "0000":
        return False
    return f"{area}{group}{serial}" not in {"123456789", "078051120", "219099999"}


def _luhn_ok(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        n = int(ch)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask(value: str) -> str:
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    d = _digits(value)
    return f"***{d[-2:]}" if d else "***"


def scan_line(text: str) -> list[tuple[str, str]]:
    """Return (kind, masked value) for each real-looking item on one line."""
    if ALLOW_MARKER in text:
        return []
    hits: list[tuple[str, str]] = []
    for m in _EMAIL.finditer(text):
        if not _email_is_safe(m.group(2)):
            hits.append(("email", _mask(m.group(0))))
    card_spans: list[tuple[int, int]] = []
    for m in _CARD.finditer(text):
        num = _digits(m.group(1))
        if 13 <= len(num) <= 19 and num not in _TEST_CARDS and _luhn_ok(num):
            hits.append(("card-number", _mask(num)))
            card_spans.append(m.span())
    for m in _SSN.finditer(text):
        if _ssn_is_real_looking(*m.groups()):
            hits.append(("ssn", _mask(m.group(0))))
    for m in _PHONE.finditer(text):
        if any(s <= m.start() < e for s, e in card_spans):
            continue
        if not _phone_is_safe(m.group(1)):
            hits.append(("phone", _mask(m.group(1))))
    return hits


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """Yield (path, line number, text) for every added line in a unified diff."""
    path: str | None = None
    lineno = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target.removeprefix("b/")
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git"):
            continue
        hunk = _HUNK.match(raw)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            yield path, lineno, raw[1:]
            lineno += 1
        elif raw.startswith(" "):
            lineno += 1


def scan_diff(diff: str) -> list[Finding]:
    findings: list[Finding] = []
    for path, lineno, text in added_lines(diff):
        if not is_target_path(path):
            continue
        for kind, masked in scan_line(scannable_text(path, text)):
            findings.append(Finding(path, lineno, kind, masked))
    return findings


def git_diff(base: str, head: str) -> str:
    cmd = ["git", "diff", "--no-color", "--no-ext-diff", "--unified=0", "--no-renames", f"{base}...{head}"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
    return result.stdout


def report(findings: Iterable[Finding]) -> int:
    count = 0
    for f in findings:
        count += 1
        print(f"{f.path}:{f.line}: {f.kind} {f.masked}")
        print(f"::error file={f.path},line={f.line}::pii-scan: real-looking {f.kind} ({f.masked})")
    if count:
        print(
            f"\n{count} finding(s). Replace with fake data (user@example.com, "
            "+1 555 0100, 4242 4242 4242 4242) or add 'pii-scan: allow' on a reviewed line."
        )
    else:
        print("pii-scan: no real-looking personal data in added lines.")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="base commit (merge-base is used)")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        diff = git_diff(args.base, args.head)
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    return 1 if report(scan_diff(diff)) else 0


if __name__ == "__main__":
    sys.exit(main())
