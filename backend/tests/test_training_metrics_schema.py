"""Schema regression tests for ``compute_training_metrics``.

Why this file
-------------
Production hit a bug where ``compute_training_metrics`` returned
``_source_count=0, mind_score=0`` and the cryptic note
``"Error computing metrics: 23"`` for every twin created after the
``sources`` table was simplified to ``(id, twin_id, filename, file_url,
content_text)``. The function selected legacy columns (``status``,
``citation_url``, ``extracted_text_length``, ``created_at``) that no longer
exist on production, the SELECT raised 42703, the bare ``except`` swallowed
it, and the API was happy to ship zero metrics.

These tests use the schema-aware ``FakeSupabase`` from PR #42, which mimics
production by raising :class:`Postgres42703Error` when code touches a
non-existent column. They would have caught the original regression at
test time.

The same bug class previously hit ``twins.user_id`` (PR #27); same template
applies here.
"""
from __future__ import annotations

from unittest.mock import patch

from tests._fake_supabase import FakeSupabase, PRODUCTION_SCHEMA


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------


def test_sources_schema_does_not_include_legacy_columns() -> None:
    """The exact assertion that would have prevented the original bug.

    The legacy migrations add ``status``, ``citation_url``,
    ``extracted_text_length``, and ``created_at`` to the ``sources`` table,
    but production has been simplified. Any code that selects these
    columns will 42703 in prod. Lock the snapshot.
    """
    sources_schema = PRODUCTION_SCHEMA["sources"]
    assert "id" in sources_schema
    assert "twin_id" in sources_schema
    assert "filename" in sources_schema
    assert "file_url" in sources_schema
    assert "content_text" in sources_schema

    # These columns are referenced by stale code paths and must NOT be
    # selected from `sources` in production code.
    for legacy in ("status", "citation_url", "extracted_text_length", "created_at"):
        assert legacy not in sources_schema, (
            f"sources.{legacy} is a legacy migration column that does not "
            f"exist on production. Selecting it raises 42703."
        )


# ---------------------------------------------------------------------------
# compute_training_metrics — the regression
# ---------------------------------------------------------------------------


def _make_content_text(num_words: int) -> str:
    """Generate ``num_words`` whitespace-separated dummy words."""
    return " ".join(f"word{i}" for i in range(num_words))


def test_compute_training_metrics_against_production_schema() -> None:
    """Reproduces the production bug for nikhiltambib@gmail.com.

    Before the fix: the SELECT touched legacy columns, raised 42703,
    the outer except swallowed it, and metrics came back all zeroes.
    After the fix: the SELECT only references columns that exist, so a
    twin with one valid source row computes a non-zero mind_score.
    """
    sb = FakeSupabase()
    twin_id = "b15fae0a-bf30-4f13-a99e-4e503e6462b0"

    sb.table("twins").set_row(
        id=twin_id,
        name="Nikhil Tambi",
        settings={
            "owner_user_id": "user-nikhil",
            # Persona profile present (research succeeded). The metrics
            # function does not read these, but their presence proves
            # the twin was fully populated when metrics ran.
            "persona_profile": {
                "areas_of_expertise": ["product management", "fintech"],
                "education": [{"school": "IIT", "degree": "B.Tech"}],
            },
        },
        status="active",
    )
    sb.table("sources").set_row(
        id="src-1",
        twin_id=twin_id,
        filename="Profile.md",
        file_url="https://example.com/profile.md",
        # 600 words ~= "Developing"-tier volume + "live"-by-presence
        content_text=_make_content_text(600),
    )

    from modules import training_metrics
    with patch.object(training_metrics, "supabase", sb):
        result = training_metrics.compute_training_metrics(twin_id)

    # Source row was actually counted (the symptom was _source_count=0)
    assert result.source_count >= 1, (
        f"compute_training_metrics returned source_count={result.source_count}; "
        f"expected >= 1 for a twin with 1 valid source row. Likely the "
        f"SELECT references a column that does not exist on the production "
        f"sources schema (regression of the legacy-columns bug)."
    )
    # Words came through (the symptom was words_processed=0)
    assert result.words_processed >= 500, (
        f"words_processed={result.words_processed}; expected ~600 from "
        f"the 600-word source row."
    )
    # Mind score is non-zero (the symptom was mind_score=0)
    assert result.mind_score > 0, (
        f"mind_score={result.mind_score}; expected > 0 once volume + "
        f"diversity + quality components fire."
    )
    # And the cryptic error note is gone
    assert "Error" not in result.notes, (
        f"notes={result.notes!r}; expected the happy-path note. The "
        f"original regression set this to 'Error computing metrics: 23'."
    )


def test_compute_training_metrics_no_sources_returns_clean_zeros() -> None:
    """Twin with zero sources should return zeros *without* an error note.

    Distinguishes "legitimately empty" from "errored out", which the
    original bug conflated (both came back as zeros + Error in notes).
    """
    sb = FakeSupabase()
    twin_id = "twin-empty"
    sb.table("twins").set_row(
        id=twin_id,
        name="Empty Twin",
        settings={"owner_user_id": "user-x"},
        status="active",
    )
    # No sources rows added.

    from modules import training_metrics
    with patch.object(training_metrics, "supabase", sb):
        result = training_metrics.compute_training_metrics(twin_id)

    assert result.source_count == 0
    assert result.words_processed == 0
    assert result.mind_score == 0
    # Empty != errored — notes should NOT mention an error
    assert "Error" not in result.notes
