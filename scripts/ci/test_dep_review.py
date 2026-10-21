"""Tests for scripts/ci/dep_review.py. Run: python -m pytest scripts/ci/test_dep_review.py -q"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dep_review import (  # noqa: E402
    Change,
    Vuln,
    diff_deps,
    osv_severity,
    parse_npm_audit,
    parse_package_json,
    parse_requirements,
    render,
)


def test_parse_requirements_normalises_and_skips_options() -> None:
    text = """\
# comment
-r requirements.txt
fastapi[standard]
Google_ADK>=1.2  # pinned floor
pydantic==2.9.0 ; python_version >= "3.10"

"""
    assert parse_requirements(text) == {"fastapi": "", "google-adk": ">=1.2", "pydantic": "==2.9.0"}


def test_parse_package_json_merges_sections() -> None:
    text = '{"dependencies": {"next": "16.0.0"}, "devDependencies": {"typescript": "^5"}, "scripts": {"x": "y"}}'
    assert parse_package_json(text) == {"next": "16.0.0", "typescript": "^5"}


def test_parse_package_json_empty() -> None:
    assert parse_package_json("") == {}


def test_diff_deps_added_changed_removed() -> None:
    old = {"a": "1", "b": "1", "c": "1"}
    new = {"a": "1", "b": "2", "d": "1"}
    assert diff_deps("m", old, new) == [
        Change("m", "d", None, "1"),
        Change("m", "b", "1", "2"),
        Change("m", "c", "1", None),
    ]


def test_change_describe() -> None:
    assert Change("m", "x", None, "").describe() == "added `x` (any)"
    assert Change("m", "x", "1", "2").describe() == "changed `x` 1 -> 2"
    assert Change("m", "x", "1", None).describe() == "removed `x`"


def test_osv_severity_direct() -> None:
    assert osv_severity({"database_specific": {"severity": "HIGH"}}) == "HIGH"
    assert osv_severity({"database_specific": {"severity": "MEDIUM"}}) == "MODERATE"


def test_osv_severity_follows_ghsa_alias() -> None:
    records = {"GHSA-aaaa-bbbb-cccc": {"database_specific": {"severity": "CRITICAL"}}}
    rec = {"id": "PYSEC-2024-1", "aliases": ["CVE-2024-1", "GHSA-aaaa-bbbb-cccc"]}
    assert osv_severity(rec, fetch=records.__getitem__) == "CRITICAL"


def test_osv_severity_unknown() -> None:
    assert osv_severity({"id": "PYSEC-1", "aliases": []}) == "UNKNOWN"


def test_parse_npm_audit_keeps_advisories_only() -> None:
    data = {
        "vulnerabilities": {
            "lodash": {
                "range": "<4.17.21",
                "via": [{"url": "https://github.com/advisories/GHSA-x", "severity": "high", "title": "Proto pollution"}],
            },
            "wrapper": {"range": "*", "via": ["lodash"]},
        }
    }
    found = parse_npm_audit(data)
    assert list(found) == [("lodash", "https://github.com/advisories/GHSA-x")]
    assert found[("lodash", "https://github.com/advisories/GHSA-x")].severity == "HIGH"


def test_render_lists_changes_and_vulns() -> None:
    out = render(
        [Change("backend/requirements.txt", "requests", None, "==2.19.0")],
        ["frontend/pnpm-lock.yaml"],
        [Vuln("requests", "2.19.0", "GHSA-x", "HIGH", "bad")],
    )
    assert "added `requests` ==2.19.0" in out
    assert "frontend/pnpm-lock.yaml" in out
    assert "**HIGH** `requests` 2.19.0" in out


def test_render_nothing() -> None:
    out = render([], [], [])
    assert "No dependency manifests changed." in out
    assert "None introduced" in out
