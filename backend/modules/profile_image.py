"""Image resolution and HTTP fetch primitives for public profiles."""
from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from modules.profile_utils import (
    _clean_text,
    _coerce_ratio,
    _safe_dict,
    _safe_list,
)

OWNER_LOCKED_IMAGE_SOURCE_TYPES = {"owner_uploaded", "oauth"}


# ---------------------------------------------------------------------------
# HTTP primitives
# ---------------------------------------------------------------------------

def _request_url(url: str, *, accept: str, timeout: float = 4.0):
    return Request(
        url,
        headers={
            "User-Agent": "VerifiedDigitalTwinBrain/1.0",
            "Accept": accept,
        },
    )


def _fetch_remote_text(url: str, *, timeout: float = 4.0, max_bytes: int = 160000) -> str:
    normalized_url = _clean_text(url)
    if not normalized_url.startswith(("http://", "https://")):
        return ""
    try:
        request = _request_url(normalized_url, accept="text/html,application/xhtml+xml")
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes)
            return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _fetch_remote_json(url: str, *, timeout: float = 4.0) -> dict[str, Any]:
    normalized_url = _clean_text(url)
    if not normalized_url.startswith(("http://", "https://")):
        return {}
    try:
        request = _request_url(normalized_url, accept="application/json")
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(250000).decode("utf-8", errors="ignore")
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _clean_host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().strip()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


# ---------------------------------------------------------------------------
# Image URL inspection
# ---------------------------------------------------------------------------

def _looks_like_image_url(url: Any) -> bool:
    normalized = _clean_text(url).lower()
    if not normalized:
        return False
    image_markers = (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".avif",
        ".gif",
        "upload.wikimedia.org",
        "media.licdn.com/dms/image",
        "/photo/",
        "/images/",
        "/headshot",
        "/portrait",
    )
    return any(marker in normalized for marker in image_markers)


def _looks_like_logo_url(url: Any) -> bool:
    normalized = _clean_text(url).lower()
    if not normalized:
        return False
    return any(token in normalized for token in ("logo", "favicon", "icon", "apple-touch"))


# ---------------------------------------------------------------------------
# Host matching helpers
# ---------------------------------------------------------------------------

def _host_matches(expected_hosts: list[str], url: str) -> bool:
    host = _clean_host(url)
    if not host:
        return False
    for expected in expected_hosts:
        if not expected:
            continue
        if host == expected or host.endswith("." + expected) or expected.endswith("." + host):
            return True
    return False


def _official_host_candidates(result: dict[str, Any]) -> list[str]:
    input_data = _safe_dict(result.get("input"))
    hints = _safe_dict(input_data.get("hints"))
    hosts = []
    for raw_url in (
        hints.get("website"),
        hints.get("official_website"),
        hints.get("organization_website"),
    ):
        host = _clean_host(_clean_text(raw_url))
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _is_official_source(url: str, source: dict[str, Any], official_hosts: list[str]) -> bool:
    host = _clean_host(url)
    if not host:
        return False
    if _host_matches(official_hosts, url):
        return True
    source_type = _clean_text(source.get("source_type")).lower()
    return source_type in {"profile", "website"} and (
        host.endswith(".gov")
        or host.endswith(".gov.in")
        or host.endswith(".edu")
        or host.endswith(".edu.in")
        or host.endswith(".org")
    )


# ---------------------------------------------------------------------------
# Meta-image extraction & Wikipedia
# ---------------------------------------------------------------------------

