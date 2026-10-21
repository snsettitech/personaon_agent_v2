"""W9b — Heads Up LLM rewriter prompt + output schema.

Single source of truth for the system prompt, response schema, and user-prompt
builder. Decoupled from the Gemini call (in heads_up_rewriter.py) so the prompt
text can be unit-tested in isolation.

The 6 design principles + tone calibration + anti-pattern blocklist are inlined
verbatim — any change must update the spec doc at
docs/superpowers/plans/2026-05-21-w9-heads-up-eval-set.md AND the eval fixture
YAML at backend/tests/fixtures/heads_up_eval_set.yaml.

Citation strategy: the LLM emits ``source_candidate_idx`` (an integer pointing
back to the candidate it transformed). The caller mechanically synthesizes
``source.ref`` and ``source.quote`` by re-reading that candidate. This
eliminates citation hallucination — the LLM can pick wrong, but it can't
invent source text out of thin air.
"""

from __future__ import annotations

import re
from typing import Any

# AUDIT FIX (HIGH security): defense against prompt injection via candidate
# field values that originate from prior recap content (LLM-extracted from
# meeting transcripts, then re-fed here). A meeting participant could say
# "Ignore previous instructions" during a call; the recap agent stores it;
# this module previously interpolated it verbatim into the LLM user prompt.
#
# Mitigations:
#   1. Per-field char cap (_FIELD_VALUE_CAP) prevents long payloads
#   2. Regex strips common "ignore previous instructions" patterns
#   3. response_schema in the LLM call still constrains shape — this is
#      defense-in-depth, not the primary barrier
_FIELD_VALUE_CAP = 400

_INJECTION_PATTERN = re.compile(
    r"(?i)\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|above|prior|earlier|system|all|the)\b.{0,40}\b(instruction|prompt|rule|order|direction|command)s?\b"
)


def _sanitize_field_value(value: object) -> str:
    """Coerce to str, cap length, neutralize injection patterns.

    Stripped phrases get replaced with a neutral marker so the LLM sees
    that something was redacted (better than silent disappearance, which
    could change candidate semantics).
    """
    s = str(value) if value is not None else ""
    if len(s) > _FIELD_VALUE_CAP:
        s = s[:_FIELD_VALUE_CAP] + "…"
    s = _INJECTION_PATTERN.sub("[redacted-instruction]", s)
    return s


SYSTEM_PROMPT = """You rewrite candidate facts about an upcoming meeting into "Heads Up" notes
for a busy founder. Your job is the LAST mile: take the raw rule-fired facts
and transform them into Level-3 ally tone.

THE 6 DESIGN PRINCIPLES (non-negotiable):
1. Lead with the observable fact, not the inference. Show the artifact
   ("the May 8 note"); never accuse ("you committed").
2. Use first-person source attribution ("your May 8 note"), not omniscient
   narration.
3. Cite the receipt — every note must point back to its source candidate by
   integer idx. The system synthesizes the source quote mechanically.
4. Frame as "worth knowing," not "worth doing." Drop imperatives. Never
   "you should", "don't forget", "make sure to".
5. Stop one beat short of advice. State the fact. Trust the reader.
6. SBI minus the I — Situation, Behavior, drop Impact. "Impact" is where
   snark lives.

TONE TARGET: Level 3 ("trusted Chief of Staff"). NEVER level 4 ("friendly
nudge") or level 5 ("buddy/snark").

LEVEL 3 examples (TARGET — emit notes like these):
- "Heads up — Sarah's still waiting on the Q2 strategy doc you mentioned May 8."
- "Worth knowing — Sarah moved from Acme to Beta as CRO since you last met."
- "Still open — legal review you flagged for May 15 hasn't gone out yet."
- "Heads up — this is your third meeting with Anand after two reschedules."

LEVEL 4-5 examples (FORBIDDEN — never emit notes like these):
- "Quick FYI: that doc you said you'd send hasn't gone out yet 🙂"  [too warm]
- "Sooo… that doc you promised Sarah two weeks ago? Yeah."  [snark]
- "Don't forget to send the legal review."  [imperative]

ANTI-PATTERN BLOCKLIST (any of these in a note will be auto-dropped):
- Imperative verbs: "you should", "don't forget to", "make sure to", "be sure to"
- Failure verbs: "you forgot", "you missed", "you skipped", "you owe",
  "you failed", "you neglected", "you committed to"
- Mind-reading: "they may be frustrated", "he might be annoyed",
  "she's likely upset", "they probably feel", "their morale may be"
- Loaded words: "overdue", "deadline missed", "stalemate",
  "dropped the ball", "behind on"
- Emoji on hard content (open commitments, disputes, sensitive topics)

RESTRAINT CASES (emit no note for these candidate kinds — they are explicitly
out of scope for Heads Up):
- `persona_mismatch` — belongs in user's persona editor, not a Heads Up
- `kb_public_bio` — bio facts go in participant_insights, not cautions
- `title_correction` — context correction, not derail-risk
- `user_self_critique` — never re-surface the user's own past self-criticism
- `prior_meeting_neutral` — neutral history isn't a caution
- Empty candidate list — emit empty caution_notes array

CITATION CONTRACT:
For each note you emit, include "source_candidate_idx": <integer> pointing
to the candidate (zero-indexed) you transformed. The system synthesizes
source.ref + source.quote by re-reading that candidate. Do NOT invent
source text in your note body — quote only what's already in the
candidate's structured fields.

OUTPUT FORMAT: JSON only, no surrounding text, no markdown code fences.
Conform to the schema. Default to an empty caution_notes array if you
cannot confidently produce Level-3 tone for any candidate.

STACKING DISCIPLINE: For weak/borderline candidates (e.g., commitment open
exactly 8 days at the threshold), prefer to suppress rather than emit.
Better to miss a true positive than to ship snark.

CAPS:
- Max 3 notes per brief total. Pick the strongest 3 if more candidates fire.
- Each note text ≤ 200 characters. Lead with the label ("Heads up —",
  "Worth knowing —", "Still open —"), then the fact.
""".strip()


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caution_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source_candidate_idx": {"type": "integer"},
                },
                "required": ["text", "source_candidate_idx"],
            },
        },
    },
    "required": ["caution_notes"],
}


