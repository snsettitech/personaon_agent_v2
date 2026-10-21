-- Migration: Add firecrawl_extract to graph_outbox operation constraint
-- Required for background Firecrawl extraction during onboarding

ALTER TABLE graph_outbox DROP CONSTRAINT IF EXISTS graph_outbox_operation_check;

ALTER TABLE graph_outbox ADD CONSTRAINT graph_outbox_operation_check CHECK (
    operation IN (
        'create_episode',
        'create_claims',
        'update_claim_status',
        'create_relationship',
        'delete_twin_graph',
        'extract_claims',
        'evaluate_contradictions',
        'refresh_snapshot',
        'persona_research',
        'enrich_from_web',
        'firecrawl_extract'
    )
);