def _extract_meta_image(html_text: str, page_url: str) -> str:
    if not html_text:
        return ""
    patterns = (
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if not match:
            continue
        candidate = html_lib.unescape(_clean_text(match.group(1)))
        if not candidate:
            continue
        candidate = urljoin(page_url, candidate)
        if _looks_like_image_url(candidate) and not _looks_like_logo_url(candidate):
            return candidate
    return ""


def _wikipedia_summary_api_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    if "wikipedia.org" not in parsed.netloc.lower():
        return ""
    if "/wiki/" not in parsed.path:
        return ""
    page_title = parsed.path.split("/wiki/", 1)[1].strip("/")
    if not page_title:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/api/rest_v1/page/summary/{quote(page_title)}"


def _fetch_wikipedia_thumbnail(page_url: str) -> str:
    api_url = _wikipedia_summary_api_url(page_url)
    if not api_url:
        return ""
    summary = _fetch_remote_json(api_url)
    thumbnail = _safe_dict(summary.get("thumbnail"))
    source = _clean_text(thumbnail.get("source"))
    return source if _looks_like_image_url(source) and not _looks_like_logo_url(source) else ""


# ---------------------------------------------------------------------------
# Image candidate building & prioritization
# ---------------------------------------------------------------------------

def _build_image_candidate(
    *,
    url: str,
    source_type: str,
    source_url: str,
    confidence: Any,
) -> dict[str, Any] | None:
    image_url = _clean_text(url)
    if not _looks_like_image_url(image_url) or _looks_like_logo_url(image_url):
        return None
    return {
        "url": image_url,
        "source_type": _clean_text(source_type).lower() or "generic_public",
        "source_url": _clean_text(source_url),
        "confidence": round(_coerce_ratio(confidence), 3),
    }


def _candidate_priority(candidate: dict[str, Any]) -> float:
    priority_map = {
        "owner_uploaded": 1.0,
        "oauth": 0.98,
        "official_profile": 0.9,
        "wikipedia": 0.82,
        "direct_public_image": 0.72,
        "generic_public": 0.64,
        "linkedin_public": 0.55,
        "existing": 0.45,
    }
    source_type = _clean_text(candidate.get("source_type")).lower()
    confidence = _coerce_ratio(candidate.get("confidence"))
    return priority_map.get(source_type, 0.4) + confidence


def _image_source_tier(source_type: str, status: str) -> str:
    normalized_type = _clean_text(source_type).lower()
    normalized_status = _clean_text(status).lower()
    if normalized_status != "resolved":
        return "rejected" if normalized_status == "rejected" else "missing"
    if normalized_type in {"owner_uploaded", "oauth"}:
        return "owner"
    if normalized_type == "official_profile":
        return "official"
    if normalized_type in {"wikipedia", "direct_public_image", "existing"}:
        return "reference"
    if normalized_type in {"generic_public", "linkedin_public"}:
        return "generic"
    return "reference"


# ---------------------------------------------------------------------------
# Main image resolver
# ---------------------------------------------------------------------------

def _resolve_profile_image(
    result: dict[str, Any],
    existing_public_profile: dict[str, Any],
    existing_meta: dict[str, Any],
) -> dict[str, Any]:
    existing_image_url = (
        _clean_text(existing_public_profile.get("image_url"))
        or _clean_text(existing_public_profile.get("avatar_url"))
    )
    existing_source_type = _clean_text(existing_meta.get("image_source_type")).lower()
    existing_confidence = _coerce_ratio(existing_meta.get("image_confidence") or 0.9)
    if existing_image_url and existing_source_type in OWNER_LOCKED_IMAGE_SOURCE_TYPES:
        return {
            "status": "resolved",
            "image_url": existing_image_url,
            "image_source_type": existing_source_type,
            "image_source_url": _clean_text(existing_meta.get("image_source_url")) or existing_image_url,
            "image_source_tier": _clean_text(existing_meta.get("image_source_tier"))
            or _image_source_tier(existing_source_type, "resolved"),
        }

    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(candidate: dict[str, Any] | None) -> None:
        if not candidate:
            return
        key = str(candidate.get("url") or "").lower()
        if not key:
            return
        current = candidates.get(key)
        if current is None or _candidate_priority(candidate) > _candidate_priority(current):
            candidates[key] = candidate

    if existing_image_url:
        add_candidate(
            _build_image_candidate(
                url=existing_image_url,
                source_type=existing_source_type or "existing",
                source_url=_clean_text(existing_meta.get("image_source_url")) or existing_image_url,
                confidence=existing_confidence or 0.6,
            )
        )

    input_data = _safe_dict(result.get("input"))
    hints = _safe_dict(input_data.get("hints"))
    for hint_key in ("image_url", "avatar_url", "profile_image_url", "photo_url", "headshot_url"):
        hint_image = _clean_text(hints.get(hint_key))
        if not hint_image:
            continue
        add_candidate(
            _build_image_candidate(
                url=hint_image,
                source_type="direct_public_image",
                source_url=hint_image,
                confidence=0.9,
            )
        )

    official_hosts = _official_host_candidates(result)
    sorted_sources = sorted(
        _safe_list(result.get("sources")),
        key=lambda row: (
            not bool(_safe_dict(row).get("used_in_final")),
            -float(_safe_dict(row).get("identity_match_confidence") or 0.0),
        ),
    )

    for raw_source in sorted_sources:
        source = _safe_dict(raw_source)
        source_url = _clean_text(source.get("url"))
        if not source_url:
            continue
        source_type = _clean_text(source.get("source_type")).lower()
        confidence = float(source.get("identity_match_confidence") or 0.0)

        if _looks_like_image_url(source_url):
            resolved_type = "direct_public_image"
            if _is_official_source(source_url, source, official_hosts):
                resolved_type = "official_profile"
            elif "linkedin.com" in _clean_host(source_url):
                resolved_type = "linkedin_public"
            add_candidate(
                _build_image_candidate(
                    url=source_url,
                    source_type=resolved_type,
                    source_url=source_url,
                    confidence=max(confidence, 0.75),
                )
            )
            continue

        if "linkedin.com" in _clean_host(source_url):
            continue

        if "wikipedia.org" in _clean_host(source_url):
            thumbnail = _fetch_wikipedia_thumbnail(source_url)
            add_candidate(
                _build_image_candidate(
                    url=thumbnail,
                    source_type="wikipedia",
                    source_url=source_url,
                    confidence=max(confidence, 0.8),
                )
            )
            continue

        if source_type not in {"website", "profile"}:
            continue

        if not source.get("used_in_final") and confidence < 0.65:
            continue

        html_text = _fetch_remote_text(source_url)
        image_url = _extract_meta_image(html_text, source_url)
        if not image_url:
            continue
        resolved_type = "official_profile" if _is_official_source(source_url, source, official_hosts) else "generic_public"
        minimum_confidence = 0.55 if resolved_type == "official_profile" else 0.7
        if confidence < minimum_confidence and not source.get("used_in_final"):
            continue
        add_candidate(
            _build_image_candidate(
                url=image_url,
                source_type=resolved_type,
                source_url=source_url,
                confidence=max(confidence, minimum_confidence),
            )
        )

    if not candidates:
        return {
            "status": "resolved" if existing_image_url else "missing",
            "image_url": existing_image_url,
            "image_source_type": existing_source_type,
            "image_source_url": _clean_text(existing_meta.get("image_source_url")),
            "image_source_tier": _clean_text(existing_meta.get("image_source_tier"))
            or _image_source_tier(existing_source_type, "resolved" if existing_image_url else "missing"),
        }

    best = max(candidates.values(), key=_candidate_priority)
    return {
        "status": "resolved",
        "image_url": _clean_text(best.get("url")),
        "image_source_type": _clean_text(best.get("source_type")).lower(),
        "image_source_url": _clean_text(best.get("source_url")),
        "image_source_tier": _image_source_tier(_clean_text(best.get("source_type")).lower(), "resolved"),
    }
