"""SEO indexability gate — the single source of truth for whether a public
persona page is rich enough to be indexed by search engines / AI crawlers.

The gate keys on a **substantial bio**. Real personas reliably populate a bio
(Firecrawl-extracted, unique per person) but rarely populate
``areas_of_expertise`` / ``public_response_seeds`` in the public profile (and
seeds are stripped from the public response). A unique, multi-sentence bio is the
dependable substance signal — and because bios are unique per person, gating on
it does NOT create the scaled/near-duplicate content that Google penalizes.

``indexability_signals_from_settings`` still surfaces expertise/seeds so callers
(e.g. the future SEO watchdog) can use them as positive ranking signals, but the
gate itself requires only a substantive bio today.

Reused by (so the gate is defined once):
  - GET /handles/public            (sitemap enumeration)
  - GET /handles/{handle}/profile  (per-page noindex metadata for SSR)
  - the SEO/AEO watchdog agent (Track 1, future)

Signals are read from `twins.settings` (no extra DB calls) and mirror the sources
used by `build_public_profile_pack`, so the sitemap and the per-page metadata
agree on which pages are index-eligible.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# A substantive, unique bio is the substance bar. Tune with product. Conservative
# enough to exclude thin/empty profiles; achievable for real Firecrawl bios.
MIN_BIO_LENGTH = 200


def _coerce_dict(value: Any) -> dict[str, Any]:
    """Best-effort coerce settings sub-objects (which may be JSON strings)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def indexability_signals_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Extract the raw gate signals from a twin's ``settings`` (no DB calls).

    Mirrors the field resolution in ``build_public_profile_pack`` /
    ``normalize_public_profile`` so the gate agrees with what the public page
    actually renders.

    Bio resolution (P0.1 fix): the public page (``normalize_public_profile``)
    fills the rendered bio from the FIRST non-empty of
    ``public_profile.bio -> persona_profile.bio -> public_intro -> description
    -> short_description``. The gate previously took the first non-empty of a
    DIFFERENT order (``public_profile.bio -> public_intro -> short_description
    -> persona_profile.bio``), so a short tagline in an earlier-priority field
    (e.g. a one-line ``public_profile.bio`` or ``public_intro``) could shadow a
    long ``persona_profile.bio`` and wrongly force ``noindex`` on a page that
    actually renders the long bio — a false negative.

    Fix: consider EVERY bio field the page could render and key on the LONGEST
    one, so a substantive bio in any renderable field clears the gate regardless
    of field priority. The ``>= MIN_BIO_LENGTH`` bar (checked in
    :func:`compute_is_indexable`) still keeps thin/empty profiles out — a short
    tagline can no longer over-count, and it can no longer shadow a real bio.
    """
    settings = settings if isinstance(settings, dict) else {}
    public_profile = _coerce_dict(settings.get("public_profile"))
    persona_profile = _coerce_dict(settings.get("persona_profile"))

    # Every bio field the public page may surface for this persona. We take the
    # MAX-length candidate rather than first-non-empty so the gate reflects the
    # substantive content the page renders, not whichever tagline field happens
    # to sit first in priority order.
    bio_candidates = (
        public_profile.get("bio"),
        persona_profile.get("bio"),
        settings.get("public_intro"),
        settings.get("description"),
        public_profile.get("short_description"),
        persona_profile.get("short_description"),
    )
    bio = max(
        (str(candidate).strip() for candidate in bio_candidates if candidate),
        key=len,
        default="",
    )

    expertise = public_profile.get("areas_of_expertise")
    if not isinstance(expertise, list) or not expertise:
        alt = persona_profile.get("areas_of_expertise")
        expertise = alt if isinstance(alt, list) else []

    seeds = public_profile.get("public_response_seeds")
    if not isinstance(seeds, list):
        seeds = []

    return {
        "bio": bio,
        "areas_of_expertise": [e for e in expertise if str(e or "").strip()],
        "public_response_seeds": [s for s in seeds if s],
    }


def compute_is_indexable(signals: dict[str, Any]) -> bool:
    """Return True when a public profile has a substantive bio (>= MIN_BIO_LENGTH).

    ``signals`` must expose ``bio`` (str) — as produced by
    :func:`indexability_signals_from_settings` or a redacted public profile pack.
    Expertise/seeds are intentionally NOT required (they're rarely populated in
    real data); they remain available in the signals for future positive use.
    """
    bio = str(signals.get("bio") or "").strip()
    return len(bio) >= MIN_BIO_LENGTH


def is_twin_indexable(twin: dict[str, Any]) -> bool:
    """Convenience: compute the gate directly from a twin row's ``settings``."""
    settings = twin.get("settings") if isinstance(twin, dict) else {}
    return compute_is_indexable(indexability_signals_from_settings(settings or {}))
