"""
linkedin_export_parser.py

Parses LinkedIn 'Download My Data' ZIP exports and extracts structured
profile pack fields compatible with merge_profile_fields_partial().

LinkedIn export typically contains:
  Profile.csv       — name, headline, summary, websites
  Positions.csv     — work history
  Education.csv     — degrees and institutions
  Skills.csv        — list of skills
  Certifications.csv — professional certs (optional)

Public API:
    parse_linkedin_export_zip(zip_bytes) -> Optional[Dict[str, Any]]
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

# Confidence score for LinkedIn export data (high trust — self-reported, structured)
LINKEDIN_EXPORT_CONFIDENCE = 0.80

# CSV filenames inside the LinkedIn export ZIP (case-insensitive)
_PROFILE_CSV = "profile.csv"
_POSITIONS_CSV = "positions.csv"
_EDUCATION_CSV = "education.csv"
_SKILLS_CSV = "skills.csv"
_CERTIFICATIONS_CSV = "certifications.csv"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_csv(zip_file: zipfile.ZipFile, filename: str) -> list[dict[str, str]] | None:
    """Read a CSV file from the ZIP by case-insensitive name match."""
    name_map = {n.lower().split("/")[-1]: n for n in zip_file.namelist()}
    key = filename.lower()
    if key not in name_map:
        return None
    raw = zip_file.read(name_map[key]).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(raw))
    return [dict(row) for row in reader]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_year(value: Any) -> int | None:
    """Extract a 4-digit year from various LinkedIn date formats (Jan 2018, 2018, etc.)."""
    s = _clean(value)
    if not s:
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    if m:
        return int(m.group(1))
    return None


def _parse_profile(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Extract scalar fields from Profile.csv (usually a single row)."""
    result: dict[str, Any] = {}
    if not rows:
        return result

    row = rows[0]  # Profile.csv has one data row

    first = _clean(row.get("First Name") or row.get("first name"))
    last = _clean(row.get("Last Name") or row.get("last name"))
    if first or last:
        parts = [p for p in (first, last) if p]
        result["display_name"] = " ".join(parts)

    headline = _clean(row.get("Headline") or row.get("headline"))
    if headline:
        result["headline"] = headline

    summary = _clean(row.get("Summary") or row.get("summary"))
    if summary and len(summary) > 20:
        result["bio"] = summary[:2000]  # cap at 2000 chars

    # Websites: comma-separated list in one cell
    websites_raw = _clean(row.get("Websites") or row.get("websites"))
    if websites_raw:
        urls = [u.strip() for u in re.split(r"[,\n]+", websites_raw) if u.strip()]
        if urls:
            result["_websites"] = urls  # passed downstream to social_links

    return result


