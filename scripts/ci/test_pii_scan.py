"""Tests for scripts/ci/pii_scan.py. Run: python -m pytest scripts/ci/test_pii_scan.py -q"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pii_scan import added_lines, is_target_path, main, scan_diff, scan_line, scannable_text  # noqa: E402


def _kinds(text: str) -> list[str]:
    return [kind for kind, _ in scan_line(text)]


# --- which files are scanned ------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "backend/tests/fixtures/leads.json",
        "frontend/tests/fixtures/sample.txt",
        "backend/testdata/people.yaml",
        "supabase/seed.sql",
        "backend/scripts/seed_linkedin_youtube_ingestion.py",
        "data/contacts.csv",
        "frontend/public/manifest.json",
        "backend/evals/transcripts.jsonl",
        "data/events.ndjson",
        "data/contacts.tsv",
        "backend/tests/cases.yaml",
        "frontend/tests/e2e/users.yml",
        "backend/tests/test_leads.py",
        "backend/tests/integration/helpers.py",
    ],
)
def test_target_paths(path: str) -> None:
    assert is_target_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "backend/modules/graph_outbox.py",
        "frontend/package-lock.json",
        "frontend/pnpm-lock.yaml",
        "frontend/tsconfig.json",
        "frontend/node_modules/x/data.json",
        "docs/README.md",
        ".github/workflows/lint.yml",
        "frontend/tests/e2e/login.spec.ts",
        "scripts/agent/test_tiers.py",
    ],
)
def test_non_target_paths(path: str) -> None:
    assert not is_target_path(path)


# --- emails -------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        '"email": "jane.doe@gmail.com"',
        "owner,rahul.k@acme-corp.io,active",
        '{"to": "someone@personaon.com"}',
        '"email": "test.user@gmail.com"',
        '"email": "test+1@gmail.com"',
        '"email": "anyone@test.acme.com"',
        '"email": "noreply@personaon.com"',
        '"email": "qa@test.com"',
    ],
)
def test_real_emails_flagged(line: str) -> None:
    assert _kinds(line) == ["email"]


@pytest.mark.parametrize(
    "line",
    [
        '"email": "user@example.com"',
        '"email": "a@example.org", "b": "b@sub.example.net"',
        '"email": "lead@personaon.test"',
        '"email": "qa@mail.test"',
        '"dep": "@types/node", "v": "react@18.3.1"',
        '"email": "bot@foo.invalid"',
        '"email": "bot@acme.example"',
        '"email": "dev@app.localhost"',
    ],
)
def test_safe_emails_ignored(line: str) -> None:
    assert _kinds(line) == []


def test_email_masked_in_output() -> None:
    [(kind, masked)] = scan_line('"email": "jane.doe@gmail.com"')
    assert kind == "email"
    assert "jane" not in masked and masked.endswith("@gmail.com")


# --- phones -------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        '"phone": "+1 415 867 2301"',
        '"phone": "(415) 867-2301"',
        '"phone": "415-867-2301"',
        '"phone": "+919845012345"',
    ],
)
def test_real_phones_flagged(line: str) -> None:
    assert _kinds(line) == ["phone"]


@pytest.mark.parametrize(
    "line",
    [
        '"phone": "+1 555 0100"',
        '"phone": "415-555-0142"',
        '"phone": "000-000-0000"',
        '"phone": "123-456-7890"',
        '"id": "c9f1b8a2-4155-4867-8230-1a2b3c4d5e6f"',
        '"ts": 1729352345123',
        '"date": "2026-10-19"',
        '"version": "1.415.867"',
    ],
)
def test_safe_phones_ignored(line: str) -> None:
    assert _kinds(line) == []


# --- SSNs and cards -------------------------------------------------------------


def test_ssn_flagged() -> None:
    assert _kinds('"ssn": "512-44-9087"') == ["ssn"]


@pytest.mark.parametrize("ssn", ["000-12-3456", "666-12-3456", "912-34-5678", "123-45-6789", "078-05-1120"])
def test_fake_ssns_ignored(ssn: str) -> None:
    assert _kinds(f'"ssn": "{ssn}"') == []


def test_card_flagged() -> None:
    # Luhn-valid, not a published test number.
    assert _kinds('"card": "4539 1488 0343 6467"') == ["card-number"]


@pytest.mark.parametrize("card", ["4242 4242 4242 4242", "4111111111111111", "4539 1488 0343 6468"])
def test_test_or_invalid_cards_ignored(card: str) -> None:
    assert _kinds(f'"card": "{card}"') == []


def test_allow_marker_suppresses() -> None:
    assert _kinds("email: jane.doe@gmail.com  # pii-scan: allow") == []


# --- backend test code: string literals only ------------------------------------


def test_py_test_scans_string_literals_only() -> None:
    path = "backend/tests/test_leads.py"
    assert _kinds(scannable_text(path, 'lead = {"email": "jane.doe@gmail.com"}')) == ["email"]
    assert _kinds(scannable_text(path, "send(to='+1 415 867 2301')")) == ["phone"]
    assert _kinds(scannable_text(path, "# reported by jane.doe@gmail.com")) == []
    assert _kinds(scannable_text(path, 'x = "jane.doe@gmail.com"  # pii-scan: allow')) == []


def test_non_py_lines_scanned_whole() -> None:
    assert scannable_text("backend/tests/cases.yaml", "email: jane.doe@gmail.com") == "email: jane.doe@gmail.com"


# --- diff parsing ---------------------------------------------------------------

_DIFF = """\
diff --git a/backend/tests/fixtures/leads.json b/backend/tests/fixtures/leads.json
index 1111111..2222222 100644
--- a/backend/tests/fixtures/leads.json
+++ b/backend/tests/fixtures/leads.json
@@ -3,0 +4,2 @@
+  {"email": "jane.doe@gmail.com"},
+  {"email": "user@example.com"}
@@ -10 +12 @@
-  {"phone": "old"}
+  {"phone": "(415) 867-2301"}
diff --git a/backend/modules/emailer.py b/backend/modules/emailer.py
--- a/backend/modules/emailer.py
+++ b/backend/modules/emailer.py
@@ -1,0 +2 @@
+FROM = "jane.doe@gmail.com"
diff --git a/backend/tests/test_leads.py b/backend/tests/test_leads.py
--- a/backend/tests/test_leads.py
+++ b/backend/tests/test_leads.py
@@ -7,0 +8,2 @@
+# owner: jane.doe@gmail.com
+LEAD = {"email": "r.okafor@northwind-traders.io"}
diff --git a/backend/tests/fixtures/gone.json b/backend/tests/fixtures/gone.json
deleted file mode 100644
--- a/backend/tests/fixtures/gone.json
+++ /dev/null
@@ -1 +0,0 @@
-{"email": "jane.doe@gmail.com"}
"""


def test_added_lines_tracks_line_numbers() -> None:
    lines = list(added_lines(_DIFF))
    assert ("backend/tests/fixtures/leads.json", 4, '  {"email": "jane.doe@gmail.com"},') in lines
    assert ("backend/tests/fixtures/leads.json", 12, '  {"phone": "(415) 867-2301"}') in lines
    assert all(path != "backend/tests/fixtures/gone.json" for path, _, _ in lines)


def test_scan_diff_only_added_lines_in_target_files() -> None:
    findings = scan_diff(_DIFF)
    assert [(f.path, f.line, f.kind) for f in findings] == [
        ("backend/tests/fixtures/leads.json", 4, "email"),
        ("backend/tests/fixtures/leads.json", 12, "phone"),
        ("backend/tests/test_leads.py", 9, "email"),
    ]


def test_main_returns_2_on_bad_ref(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--base", "no-such-ref-xyz", "--head", "HEAD"]) == 2
