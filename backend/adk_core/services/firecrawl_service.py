"""Firecrawl profile extraction service.

Uses Firecrawl's agent() API to extract a structured profile from the web.
The result is a Pydantic-validated ProfileSchema dict ready for storage.
"""

import json
import logging
import re
from datetime import datetime, timezone

from firecrawl import FirecrawlApp
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_apps: list[FirecrawlApp] = []
_app_index: int = 0


def _get_app() -> FirecrawlApp:
    """Lazy-init Firecrawl clients and round-robin across available API keys.

    Reads FIRECRAWL_API_KEY (primary) and FIRECRAWL_API_KEY_2, FIRECRAWL_API_KEY_3, ...
    up to _MAX_KEYS additional keys. Keys are rotated per-call so quota is spread
    across accounts.
    """
    global _apps, _app_index
    if not _apps:
        import os
        _MAX_KEYS = 10
        keys: list[str] = []
        primary = os.getenv("FIRECRAWL_API_KEY", "")
        if primary:
            keys.append(primary)
        for i in range(2, _MAX_KEYS + 2):
            k = os.getenv(f"FIRECRAWL_API_KEY_{i}", "")
            if k:
                keys.append(k)
        if not keys:
            raise ValueError("No FIRECRAWL_API_KEY configured")
        _apps = [FirecrawlApp(api_key=k) for k in keys]
        logger.info("[Firecrawl] initialized %d API key(s)", len(_apps))
    app = _apps[_app_index % len(_apps)]
    _app_index = (_app_index + 1) % len(_apps)
    return app


# ── Profile schema ───────────────────────────────────────────────────


class Education(BaseModel):
    institution: str = Field("", description="Name of the educational institution")
    degree: str = Field("", description="Degree obtained")
    field: str = Field("", description="Field of study")
    start_year: int | None = Field(None, description="Year studies began")
    end_year: int | None = Field(None, description="Year degree was completed")


class WorkExperience(BaseModel):
    company: str = Field("", description="Name of the company or organization")
    role: str = Field("", description="Job title or role held")
    description: str = Field("", description="Brief description of responsibilities")
    start_year: int | None = Field(None, description="Year the role started")
    end_year: int | None = Field(None, description="Year the role ended, or null if current")


class ProfileSchema(BaseModel):
    name: str = Field("", description="Full name of the individual")
    occupation: str = Field(
        "",
        description="Primary occupation(s) or job title(s), comma-separated if multiple",
    )
    birth_year: int | None = Field(None, description="Year of birth")
    death_year: int | None = Field(None, description="Year of death, or null if alive")
    nationality: str | None = Field(None, description="Nationality")
    short_description: str = Field(
        "",
        description="Concise one-line summary of who the individual is",
    )
    image_url: str | None = Field(None, description="URL to a public portrait image")
    personality_traits: list[str] = Field(
        default_factory=list,
        description="List of personality traits",
    )
    speaking_style: str | None = Field(
        None,
        description="Description of their speaking or communication style",
    )
    education: list[Education] = Field(
        default_factory=list,
        description="List of educational qualifications",
    )
    work_experience: list[WorkExperience] = Field(
        default_factory=list,
        description="List of work experiences",
    )
    key_achievements: list[str] = Field(
        default_factory=list,
        description="List of key accomplishments",
    )
    areas_of_expertise: list[str] = Field(
        default_factory=list,
        description="List of domains of expertise",
    )
    contributions: list[str] = Field(
        default_factory=list,
        description="Notable contributions to their field",
    )
    social_links: dict[str, str] = Field(
        default_factory=dict,
        description="Social media/web links (platform → URL)",
    )


# ── Quality threshold ────────────────────────────────────────────────

_QUALITY_FIELDS = ("occupation", "short_description", "personality_traits", "speaking_style")
_MIN_POPULATED = 3


def is_profile_rich(profile: dict) -> bool:
    """Check if extraction produced a rich-enough profile.

    Returns True if at least 3 of the 4 quality fields are populated.
    """
    count = 0
    for field in _QUALITY_FIELDS:
        value = profile.get(field)
        if value and (not isinstance(value, list) or len(value) > 0):
            count += 1
    return count >= _MIN_POPULATED


# ── Work-experience audit ────────────────────────────────────────────


