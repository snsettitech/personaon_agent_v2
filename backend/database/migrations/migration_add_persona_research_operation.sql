-- Migration: Add persona_research to graph_outbox operation constraint
-- Required for worker-based research pipeline (graph_outbox_worker.py handles
-- persona_research jobs dispatched from create_run in name_deep_research_service.py)

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
        'persona_research'
    )
);
