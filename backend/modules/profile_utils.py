"""Text utilities, scoring helpers, and metadata builders for public profiles."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse


PUBLIC_PROFILE_META_VERSION = "1.0"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def auth_providers_from_user(user: Any) -> set[str]:
    """Return normalized auth providers present on the current user/session."""
    if not isinstance(user, dict):
        return set()

    app_metadata = _safe_dict(user.get("app_metadata"))
    providers: set[str] = set()

    raw_providers = app_metadata.get("providers")
    if isinstance(raw_providers, (list, tuple, set)):
        for provider in raw_providers:
            text = _clean_text(provider).lower()
            if text:
                providers.add(text)
    else:
        text = _clean_text(raw_providers).lower()
        if text:
            providers.add(text)

    primary_provider = _clean_text(app_metadata.get("provider")).lower()
    if primary_provider:
        providers.add(primary_provider)

    return providers


def user_has_linkedin_provider(user: Any) -> bool:
    """True when the live authenticated user still has a LinkedIn identity."""
    return bool(auth_providers_from_user(user) & {"linkedin", "linkedin_oidc"})


def _clean_unique_strings(values: Iterable[Any], *, limit: int = 6) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _first_sentence(text: Any) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)
    return parts[0].strip()


def _coerce_score_percent(value: Any) -> float:
    try:
        score = float(value or 0)
    except Exception:
        return 0.0
    if score <= 1.0:
        score *= 100.0
    return max(0.0, min(score, 100.0))


def _coerce_year(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        year_match = re.search(r"\b(18|19|20)\d{2}\b", text)
        if year_match:
            return int(year_match.group(0))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).year
        except Exception:
            return None
    return None


def _social_key_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "website"
    if "wikipedia.org" in host:
        return "wikipedia"
    if "linkedin.com" in host:
        return "linkedin"
    if "github.com" in host:
        return "github"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "x.com" in host or "twitter.com" in host:
        return "twitter"
    return "website"


def normalize_external_url(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    if text.startswith("//"):
        text = f"https:{text}"
    elif not re.match(r"^[a-z][a-z0-9+.-]*://", text, flags=re.IGNORECASE):
        text = f"https://{text}"

    try:
        parsed = urlparse(text)
    except Exception:
        return ""

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return ""

    netloc = (parsed.netloc or "").strip().lower()
    if not netloc:
        return ""
    # Reject bare words without a dot (e.g. "not-a-url" — not a real hostname)
    if "." not in netloc.split(":")[0]:
        return ""

    path = parsed.path or ""
    if path not in {"", "/"}:
        path = path.rstrip("/")

    query = parsed.query or ""
    if netloc in {"linkedin.com", "www.linkedin.com"}:
        netloc = "www.linkedin.com"
        query = ""

    normalized = urlunparse(
        (
            scheme,
            netloc,
            path,
            "",
            query,
            "",
        )
    )
    return normalized.strip()


def normalize_linkedin_profile_url(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    if text.startswith("/in/"):
        text = f"https://www.linkedin.com{text}"
    elif text.lower().startswith("linkedin.com/") or text.lower().startswith("www.linkedin.com/"):
        text = f"https://{text}"
    elif not re.match(r"^[a-z][a-z0-9+.-]*://", text, flags=re.IGNORECASE):
        slug = text.strip("/").replace("/in/", "").strip()
        if not slug:
            return ""
        text = f"https://www.linkedin.com/in/{slug}"

    try:
        parsed = urlparse(text)
    except Exception:
        return ""

    host = (parsed.netloc or "").lower().strip()
    if host not in {"linkedin.com", "www.linkedin.com"}:
        return ""
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return ""

    path = (parsed.path or "").rstrip("/")
    if not path.lower().startswith("/in/"):
        return ""

    slug = path[4:].strip("/")
    if not slug:
        return ""
    return f"https://www.linkedin.com/in/{slug}"


def is_synthesized_linkedin_url(profile_url: Any, provider_user_id: Any) -> bool:
    url = _clean_text(profile_url)
    opaque_id = _clean_text(provider_user_id)
    if not url or not opaque_id:
        return False
    return url == f"https://www.linkedin.com/in/{opaque_id}"


def select_best_linkedin_account(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def _score(row: dict[str, Any]) -> tuple[int, int, int]:
        provider = _clean_text(row.get("provider")).lower()
        snapshot = _safe_dict(row.get("profile_snapshot"))
        profile_url = normalize_linkedin_profile_url(snapshot.get("profile_url"))
        has_real_profile_url = bool(
            profile_url and not is_synthesized_linkedin_url(profile_url, row.get("provider_user_id"))
        )
        has_display_name = bool(_clean_text(snapshot.get("display_name")))
        return (
            1 if has_real_profile_url else 0,
            2 if provider == "linkedin_oidc" else 1,
            1 if has_display_name else 0,
        )

    return max(rows, key=_score)


def generate_contextual_questions(profile: dict[str, Any], *, limit: int = 4) -> list[str]:
    questions: list[str] = []

    occupation = _clean_text(profile.get("occupation") or profile.get("role"))
    organization = _clean_text(profile.get("organization"))
    if not occupation:
        role = _clean_text(profile.get("role"))
        headline = _clean_text(profile.get("headline"))
        occupation = role or headline
    if occupation and organization and organization.lower() not in occupation.lower():
        occupation = f"{occupation} at {organization}"

    work_experience = _safe_list(profile.get("work_experience"))
    key_achievements = _clean_unique_strings(profile.get("key_achievements") or [], limit=3)
    personality_traits = _clean_unique_strings(profile.get("personality_traits") or [], limit=3)
    expertise = _clean_unique_strings(profile.get("areas_of_expertise") or [], limit=3)

    if occupation:
        questions.append(f"What does your day-to-day look like as {occupation}?")

    for entry in work_experience:
        if not isinstance(entry, dict):
            continue
        company = _clean_text(entry.get("company"))
        if company:
            questions.append(f"What shaped the way you work during your time at {company}?")
            break

    if key_achievements:
        achievement = key_achievements[0]
        if len(achievement) <= 120:
            questions.append(f"How did you pull off {achievement}?")

    if personality_traits:
        trait = personality_traits[0].lower()
        article = "an" if trait[:1] in {"a", "e", "i", "o", "u"} else "a"
        questions.append(f"How does being {article} {trait} person show up in the way you lead or work?")

    if expertise:
        questions.append(f"What's your perspective on {expertise[0].lower()} right now?")

    fallbacks = [
        "What's the most important lesson from your career so far?",
        "What problems are you most motivated to solve?",
        "What do people often misunderstand about your work?",
    ]
    questions.extend(fallbacks)

    deduped: list[str] = []
    seen = set()
    for question in questions:
        cleaned = _clean_text(question)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def normalize_social_links(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        normalized: dict[str, str] = {}
        for key, url in value.items():
            cleaned_key = _clean_text(key).lower()
            cleaned_url = normalize_external_url(url)
            if not cleaned_key or not cleaned_url:
                continue
            normalized.setdefault(cleaned_key, cleaned_url)
        return normalized

    links: dict[str, str] = {}
    for raw in _safe_list(value):
        url = normalize_external_url(raw)
        if not url:
            continue
        key = _social_key_from_url(url)
        links.setdefault(key, url)
    return links


def _is_populated(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_is_populated(v) for v in value.values())
    if isinstance(value, list):
        return any(_is_populated(v) for v in value)
    return bool(_clean_text(value))


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_ratio(value: Any) -> float:
    try:
        score = float(value or 0.0)
    except Exception:
        return 0.0
    if score > 1.0:
        score /= 100.0
    return max(0.0, min(score, 1.0))


def _calculate_completeness_score(public_profile: dict[str, Any]) -> float:
    weighted_checks = [
        (_clean_text(public_profile.get("display_name")), 12),
        (_clean_text(public_profile.get("occupation")) or _clean_text(public_profile.get("role")), 10),
        (_clean_text(public_profile.get("headline")), 10),
        (_clean_text(public_profile.get("bio")), 12),
        (_clean_text(public_profile.get("short_description")), 10),
        (public_profile.get("areas_of_expertise"), 10),
        (public_profile.get("key_achievements"), 8),
        (public_profile.get("contributions"), 8),
        (public_profile.get("education"), 8),
        (public_profile.get("work_experience"), 8),
        (public_profile.get("social_links"), 7),
        (_clean_text(public_profile.get("image_url")) or _clean_text(public_profile.get("avatar_url")), 7),
    ]
    total = float(sum(weight for _value, weight in weighted_checks))
    if total <= 0:
        return 0.0
    earned = sum(weight for value, weight in weighted_checks if _is_populated(value))
    return round((earned / total) * 100.0, 1)


def _build_public_profile_meta(
    *,
    source_flow: str,
    materialized_at: str,
    public_profile: dict[str, Any],
    image_resolution: dict[str, Any],
    existing_meta: dict[str, Any],
) -> dict[str, Any]:
    from modules.profile_image import _image_source_tier

    image_status = _clean_text(image_resolution.get("status")).lower() or "missing"
    return {
        **existing_meta,
        "version": _clean_text(existing_meta.get("version")) or PUBLIC_PROFILE_META_VERSION,
        "source_flow": _clean_text(source_flow) or _clean_text(existing_meta.get("source_flow")) or "generated",
        "materialized_at": _clean_text(materialized_at) or _clean_text(existing_meta.get("materialized_at")) or _iso_now(),
        "completeness_score": _calculate_completeness_score(public_profile),
        "image_status": image_status if image_status in {"missing", "pending", "resolved", "rejected"} else "missing",
        "image_source_type": _clean_text(image_resolution.get("image_source_type"))
        or _clean_text(existing_meta.get("image_source_type")),
        "image_source_url": _clean_text(image_resolution.get("image_source_url"))
        or _clean_text(existing_meta.get("image_source_url")),
        "image_source_tier": _clean_text(image_resolution.get("image_source_tier"))
        or _clean_text(existing_meta.get("image_source_tier"))
        or _image_source_tier(
            _clean_text(image_resolution.get("image_source_type"))
            or _clean_text(existing_meta.get("image_source_type")),
            image_status,
        ),
    }