def _parse_positions(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse Positions.csv into work_experience list (max 5)."""
    work: list[dict[str, Any]] = []
    for row in rows[:10]:
        company = _clean(row.get("Company Name") or row.get("company name") or row.get("Company"))
        role = _clean(row.get("Title") or row.get("title"))
        if not company and not role:
            continue
        description = _clean(row.get("Description") or row.get("description"))
        start_year = _parse_year(row.get("Started On") or row.get("started on") or row.get("Start Date"))
        end_raw = _clean(row.get("Finished On") or row.get("finished on") or row.get("End Date"))
        end_year = _parse_year(end_raw) if end_raw and end_raw.lower() not in ("present", "") else None

        work.append({
            "company": company,
            "role": role,
            "description": description,
            "start_year": start_year,
            "end_year": end_year,
        })
        if len(work) >= 5:
            break
    return work


def _parse_education(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse Education.csv into education list (max 3)."""
    edu: list[dict[str, Any]] = []
    for row in rows[:6]:
        institution = _clean(
            row.get("School Name") or row.get("school name") or row.get("School")
        )
        degree = _clean(row.get("Degree Name") or row.get("degree name") or row.get("Degree"))
        if not institution and not degree:
            continue
        # LinkedIn Education.csv uses "End Date" or "Finished On"
        end_year = _parse_year(
            row.get("End Date") or row.get("end date") or row.get("Finished On")
        )
        # Field of study not always present in LinkedIn export
        field = _clean(
            row.get("Activities") or row.get("Notes") or row.get("Field of Study")
        )
        # Activities/Notes are not really the field — use degree as field fallback
        edu.append({
            "institution": institution,
            "degree": degree,
            "field": field if field and len(field) < 100 else None,
            "end_year": end_year,
        })
        if len(edu) >= 3:
            break
    return edu


def _parse_skills(rows: list[dict[str, str]]) -> list[str]:
    """Parse Skills.csv into areas_of_expertise list (max 8)."""
    skills: list[str] = []
    for row in rows:
        name = _clean(row.get("Name") or row.get("name") or (list(row.values())[0] if row else None))
        if name and len(name) < 60:
            skills.append(name)
        if len(skills) >= 8:
            break
    return skills


def _infer_role_and_org(work: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer current role/org from most-recent position (no end_year = current)."""
    result: dict[str, Any] = {}
    # Current = no end_year
    for entry in work:
        if not entry.get("end_year"):
            if entry.get("role"):
                result["role"] = entry["role"]
            if entry.get("company"):
                result["organization"] = entry["company"]
            break
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_linkedin_export_zip(zip_bytes: bytes) -> dict[str, Any] | None:
    """
    Parse a LinkedIn 'Download My Data' ZIP export and return structured
    profile pack fields ready for merge_profile_fields_partial().

    Args:
        zip_bytes: Raw bytes of the LinkedIn export ZIP file.

    Returns:
        Dict with any/all of: display_name, headline, bio, role, organization,
        areas_of_expertise, work_experience, education, social_links,
        plus confidence=0.80. Returns None if ZIP is invalid or empty.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        logger.warning("linkedin_export_parser: not a valid ZIP file")
        return None

    result: dict[str, Any] = {"confidence": LINKEDIN_EXPORT_CONFIDENCE}

    # --- Profile scalars ---
    profile_rows = _read_csv(zf, _PROFILE_CSV)
    if profile_rows:
        profile_data = _parse_profile(profile_rows)
        for k, v in profile_data.items():
            if not k.startswith("_"):
                result[k] = v
        websites = profile_data.get("_websites", [])
    else:
        websites = []

    # --- Work experience ---
    positions_rows = _read_csv(zf, _POSITIONS_CSV) or []
    work_exp = _parse_positions(positions_rows)
    if work_exp:
        result["work_experience"] = work_exp
        # Fill role/organization from most-recent current position
        inferred = _infer_role_and_org(work_exp)
        for k, v in inferred.items():
            if k not in result:
                result[k] = v

    # --- Education ---
    edu_rows = _read_csv(zf, _EDUCATION_CSV) or []
    education = _parse_education(edu_rows)
    if education:
        result["education"] = education

    # --- Skills → areas_of_expertise ---
    skills_rows = _read_csv(zf, _SKILLS_CSV) or []
    skills = _parse_skills(skills_rows)
    if skills:
        result["areas_of_expertise"] = skills

    # --- Social links from websites ---
    if websites:
        social_links: dict[str, str] = {}
        for url in websites:
            url_lower = url.lower()
            if "twitter.com" in url_lower or "x.com" in url_lower:
                social_links["twitter"] = url
            elif "github.com" in url_lower:
                social_links["github"] = url
            elif not any(k in url_lower for k in ("linkedin.com",)):
                # generic website
                social_links.setdefault("website", url)
        if social_links:
            result["social_links"] = social_links

    # Return None if nothing useful was extracted
    meaningful = [k for k in result if k != "confidence"]
    if not meaningful:
        logger.warning("linkedin_export_parser: no data extracted from ZIP")
        return None

    logger.info(
        "linkedin_export_parser: extracted %d fields (work=%d, edu=%d, skills=%d)",
        len(meaningful),
        len(result.get("work_experience") or []),
        len(result.get("education") or []),
        len(result.get("areas_of_expertise") or []),
    )
    return result