def _coerce_int(value: object) -> int | None:
    """Return value as int only when it is a genuine int; otherwise None.

    Deliberately ignores str/float/None so audits never crash on dirty data
    and never silently coerce "2023" or 2023.0 into a span calculation.
    """
    if isinstance(value, bool):
        # bool is a subclass of int — never treat True/False as a year.
        return None
    if isinstance(value, int):
        return value
    return None


def audit_work_experience(profile: dict) -> list[str]:
    """Deterministically audit a profile's work_experience for collapse artifacts.

    Pure function — no I/O, no network. Returns a list of human-readable issue
    strings (empty list means clean). Detects three problem classes:

      - date_inverted: a role with int start_year and end_year where end < start.
      - single_year_span: a role where start_year == end_year (often a collapse
        artifact where a multi-year tenure shrank to one year).
      - understated_tenure: when bio/short_description/occupation text claims
        "~N years" at a company but the aggregated work_experience span for that
        company is materially shorter (actual + 1 < N).

    Robust to non-dict entries, missing/None/str years (only genuine ints count).
    """
    if not isinstance(profile, dict):
        return []

    work = profile.get("work_experience")
    if not isinstance(work, list) or not work:
        return []

    now_year = datetime.now(timezone.utc).year
    issues: list[str] = []

    # Per-company aggregation: company_key -> {"name", "starts", "ends", "count"}
    companies: dict[str, dict] = {}

    for entry in work:
        if not isinstance(entry, dict):
            continue

        start = _coerce_int(entry.get("start_year"))
        end = _coerce_int(entry.get("end_year"))
        company = entry.get("company")
        company = company.strip() if isinstance(company, str) else ""
        role = entry.get("role")
        role = role.strip() if isinstance(role, str) else ""
        label = f"{role} at {company}".strip() or company or role or "role"

        # date_inverted
        if start is not None and end is not None and end < start:
            issues.append(f"date_inverted: '{label}' has end_year {end} before start_year {start}")

        # single_year_span
        if start is not None and end is not None and start == end:
            issues.append(f"single_year_span: '{label}' spans only {start}-{end} (suspicious)")

        # aggregate per company for tenure check (need at least a start year)
        if company and start is not None:
            key = company.lower()
            agg = companies.setdefault(key, {"name": company, "starts": [], "ends": [], "count": 0})
            agg["starts"].append(start)
            # treat missing/non-int end as "current" (ongoing role)
            agg["ends"].append(end if end is not None else now_year)
            agg["count"] += 1

    # understated_tenure — compare claimed years in text against actual span.
    text_parts = [
        profile.get("bio"),
        profile.get("short_description"),
        profile.get("occupation"),
    ]
    combined_text = " ".join(p for p in text_parts if isinstance(p, str))

    if combined_text and companies:
        lower_text = combined_text.lower()
        # Map each years-claim to the single NEAREST company so a number like
        # "6+ years ... at Microsoft, now building PersonaOn" binds to Microsoft
        # only -- never to a farther company that merely shared the window.
        claimed_by_company = _claimed_years_by_nearest_company(
            lower_text, [agg["name"] for agg in companies.values()]
        )
        for agg in companies.values():
            claimed = claimed_by_company.get(agg["name"].lower())
            if claimed is None:
                continue
            actual = max(agg["ends"]) - min(agg["starts"])
            # Inverted/degenerate dates (end < start) make the aggregate span
            # negative and meaningless — date_inverted already flags those, so skip
            # the tenure check to avoid double-firing a spurious understated_tenure.
            if actual >= 0 and actual + 1 < claimed:
                issues.append(
                    f"understated_tenure: bio implies ~{claimed}y at '{agg['name']}' "
                    f"but work_experience spans ~{actual}y across {agg['count']} role(s)"
                )

    if issues:
        logger.info("[Firecrawl] work_experience audit found %d issue(s)", len(issues))

    return issues


_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*years?")
# A years-claim only binds to a company if that company is mentioned reasonably
# close to the number. Beyond this many characters the proximity is meaningless.
_MAX_CLAIM_DISTANCE = 70


def _company_mentions(lower_text: str, company_lower: str) -> list[tuple[int, int]]:
    """Return (start, end) char spans of every occurrence of `company_lower`."""
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = lower_text.find(company_lower, start)
        if idx == -1:
            return spans
        spans.append((idx, idx + len(company_lower)))
        start = idx + len(company_lower)