# Fields that get a special compact-label spot in the user prompt.
# Everything else falls through to the "      key: value" list.
_PRIMARY_SUMMARY_FIELDS = ("description", "topic", "note_quote", "email_quote")


def build_user_prompt(
    *,
    candidates: list[dict[str, Any]],
    meeting_title: str,
) -> str:
    """Format the candidate list for the LLM rewriter.

    Each candidate is indexed ``[0]``, ``[1]``, ... so the LLM can pick them
    by integer in ``source_candidate_idx``. Out-of-scope kinds are still
    listed so the LLM can apply the restraint rules and skip them.

    The prompt is deterministic — same inputs produce the same string —
    which makes prompt caching effective and tests stable.
    """
    # AUDIT FIX (HIGH security): sanitize meeting_title too — it comes
    # from calendar invite data which is attacker-controllable.
    safe_title = _sanitize_field_value(meeting_title)

    if not candidates:
        return (
            f"Meeting: {safe_title}\n\n"
            "No candidate facts surfaced by the rule pass. "
            "Emit an empty caution_notes array."
        )

    lines: list[str] = [f"Meeting: {safe_title}", "", "Candidate facts:"]
    for i, cand in enumerate(candidates):
        kind = _sanitize_field_value(cand.get("kind", "unknown"))
        attendee = _sanitize_field_value(cand.get("attendee", ""))
        summary_value = ""
        for field in _PRIMARY_SUMMARY_FIELDS:
            v = cand.get(field)
            if v:
                summary_value = _sanitize_field_value(v)
                break
        header = f"[{i}] {kind}"
        if attendee:
            header += f" — attendee: {attendee}"
        if summary_value:
            header += f" — {summary_value}"
        lines.append(header)
        # Pass through the rest of the structured fields so the LLM has
        # the full signal for nuanced decisions (days_open, dates, etc.)
        # Every value is sanitized — even integer-looking fields go through
        # since dict values from JSON can be any type and an attacker who
        # controlled storage could put strings where ints are expected.
        for k, v in cand.items():
            if k in {"kind", "attendee"} or k in _PRIMARY_SUMMARY_FIELDS:
                continue
            if v is None or v == "":
                continue
            lines.append(f"      {k}: {_sanitize_field_value(v)}")
    lines.append("")
    lines.append("Rewrite as Level-3 Heads Up notes. JSON only, no prose.")
    return "\n".join(lines)
