"""List dependency changes in a PR and fail on new high/critical vulnerabilities.

Pilot step B4 (.github/workflows/security-scans.yml, job dependency-review).
Stdlib only; shells out to git, pip and npm.

actions/dependency-review-action needs the GitHub dependency graph, which on a
private repo needs GitHub Code Security (off for PersonaOn/PersonaOn). This is
the fallback:

  * Python (backend/requirements*.txt): resolve the changed file at base and at
    head with `pip install --dry-run --report` (no install), look the resolved
    versions up on OSV (osv.dev), and take severity from the GitHub advisory.
  * npm (package.json / package-lock.json): `npm audit --package-lock-only` on
    the lockfile at base and at head.

Only vulnerabilities that are HIGH/CRITICAL and present at head but not at base
fail the job, so pre-existing debt never blocks an unrelated PR. A base that
doesn't resolve counts as empty.

Not covered yet (by design, for now):
  * pnpm-lock.yaml and bun.lock(b) / yarn.lock are listed in the summary but
    NOT audited; frontend/package-lock.json (what `npm ci` uses) is.
  * Severity UNKNOWN (an OSV record with no GHSA severity) only warns; it never
    fails the job.

Usage: python scripts/ci/dep_review.py --base <sha> [--head <sha>]
Exit 0 clean, 1 new high/critical vulns, 2 tool/resolution error at head.
Run tests: python -m pytest scripts/ci/test_dep_review.py -q
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BLOCKING = {"HIGH", "CRITICAL"}
OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/{}"

_PY_MANIFEST = re.compile(r"(^|/)requirements[^/]*\.txt$")
_NPM_MANIFEST = re.compile(r"(^|/)package(-lock)?\.json$")
_OTHER_LOCK = re.compile(r"(^|/)(pnpm-lock\.yaml|yarn\.lock|bun\.lockb?)$")
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*?)\s*(#.*)?$")
_NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Change:
    manifest: str
    name: str
    old: str | None  # None = added
    new: str | None  # None = removed

    def describe(self) -> str:
        if self.old is None:
            return f"added `{self.name}` {self.new or '(any)'}"
        if self.new is None:
            return f"removed `{self.name}`"
        return f"changed `{self.name}` {self.old or '(any)'} -> {self.new or '(any)'}"


@dataclass(frozen=True)
class Vuln:
    package: str
    version: str
    vuln_id: str
    severity: str  # CRITICAL/HIGH/MODERATE/LOW/UNKNOWN
    summary: str


# --- git ------------------------------------------------------------------------


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)


def changed_files(base: str, head: str) -> list[str]:
    res = _run(["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"])
    if res.returncode != 0:
        raise ToolError(f"git diff failed: {res.stderr.strip()}")
    return [p for p in res.stdout.splitlines() if p and "node_modules/" not in p]


def show(ref: str, path: str) -> str | None:
    res = _run(["git", "show", f"{ref}:{path}"])
    return res.stdout if res.returncode == 0 else None


# --- manifest diffs ---------------------------------------------------------------


def parse_requirements(text: str) -> dict[str, str]:
    """Map normalised package name -> version spec ('' when unpinned)."""
    reqs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        m = _REQ_NAME.match(stripped)
        if m:
            name = re.sub(r"[-_.]+", "-", m.group(1)).lower()
            reqs[name] = m.group(3).split(";")[0].strip()
    return reqs


def parse_package_json(text: str) -> dict[str, str]:
    data = json.loads(text) if text.strip() else {}
    deps: dict[str, str] = {}
    for section in _NPM_SECTIONS:
        for name, spec in (data.get(section) or {}).items():
            deps[name] = str(spec)
    return deps


def diff_deps(manifest: str, old: dict[str, str], new: dict[str, str]) -> list[Change]:
    changes = [Change(manifest, n, None, new[n]) for n in sorted(new.keys() - old.keys())]
    changes += [Change(manifest, n, old[n], new[n]) for n in sorted(new.keys() & old.keys()) if old[n] != new[n]]
    changes += [Change(manifest, n, old[n], None) for n in sorted(old.keys() - new.keys())]
    return changes


def manifest_changes(path: str, base: str, head: str) -> list[Change]:
    old_text, new_text = show(base, path) or "", show(head, path) or ""
    if _PY_MANIFEST.search(path):
        return diff_deps(path, parse_requirements(old_text), parse_requirements(new_text))
    if PurePosixPath(path).name == "package.json":
        return diff_deps(path, parse_package_json(old_text), parse_package_json(new_text))
    return []


# --- Python: resolve + OSV ------------------------------------------------------------


def materialise_requirements(ref: str, path: str, dest: Path) -> Path | None:
    """Write every requirements*.txt next to `path` at `ref` (for -r includes)."""
    folder = str(PurePosixPath(path).parent)
    res = _run(["git", "ls-tree", "--name-only", ref, f"{folder}/"])
    names = [n for n in res.stdout.splitlines() if _PY_MANIFEST.search(n)] if res.returncode == 0 else []
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        text = show(ref, name)
        if text is not None:
            (dest / PurePosixPath(name).name).write_text(text, encoding="utf-8")
    target = dest / PurePosixPath(path).name
    return target if target.exists() else None


def resolve_python(req_file: Path) -> dict[str, str]:
    report = req_file.with_suffix(".report.json")
    cmd = [
        sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet",
        "--disable-pip-version-check", "--report", str(report), "-r", str(req_file),
    ]
    res = _run(cmd, cwd=str(req_file.parent))
    if res.returncode != 0:
        raise ToolError(f"pip could not resolve {req_file.name}: {res.stderr.strip()[-800:]}")
    data = json.loads(report.read_text(encoding="utf-8"))
    return {
        re.sub(r"[-_.]+", "-", item["metadata"]["name"]).lower(): item["metadata"]["version"]
        for item in data.get("install", [])
    }


def _http_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https URLs)
        return json.loads(resp.read().decode())


def osv_severity(record: dict, fetch=None) -> str:
    """GHSA-style severity from an OSV record, following GHSA aliases if needed."""
    sev = str((record.get("database_specific") or {}).get("severity") or "").upper()
    if sev:
        return "MODERATE" if sev == "MEDIUM" else sev
    fetch = fetch or (lambda vid: _http_json(OSV_VULN.format(vid)))
    for alias in record.get("aliases") or []:
        if alias.startswith("GHSA-"):
            alias_sev = str((fetch(alias).get("database_specific") or {}).get("severity") or "").upper()
            if alias_sev:
                return "MODERATE" if alias_sev == "MEDIUM" else alias_sev
    return "UNKNOWN"


def osv_vulns(packages: dict[str, str]) -> list[Vuln]:
    items = sorted(packages.items())
    vulns: list[Vuln] = []
    seen: set[tuple[str, str]] = set()  # (package, id or alias): PYSEC/GHSA dupes
    for start in range(0, len(items), 500):
        chunk = items[start : start + 500]
        queries = [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in chunk]
        results = _http_json(OSV_BATCH, {"queries": queries}).get("results", [])
        for (name, version), result in zip(chunk, results):
            for hit in result.get("vulns") or []:
                if (name, hit["id"]) in seen:
                    continue
                record = _http_json(OSV_VULN.format(hit["id"]))
                seen.update((name, i) for i in [hit["id"], *(record.get("aliases") or [])])
                vulns.append(Vuln(name, version, hit["id"], osv_severity(record), record.get("summary", "")[:120]))
    return vulns


def python_new_vulns(path: str, base: str, head: str, work: Path) -> list[Vuln]:
    head_file = materialise_requirements(head, path, work / "head")
    if head_file is None:
        return []  # file deleted
    head_pkgs = resolve_python(head_file)
    base_pkgs: dict[str, str] = {}
    base_file = materialise_requirements(base, path, work / "base")
    if base_file is not None:
        try:
            base_pkgs = resolve_python(base_file)
        except ToolError as exc:
            print(f"::warning::base {path} did not resolve, treating as empty: {exc}")
    # Only look up versions that are new at head; unchanged ones can't add vulns.
    new_pkgs = {n: v for n, v in head_pkgs.items() if base_pkgs.get(n) != v}
    return osv_vulns(new_pkgs)


# --- npm audit ------------------------------------------------------------------------


def npm_audit(ref: str, folder: str, work: Path) -> dict[tuple[str, str], Vuln]:
    lock = show(ref, f"{folder}/package-lock.json" if folder != "." else "package-lock.json")
    pkg = show(ref, f"{folder}/package.json" if folder != "." else "package.json")
    if lock is None or pkg is None:
        return {}
    work.mkdir(parents=True, exist_ok=True)
    (work / "package-lock.json").write_text(lock, encoding="utf-8")
    (work / "package.json").write_text(pkg, encoding="utf-8")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    res = _run([npm, "audit", "--package-lock-only", "--json"], cwd=str(work))
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ToolError(f"npm audit output unreadable for {folder}@{ref[:8]}: {res.stderr.strip()[-400:]}") from exc
    if "error" in data:
        raise ToolError(f"npm audit failed for {folder}@{ref[:8]}: {data['error'].get('summary', '')}")
    return parse_npm_audit(data)


def parse_npm_audit(data: dict) -> dict[tuple[str, str], Vuln]:
    found: dict[tuple[str, str], Vuln] = {}
    for name, entry in (data.get("vulnerabilities") or {}).items():
        for via in entry.get("via") or []:
            if not isinstance(via, dict):
                continue  # transitive pointer to another package's entry
            vid = str(via.get("url") or via.get("source") or via.get("title"))
            found[(name, vid)] = Vuln(
                name, str(entry.get("range", "")), vid, str(via.get("severity", "unknown")).upper(), via.get("title", "")
            )
    return found


# --- report -----------------------------------------------------------------------------


def render(changes: list[Change], others: list[str], new_vulns: list[Vuln]) -> str:
    lines = ["## Dependency review", ""]
    if changes or others:
        lines += [f"- `{c.manifest}`: {c.describe()}" for c in changes]
        lines += [f"- `{p}` changed (pnpm/bun/yarn lockfiles are not audited yet)" for p in others]
    else:
        lines.append("No dependency manifests changed.")
    lines += ["", "### New known vulnerabilities", ""]
    if new_vulns:
        lines += [f"- **{v.severity}** `{v.package}` {v.version}: {v.vuln_id} {v.summary}" for v in new_vulns]
    else:
        lines.append("None introduced by this change.")
    lines += ["", "_Fails only on new HIGH/CRITICAL. UNKNOWN severity is a warning._"]
    return "\n".join(lines) + "\n"


def review(base: str, head: str) -> int:
    files = changed_files(base, head)
    py = [p for p in files if _PY_MANIFEST.search(p)]
    npm_dirs = sorted({str(PurePosixPath(p).parent) for p in files if _NPM_MANIFEST.search(p)})
    others = [p for p in files if _OTHER_LOCK.search(p)]
    changes = [c for p in files if _PY_MANIFEST.search(p) or PurePosixPath(p).name == "package.json"
               for c in manifest_changes(p, base, head)]
    new_vulns: list[Vuln] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for i, path in enumerate(py):
            new_vulns += python_new_vulns(path, base, head, work / f"py{i}")
        for i, folder in enumerate(npm_dirs):
            head_audit = npm_audit(head, folder, work / f"npm{i}h")
            try:
                base_audit = npm_audit(base, folder, work / f"npm{i}b")
            except ToolError as exc:
                print(f"::warning::{exc}; treating base as empty")
                base_audit = {}
            new_vulns += [v for k, v in head_audit.items() if k not in base_audit]
    summary = render(changes, others, new_vulns)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(summary)
    blocking = [v for v in new_vulns if v.severity in BLOCKING]
    for v in new_vulns:
        level = "error" if v in blocking else "warning"
        print(f"::{level}::{v.severity} {v.package} {v.version}: {v.vuln_id}")
    return 1 if blocking else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        return review(args.base, args.head)
    except (ToolError, OSError) as exc:
        print(f"::error::dependency-review could not finish: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