def _span_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Min char gap between two [start, end) intervals (0 if they touch/overlap)."""
    a_start, a_end = a
    b_start, b_end = b
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _claimed_years_by_nearest_company(
    lower_text: str, companies: list[str]
) -> dict[str, int | None]:
    r"""Bind each "N years" claim to the single NEAREST company mention.

    For every ``(\d{1,2})\s*\+?\s*years?`` occurrence in ``lower_text`` we find,
    among all mentions of the given ``companies``, the one whose mention span is
    closest (min char distance) to the number. Only that nearest company is
    credited with the claim — so "6+ years ... at Microsoft, now building
    PersonaOn" attributes 6 years to Microsoft and never to PersonaOn, even
    though both fall within the proximity window.

    Returns a mapping company_lower -> claimed years (int) for companies that won
    at least one nearest-match; companies that were never the nearest to any
    years-number are absent from the mapping. Case-insensitive; ``lower_text``
    must already be lowercased.

    When two companies are exactly equidistant from a number (rare — would
    require the number to sit between two adjacent company mentions), the claim
    is treated as ambiguous and credited to neither.
    """
    # Precompute every mention span for every distinct company.
    mention_index: list[tuple[str, tuple[int, int]]] = []
    for company in companies:
        company_lower = company.lower()
        if not company_lower:
            continue
        for span in _company_mentions(lower_text, company_lower):
            mention_index.append((company_lower, span))

    if not mention_index:
        return {}

    result: dict[str, int | None] = {}
    for m in _YEARS_RE.finditer(lower_text):
        try:
            claimed = int(m.group(1))
        except (ValueError, TypeError):
            continue
        # Distance is measured from the number-token to each company mention.
        num_start, num_end = m.start(), m.end()

        num_span = (num_start, num_end)
        best_company: str | None = None
        best_distance = _MAX_CLAIM_DISTANCE + 1
        ambiguous = False
        for company_lower, span in mention_index:
            dist = _span_distance(num_span, span)
            if dist < best_distance:
                best_distance = dist
                best_company = company_lower
                ambiguous = False
            elif dist == best_distance and company_lower != best_company:
                ambiguous = True

        if best_company is None or best_distance > _MAX_CLAIM_DISTANCE or ambiguous:
            continue

        # Keep the LARGEST claim attributed to a company (most conservative for
        # flagging understated tenure).
        prior = result.get(best_company)
        if prior is None or claimed > prior:
            result[best_company] = claimed

    return result


# ── OAuth validation ─────────────────────────────────────────────────


def validate_profile_against_snapshot(profile: dict, snapshot: dict) -> dict:
    """Cross-check Firecrawl-extracted profile against LinkedIn OAuth snapshot.

    Firecrawl scrapes the CURRENT LinkedIn profile — it is more up-to-date than
    the OAuth snapshot (which was captured at login time and may be stale).

    Rules:
      - If Firecrawl returned a populated field → trust it (current LinkedIn data)
      - If Firecrawl returned an empty field → fill from OAuth as fallback
      - Wrong-person detection: if extracted name does not match OAuth name,
        discard the entire profile (Firecrawl found a different person)
      - Image: prefer OAuth photo (higher resolution, directly from LinkedIn API)

    Args:
        profile: Raw dict from extract_profile().
        snapshot: LinkedIn profile_snapshot from connected_accounts table.
                  Expected keys: display_name, headline, profile_url, image_url.

    Returns:
        Validated profile dict with a `_validation` metadata key added.
    """
    if not snapshot:
        return profile

    validated = dict(profile)
    validation_log: list[str] = []

    oauth_name = (snapshot.get("display_name") or "").strip()
    oauth_headline = (snapshot.get("headline") or "").strip()
    oauth_image = (snapshot.get("image_url") or snapshot.get("picture") or "").strip()

    # ── 1. Wrong-person detection — name must match OAuth identity ────
    # If Firecrawl found a completely different person, discard everything.
    if oauth_name and validated.get("name"):
        extracted_name = validated["name"].strip().lower()
        oauth_name_lower = oauth_name.lower()
        # Check if at least one token from the OAuth name appears in the extracted name
        oauth_tokens = set(oauth_name_lower.split())
        extracted_tokens = set(extracted_name.split())
        shared_tokens = oauth_tokens & extracted_tokens
        last_name_token = oauth_name_lower.split()[-1] if oauth_name_lower else ""
        if len(shared_tokens) < 2 and last_name_token not in extracted_tokens:
            validation_log.append(
                f"wrong person detected: extracted name '{validated['name']}' "
                f"does not match OAuth name '{oauth_name}' — clearing profile"
            )
            logger.warning("[Firecrawl] wrong person detected for '%s', discarding extraction", oauth_name)
            validated["_validation"] = {
                "wrong_person": True,
                "corrections": validation_log,
            }
            return validated

    # ── 2. Name — always use OAuth (exact verified identity) ─────────
    if oauth_name:
        validated["name"] = oauth_name

    # ── 3. Occupation — trust Firecrawl if populated (current LinkedIn)
    # Fall back to OAuth headline only if Firecrawl returned nothing.
    if not validated.get("occupation") and oauth_headline:
        validated["occupation"] = oauth_headline
        validation_log.append(f"occupation filled from OAuth headline: '{oauth_headline}'")

    # ── 4. Image — prefer OAuth photo (higher res, direct from API) ───
    if oauth_image:
        validated["image_url"] = oauth_image

    if validation_log:
        logger.info("[Firecrawl] validation applied: %s", "; ".join(validation_log))

    validated["_validation"] = {
        "oauth_verified": ["name", "image_url"],
        "corrections": validation_log,
    }

    return validated


# ── Extraction ───────────────────────────────────────────────────────


def _sanitize_prompt_str(value: str, max_len: int = 300) -> str:
    """Strip newlines/tabs and cap length to reduce prompt-injection risk."""
    return value.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ').strip()[:max_len]


def extract_profile(
    person_name: str,
    context: str | None = None,
    linkedin_url: str | None = None,
    timeout: int = 480,
    repair: bool = True,
) -> dict:
    """Extract a profile from the web using Firecrawl agent.

    The agent is instructed to search broadly across LinkedIn, Google, Twitter/X,
    personal websites, press articles, and video transcripts. The LinkedIn URL
    (when provided) is used as an identity anchor — the agent confirms the correct
    person then expands its research across all public sources.

    Args:
        person_name: Full name of the person.
        context: Optional context like "CEO at Acme Corp" to help disambiguation.
        linkedin_url: LinkedIn profile URL used as an identity anchor.
        timeout: Per-call agent timeout in seconds.
        repair: When True (default), a deterministic audit runs on the extracted
            work_experience and, if collapse artifacts are detected, a guarded LLM
            re-extraction attempts to recover the missing roles. The repair is fully
            resilient — on any failure the original profile is returned unchanged.

    Returns:
        Profile dict matching ProfileSchema fields. When the work-experience audit
        flags issues, a non-empty ``extraction_review`` key is attached.

    Raises:
        TimeoutError: If extraction takes too long.
        Exception: On API failures.
    """
    if not person_name or not person_name.strip():
        raise ValueError("person_name must not be empty")

    app = _get_app()

    # Sanitize user-supplied strings before prompt interpolation to prevent injection.
    safe_name = _sanitize_prompt_str(person_name)
    safe_context = _sanitize_prompt_str(context, max_len=500) if context else None
    safe_linkedin_url = _sanitize_prompt_str(linkedin_url, max_len=300) if linkedin_url else None

    # Build an identity anchor so the agent never confuses this person with
    # someone who shares their name.
    identity_parts = [f"Full name: {safe_name}"]
    if safe_context:
        identity_parts.append(f"Context: {safe_context}")
    if safe_linkedin_url:
        identity_parts.append(f"LinkedIn profile: {safe_linkedin_url}")
    identity_block = "\n".join(identity_parts)

    prompt = f"""You are a deep-research agent. Your job is to build the most complete professional profile possible for the person identified below.

