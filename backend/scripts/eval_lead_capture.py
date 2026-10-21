"""PR6 BEHAVIORAL layer — run the public lead-capture fixture corpus through the model
and score it. The static prompt-contract tests (test_lead_capture_prompt_contract.py)
run every commit in CI; THIS is the on-demand behavioral eval (needs a model + key).

For each fixture it builds the real public_lead system prompt (generate_system_prompt)
+ the visitor message, calls the model once, and checks:
  - offer fired? (heuristic _looks_like_offer, the same signal the backend uses) ==
    fixture.expects_offer
  - the response contains NONE of fixture.must_not_say (identity/source assertions,
    newsletter framing, illegal re-offers, info-gating)
A fixture passes only if BOTH hold. Reports per-category + overall pass rate.

Usage (from backend/):
    EVAL_MODEL=gemini/gemini-2.5-flash GEMINI_API_KEY=... python scripts/eval_lead_capture.py
    python scripts/eval_lead_capture.py --threshold 0.9 --limit 5

Gated: if litellm or an API key is unavailable it prints a skip and exits 0, so it is
safe to wire into an optional CI job without breaking the build.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make the backend package importable whether run from backend/ or the repo root.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from adk_core.services.prompts import generate_system_prompt  # noqa: E402
from routers.chat import _looks_like_offer  # noqa: E402  (reuse the backend's offer signal)

CORPUS_PATH = _BACKEND / "tests" / "fixtures" / "lead_capture_corpus.json"
DEFAULT_MODEL = os.getenv("EVAL_MODEL", "gemini/gemini-2.5-flash")
PROFILE = {
    "name": "Sainath",
    "bio": "Founder building PersonaOn; backend + AI product experience.",
    "occupation": "Founder",
}


def _offer_state(fixture: dict) -> str:
    if fixture.get("email_already_captured"):
        return "email_captured"
    if fixture.get("prior_offered"):
        return "already_offered"
    return "not_yet_offered"


def _build_prompt(fixture: dict) -> str:
    ctx = {
        "lead_capture_enabled": True,
        "offer_state": _offer_state(fixture),
        "turn_count": 2 if fixture.get("prior_offered") else 1,
        "value_frame": fixture["value_frame"],
        "persona_name": PROFILE["name"],
    }
    if fixture.get("email_already_captured"):
        ctx["email"] = "known@example.com"
    return generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=ctx)


def _has_key() -> bool:
    return any(os.getenv(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"))


def _call_model(model: str, system_prompt: str, user_message: str) -> str:
    import litellm  # imported lazily so the script can skip cleanly when absent

    # No explicit temperature — mirror production (agent_service sets none, so the
    # model's default sampling is used). Keeps the eval representative of live behavior
    # rather than a different (e.g. lower-variance) configuration.
    resp = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return resp["choices"][0]["message"]["content"] or ""


def evaluate(model: str, threshold: float, limit: int | None) -> int:
    fixtures = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))["fixtures"]
    if limit:
        fixtures = fixtures[:limit]

    by_cat: dict[str, list[bool]] = defaultdict(list)
    failures: list[str] = []

    for f in fixtures:
        prompt = _build_prompt(f)
        try:
            response = _call_model(model, prompt, f["visitor_message"])
        except Exception as exc:  # network/model error — count as a hard failure
            # Print only the exception TYPE, never its message (avoid any chance of a
            # key/URL fragment from a provider auth error landing in CI output).
            print(f"[ERROR] {f['id']}: model call failed ({type(exc).__name__})")
            by_cat[f["category"]].append(False)
            failures.append(f"{f['id']}: model error")
            continue

        offered = _looks_like_offer(response)
        offer_ok = offered == bool(f["expects_offer"])
        violations = [m for m in f["must_not_say"] if m.lower() in response.lower()]
        ok = offer_ok and not violations
        by_cat[f["category"]].append(ok)
        if not ok:
            why = []
            if not offer_ok:
                why.append(f"offer={offered} expected={f['expects_offer']}")
            if violations:
                why.append(f"said forbidden: {violations}")
            failures.append(f"{f['id']}: {'; '.join(why)}")

    total = [r for rs in by_cat.values() for r in rs]
    rate = sum(total) / len(total) if total else 0.0

    print("\n=== Lead-capture behavioral eval ===")
    print(f"model={model}  fixtures={len(total)}")
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        print(f"  {cat:22s} {sum(rs)}/{len(rs)}")
    print(f"OVERALL: {sum(total)}/{len(total)} = {rate:.0%}  (threshold {threshold:.0%})")
    if failures:
        print("\nFailures:")
        for line in failures:
            print(f"  - {line}")
    return 0 if rate >= threshold else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Behavioral eval for public lead-capture")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--threshold", type=float, default=0.9)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    try:
        import litellm  # noqa: F401
    except Exception:
        print("[skip] litellm not installed — behavioral eval skipped (static contract tests still run).")
        return 0
    if not _has_key():
        print("[skip] no model API key in env (GEMINI_API_KEY/GOOGLE_API_KEY/...) — behavioral eval skipped.")
        return 0
    if not CORPUS_PATH.exists():
        print(f"[skip] corpus not found: {CORPUS_PATH}")
        return 0

    return evaluate(args.model, args.threshold, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
