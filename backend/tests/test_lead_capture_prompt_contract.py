"""PR6 STATIC layer — prompt-contract tests for the public_lead offer block, plus a
corpus well-formedness check. Deterministic; runs in CI (no LLM). The BEHAVIORAL
layer (the LLM run over the corpus) lives in backend/scripts/eval_lead_capture.py.

This is the "two-layer oracle": cheap static invariants here guard against prompt
regressions every commit; the eval script measures actual model behavior on demand.
"""
import json
from pathlib import Path

import pytest

from adk_core.services.prompts import generate_system_prompt

PROFILE = {"name": "Sainath", "bio": "founder"}
VALUE_FRAMES = ["opportunity", "lead", "inquiry", "collaboration", "interest"]
CORPUS = json.loads(
    (Path(__file__).parent / "fixtures" / "lead_capture_corpus.json").read_text(encoding="utf-8")
)


def _public_lead_prompt(value_frame="lead", offer_state="not_yet_offered", email=None):
    ctx = {
        "lead_capture_enabled": True, "offer_state": offer_state, "turn_count": 1,
        "value_frame": value_frame, "persona_name": "Sainath",
    }
    if email:
        ctx["email"] = email
    return generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=ctx)


# ── Invariants present on every public_lead offer prompt ──────────────────────

@pytest.mark.parametrize("value_frame", VALUE_FRAMES)
def test_public_lead_invariants_hold_for_every_frame(value_frame):
    p = _public_lead_prompt(value_frame=value_frame)
    lower = p.lower()
    # Semantic placement, not bare keyword presence — these would fail if a rule were
    # inverted (e.g. moved from a negative directive into a positive example).
    assert "never state your inference as fact" in lower  # anti-creepy (P1)
    assert "is forbidden" in lower                         # P1, the identity-assertion ban
    assert "pass that to Sainath" in p                     # consent disclosure (P3)
    assert "never imply a newsletter" in lower             # never newsletter/marketing
    assert "never gate information behind" in lower        # answer-first (info not gated)
    assert "no turn-count gate" in lower                   # intent-gated, no turn floor (D9)
    assert "capture_lead_contact" in p                     # capture tool wired


_FRAME_MARKERS = {
    "opportunity": "as an OPPORTUNITY",
    "lead": "conversation about working together",
    "inquiry": "qualified inquiry",
    "collaboration": "collaboration, partnership",
    "interest": "owner follow up",
}


@pytest.mark.parametrize("value_frame,marker", list(_FRAME_MARKERS.items()))
def test_value_frame_copy_is_selected(value_frame, marker):
    assert marker in _public_lead_prompt(value_frame=value_frame)


def test_offer_state_blocks():
    assert "Do NOT offer again" in _public_lead_prompt(offer_state="already_offered")
    captured = _public_lead_prompt(offer_state="email_captured", email="jo@fund.vc")
    assert "Email already captured" in captured
    assert "jo@fund.vc" in captured


def test_capture_off_public_path_has_no_offer():
    # capture OFF -> public maps to the "visitor" class -> none of the capture wiring
    p = generate_system_prompt(PROFILE, surface_class="visitor")
    assert "capture_lead_contact" not in p
    assert "NO turn-count gate" not in p


# ── Corpus well-formedness (validate the eval data itself) ────────────────────

def test_corpus_has_all_categories_and_frames():
    fixtures = CORPUS["fixtures"]
    assert len(fixtures) == 29  # exact: any change to corpus size forces a deliberate update
    assert {f["category"] for f in fixtures} == {
        "intent_offer", "small_talk", "declared_context", "adversarial_identity", "decline_repeat",
    }
    assert {f["value_frame"] for f in fixtures} == set(VALUE_FRAMES)


def test_corpus_expects_offer_consistent_with_category():
    for f in CORPUS["fixtures"]:
        # small talk never offers; an already-captured email or a prior offer never (re-)offers
        if f["category"] == "small_talk" or f["email_already_captured"] or f["prior_offered"]:
            assert f["expects_offer"] is False, f["id"]


def test_corpus_fixtures_are_shaped_and_adversarial_have_guards():
    required = {"id", "category", "value_frame", "prior_offered", "email_already_captured",
                "expects_offer", "visitor_message", "must_not_say"}
    for f in CORPUS["fixtures"]:
        assert required <= set(f), f.get("id")
        assert isinstance(f["must_not_say"], list)
        assert f["visitor_message"].strip()
        if f["category"] == "adversarial_identity":
            assert f["must_not_say"], f["id"]  # forbidden identity/source assertions listed