IDENTITY (use this to confirm you have the right person — do not confuse with others of the same name):
{identity_block}

RESEARCH STEPS — work through these in order, gathering as much data as possible:

1. LinkedIn: {("Visit " + safe_linkedin_url + " and extract everything visible — headline, about section, all work positions (company, role, dates, description), education, skills, recommendations, and any links.") if safe_linkedin_url else ("Search LinkedIn for " + safe_name + " and find their profile.")} List EVERY position as a SEPARATE entry — including multiple roles at the SAME company (promotions/title changes over time). Never merge a multi-role tenure into one entry.

2. Google search: Search for "{safe_name}" {("+ their company/role from step 1") if not safe_context else ("+ " + safe_context)}. Look at the top 5-10 results — personal website, company bio, press articles, blog posts.

3. Social media: Search for their Twitter/X account, YouTube channel, or podcast appearances. Find at least 3-5 real quotes or statements they have made.

4. Press & interviews: Look for any news articles, podcast interviews, conference talks, or published writing. Extract quotes and key ideas.

5. Personal website / blog: If they have one, read their About page and any articles they wrote.

WHAT TO EXTRACT (populate every field you can find evidence for):
- occupation: their current role and company
- short_description: a compelling one-line summary (write this yourself based on everything you found)
- speaking_style: describe HOW they communicate — formal/casual, use of jargon, storytelling vs data-driven — infer this from actual quotes you found
- personality_traits: list traits like "analytical", "empathetic", "direct" — infer from their public communication style and how people describe them
- work_experience: the COMPLETE history. Output ONE entry per distinct role. If the person held several titles at the same company over time (e.g. promotions), output a SEPARATE entry for EACH title, each with its OWN start_year and end_year — do NOT merge them into a single role. Capture the real start/end year for each (a role spanning a single year like 2023-2023 is usually wrong unless it truly lasted under a year).
- education: all degrees, institutions, years
- key_achievements: specific accomplishments with context (raised $X, built Y, won Z)
- areas_of_expertise: topics they speak/write about, skills they are known for
- contributions: things they created, led, or are credited with
- social_links: all URLs you found (LinkedIn, Twitter, website, etc.)

