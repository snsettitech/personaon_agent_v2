"""Sprint 1 Passport claim_type allowlist (PON-7 Approach B)."""

CLAIM_TYPES: frozenset[str] = frozenset({
    "full_name",
    "headline",
    "bio",
    "work_experience",
    "education",
    "skill",
    "project",
    "credential",
    "preference",
    "social_link",
})


def is_allowed_claim_type(claim_type: str) -> bool:
    return claim_type in CLAIM_TYPES
