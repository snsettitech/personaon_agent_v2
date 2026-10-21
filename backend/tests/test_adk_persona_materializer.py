from adk_core.schemas.artifacts import (
    ResearchArtifact,
    ResearchClaim,
    ResearchQuoteCandidate,
    ResearchSource,
    ResearchTimelineItem,
)
from adk_core.services.persona_materializer import materialize_persona_artifact


def _sample_research_artifact() -> ResearchArtifact:
    return ResearchArtifact(
        subject_identity={
            "canonical_name": "Ada Founder",
            "public_roles": ["Founder", "Operator"],
            "organizations": ["Example Labs"],
            "locations": ["New York"],
            "expertise_topics": ["AI", "Startups"],
        },
        source_registry=[
            ResearchSource(
                source_id="src-1",
                url="https://example.com/interview",
                title="Interview",
                snippet="Ada on building companies.",
                extracted_text="I care about shipping useful products and earning trust.",
                provider="mock",
                quality="full",
            )
        ],
        extracted_claims=[
            ResearchClaim(
                claim_id="claim-1",
                text="Ada focuses on shipping useful products.",
                claim_type="experience",
                confidence=0.92,
                source_ids=["src-1"],
            )
        ],
        timeline=[
            ResearchTimelineItem(
                date_or_range="2024",
                event="Launched Example Labs.",
                confidence=0.9,
                source_ids=["src-1"],
            )
        ],
        verified_quote_candidates=[
            ResearchQuoteCandidate(
                quote="I care about shipping useful products and earning trust.",
                source_id="src-1",
                confidence=0.91,
                context="Interview quote",
            )
        ],
        synthesis_summary="Ada is an operator-minded founder who prefers evidence and shipping over hype.",
        compile_metadata={"source": "test"},
    )


def test_materialize_persona_artifact_builds_canonical_fields():
    artifact = materialize_persona_artifact(
        twin_id="twin-123",
        research_artifact=_sample_research_artifact(),
    )

    assert artifact.twin_id == "twin-123"
    assert artifact.subject_name == "Ada Founder"
    assert artifact.public_profile["name"] == "Ada Founder"
    assert artifact.quote_pack[0].quote.startswith("I care about shipping")
    assert artifact.voice_dna.signature_phrases
    assert artifact.communication_rules
    assert artifact.retrieval_seeds