RULES:
- Preserve career progression: same-company promotions are distinct entries, not one merged role. Prefer more granular, accurate dates over collapsing.
- Only include information about {safe_name} specifically — not colleagues, co-founders, or similarly named people.
- Do NOT hallucinate. If you cannot find evidence for a field, leave it empty.
- speaking_style and personality_traits MUST be based on real quotes or observed communication patterns, not guessed.
- short_description should be written in third person and capture what makes this person distinctive."""

    logger.info("[Firecrawl] extracting profile for '%s' (linkedin_url=%s)", person_name, linkedin_url or "none")
    result = app.agent(
        schema=ProfileSchema,
        prompt=prompt,
        model="spark-1-pro",
        timeout=timeout,
    )

    data = result.data
    if hasattr(data, "model_dump"):
        profile = data.model_dump(mode="json")
    elif isinstance(data, dict):
        profile = data
    else:
        profile = json.loads(str(data)) if data else {}

    logger.info(
        "[Firecrawl] extraction complete for '%s': %d fields populated",
        person_name,
        sum(1 for v in profile.values() if v),
    )

    # ── Work-experience audit + optional guarded repair ──────────────
    issues = audit_work_experience(profile)
    if issues:
        logger.warning(
            "[Firecrawl] work_experience audit flagged %d issue(s) for '%s': %s",
            len(issues),
            person_name,
            issues,
        )
        profile["extraction_review"] = {"work_experience_issues": issues}

        repairable = any(
            i.startswith(("understated_tenure", "single_year_span", "date_inverted"))
            for i in issues
        )
        if repair and repairable:
            profile = _repair_work_experience(
                app, person_name, profile, issues, safe_linkedin_url, timeout
            )

    return profile


def _repair_work_experience(
    app: FirecrawlApp,
    person_name: str,
    profile: dict,
    issues: list[str],
    safe_linkedin_url: str | None,
    timeout: int,
) -> dict:
    """Guarded LLM re-extraction of work history to recover collapsed roles.

    Re-asks the agent specifically for the COMPLETE per-role work history, naming
    the companies flagged in ``issues`` and emphasizing that same-company
    progressions are separate dated entries. The repaired list only REPLACES the
    original when it recovered MORE entries (otherwise the original is kept).

    Fully resilient: any exception is logged and the ORIGINAL profile is returned
    unchanged — this never raises and never drops data.
    """
    try:
        original_work = profile.get("work_experience")
        original_count = len(original_work) if isinstance(original_work, list) else 0

        # Companies named in the flagged issues, to focus the re-extraction.
        flagged_companies = sorted(
            {
                m.group(1)
                for m in (re.search(r"'([^']+)'", i) for i in issues)
                if m
            }
        )
        # Company names originate from the LLM-extracted profile — sanitize each
        # before interpolating into the repair prompt (defense against injection
        # via a crafted company field on a public profile).
        safe_companies = [_sanitize_prompt_str(c, max_len=100) for c in flagged_companies]
        companies_hint = (
            f" Pay special attention to these companies where roles may have been merged or dates compressed: {', '.join(safe_companies)}."
            if safe_companies
            else ""
        )

        class WorkHistory(BaseModel):
            work_experience: list[WorkExperience] = Field(
                default_factory=list,
                description="Complete per-role work history",
            )

        safe_name = _sanitize_prompt_str(person_name)
        anchor = f"LinkedIn profile: {safe_linkedin_url}" if safe_linkedin_url else ""
        repair_prompt = f"""You previously extracted a work history for the person below, but it appears INCOMPLETE — some roles were merged or had compressed dates.

PERSON: {safe_name}
{anchor}

Re-extract the COMPLETE professional work history. Output ONE entry per distinct role.
If the person held several titles at the SAME company over time (promotions/title changes), output a SEPARATE entry for EACH title, each with its OWN accurate start_year and end_year. Do NOT merge a multi-role tenure into one entry. A role spanning a single year (e.g. 2023-2023) is usually wrong unless it truly lasted under a year.{companies_hint}

Only include real, verifiable roles for {safe_name} — do not hallucinate."""

        logger.info("[Firecrawl] attempting work_experience repair for '%s'", person_name)
        result = app.agent(
            schema=WorkHistory,
            prompt=repair_prompt,
            model="spark-1-pro",
            timeout=timeout,
        )

        data = result.data
        if hasattr(data, "model_dump"):
            repaired = data.model_dump(mode="json")
        elif isinstance(data, dict):
            repaired = data
        else:
            repaired = json.loads(str(data)) if data else {}

        repaired_work = repaired.get("work_experience") if isinstance(repaired, dict) else None
        if not isinstance(repaired_work, list):
            logger.info("[Firecrawl] repair returned no usable work_experience for '%s'", person_name)
            return profile

        # Only replace if the repair actually recovered MORE roles.
        if len(repaired_work) > original_count:
            logger.info(
                "[Firecrawl] repair recovered roles for '%s': %d -> %d entries",
                person_name,
                original_count,
                len(repaired_work),
            )
            profile["work_experience"] = repaired_work
            new_issues = audit_work_experience(profile)
            if new_issues:
                profile["extraction_review"] = {"work_experience_issues": new_issues}
            else:
                profile.pop("extraction_review", None)
        else:
            logger.info(
                "[Firecrawl] repair did not recover more roles for '%s' (%d <= %d); keeping original",
                person_name,
                len(repaired_work),
                original_count,
            )

        return profile
    except Exception:
        logger.exception("[Firecrawl] work_experience repair failed for '%s'; keeping original", person_name)
        return profile


def profile_to_text(profile: dict) -> str:
    """Convert a profile dict to a text representation for embedding.

    Produces a human-readable summary suitable for chunking and vector search.
    """
    parts = []

    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    if profile.get("occupation"):
        parts.append(f"Occupation: {profile['occupation']}")
    if profile.get("short_description"):
        parts.append(f"About: {profile['short_description']}")
    if profile.get("nationality"):
        parts.append(f"Nationality: {profile['nationality']}")
    if profile.get("speaking_style"):
        parts.append(f"Speaking style: {profile['speaking_style']}")

    traits = profile.get("personality_traits", [])
    if traits:
        parts.append(f"Personality traits: {', '.join(traits)}")

    expertise = profile.get("areas_of_expertise", [])
    if expertise:
        parts.append(f"Areas of expertise: {', '.join(expertise)}")

    achievements = profile.get("key_achievements", [])
    if achievements:
        parts.append("Key achievements:")
        for a in achievements:
            parts.append(f"  - {a}")

    contributions = profile.get("contributions", [])
    if contributions:
        parts.append("Notable contributions:")
        for c in contributions:
            parts.append(f"  - {c}")

    education = profile.get("education", [])
    if education:
        parts.append("Education:")
        for e in education:
            if isinstance(e, dict):
                line = f"  - {e.get('degree', '')} in {e.get('field', '')} at {e.get('institution', '')}"
                if e.get("end_year"):
                    line += f" ({e['end_year']})"
                parts.append(line)

    work = profile.get("work_experience", [])
    if work:
        parts.append("Work experience:")
        for w in work:
            if isinstance(w, dict):
                line = f"  - {w.get('role', '')} at {w.get('company', '')}"
                if w.get("start_year"):
                    years = f"{w['start_year']}"
                    if w.get("end_year"):
                        years += f"-{w['end_year']}"
                    else:
                        years += "-present"
                    line += f" ({years})"
                if w.get("description"):
                    line += f": {w['description']}"
                parts.append(line)

    return "\n".join(parts)
