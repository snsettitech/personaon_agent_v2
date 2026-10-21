from pydantic import BaseModel, Field
from typing import Any
from datetime import datetime

class ChatRequest(BaseModel):
    query: str | None = None
    twin_id: str | None = None
    conversation_id: str | None = None
    group_id: str | None = None  # NEW: Allow group override
    metadata: dict[str, Any] | None = None
    mode: str | None = None  # Deprecated: ignored for auth/routing decisions
    training_session_id: str | None = None
    trace_id: str | None = None  # Langfuse trace ID for observability linking
    # Compatibility: accept legacy {message} payloads for one release window
    message: str | None = None

class ChatMetadata(BaseModel):
    type: str = "metadata"
    citations: list[str]
    conversation_id: str
    answerability_state: str = "unknown"
    source_tier: str = "mixed"
    review_required: bool = False
    review_reason: str | None = None

class ChatContent(BaseModel):
    type: str = "content"
    content: str

class ChatDone(BaseModel):
    type: str = "done"
    escalated: bool

class IngestionResponse(BaseModel):
    status: str
    chunks_ingested: int
    source_id: str

class SourceSchema(BaseModel):
    id: str
    twin_id: str
    filename: str | None
    file_size: int | None
    status: str
    created_at: datetime | None

class MessageSchema(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    citations: list[str] | None
    answerability_state: str | None = None
    source_tier: str | None = None
    review_required: bool | None = None
    review_reason: str | None = None
    created_at: datetime | None

class ConversationSchema(BaseModel):
    id: str
    twin_id: str
    user_id: str | None
    created_at: datetime | None

class EscalationSchema(BaseModel):
    id: str
    message_id: str
    status: str
    created_at: datetime
    messages: MessageSchema | None = None

class TwinSettingsUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None
    settings: dict[str, Any] | None = None

class YouTubeIngestRequest(BaseModel):
    url: str

class PodcastIngestRequest(BaseModel):
    url: str # RSS feed or direct audio link

class XThreadIngestRequest(BaseModel):
    url: str

class KnowledgeProfile(BaseModel):
    total_chunks: int
    total_sources: int
    fact_count: int
    opinion_count: int
    tone_distribution: dict[str, int]
    top_tone: str

class CitationSchema(BaseModel):
    id: str
    verified_qna_id: str
    source_id: str | None = None
    chunk_id: str | None = None
    citation_url: str | None = None
    created_at: datetime | None = None

class AnswerPatchSchema(BaseModel):
    id: str
    verified_qna_id: str
    previous_answer: str
    new_answer: str
    reason: str | None = None
    patched_by: str | None = None
    patched_at: datetime | None = None

class VerifiedQnASchema(BaseModel):
    id: str
    twin_id: str
    question: str
    answer: str
    visibility: str
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_active: bool
    citations: list[CitationSchema] | None = None
    patches: list[AnswerPatchSchema] | None = None

class VerifiedQnACreateRequest(BaseModel):
    question: str
    answer: str
    citations: list[str] | None = None
    visibility: str | None = "private"

class VerifiedQnAUpdateRequest(BaseModel):
    answer: str
    reason: str

# Access Groups Schemas
class AccessGroupSchema(BaseModel):
    id: str
    twin_id: str
    name: str
    description: str | None = None
    is_default: bool
    is_public: bool
    settings: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None

class GroupMembershipSchema(BaseModel):
    id: str
    group_id: str
    user_id: str
    twin_id: str
    is_active: bool
    created_at: datetime | None = None

class ContentPermissionSchema(BaseModel):
    id: str
    group_id: str
    twin_id: str
    content_type: str
    content_id: str
    created_at: datetime | None = None

class GroupCreateRequest(BaseModel):
    name: str
    description: str | None = None
    is_public: bool = False
    settings: dict[str, Any] | None = None

class GroupUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None

class AssignUserRequest(BaseModel):
    user_id: str
    group_id: str

class ContentPermissionRequest(BaseModel):
    content_type: str  # 'source' or 'verified_qna'
    content_ids: list[str]  # List of IDs to grant access

class GroupLimitSchema(BaseModel):
    id: str
    group_id: str
    limit_type: str
    limit_value: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

class GroupOverrideSchema(BaseModel):
    id: str
    group_id: str
    override_type: str
    override_value: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None

# Phase 6: Mind Ops Layer Schemas

class SourceHealthCheckSchema(BaseModel):
    id: str
    source_id: str
    check_type: str
    status: str
    message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

class TrainingJobSchema(BaseModel):
    id: str
    source_id: str
    twin_id: str
    status: str
    job_type: str
    priority: int
    error_message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

class IngestionLogSchema(BaseModel):
    id: str
    source_id: str
    twin_id: str
    log_level: str
    message: str
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None

class BulkUpdateRequest(BaseModel):
    source_ids: list[str]
    metadata: dict[str, Any]  # Can include: publish_date, author, citation_url

# Phase 7: Omnichannel Distribution Schemas

class ApiKeyCreateRequest(BaseModel):
    twin_id: str
    name: str
    group_id: str | None = None
    allowed_domains: list[str] | None = None
    expires_at: datetime | None = None

class ApiKeyUpdateRequest(BaseModel):
    name: str | None = None
    allowed_domains: list[str] | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None

class ApiKeySchema(BaseModel):
    id: str
    twin_id: str
    name: str
    key_prefix: str
    group_id: str | None = None
    allowed_domains: list[str]
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None

class ShareLinkResponse(BaseModel):
    twin_id: str
    share_token: str | None
    share_url: str | None
    public_share_enabled: bool

class SessionCreateRequest(BaseModel):
    twin_id: str
    group_id: str | None = None
    session_type: str  # 'anonymous' or 'authenticated'
    user_id: str | None = None

class SessionSchema(BaseModel):
    id: str
    twin_id: str
    group_id: str | None = None
    session_type: str
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime

class RateLimitStatusResponse(BaseModel):
    requests_per_hour: dict[str, Any] | None = None
    requests_per_day: dict[str, Any] | None = None

class UserInvitationCreateRequest(BaseModel):
    email: str
    role: str # 'owner' or 'viewer'

class UserInvitationSchema(BaseModel):
    id: str
    tenant_id: str
    email: str
    invitation_token: str
    invitation_url: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime

class ChatWidgetRequest(BaseModel):
    query: str
    session_id: str | None = None
    api_key: str
    # Compatibility: accept legacy {message} payloads for one release window
    message: str | None = None

class PublicChatRequest(BaseModel):
    message: str
    conversation_history: list[dict[str, Any]] | None = None
    trace_id: str | None = None  # Langfuse trace ID for observability linking

# Owner Memory + Clarifications

class OwnerMemorySchema(BaseModel):
    id: str
    twin_id: str
    tenant_id: str
    topic_normalized: str
    memory_type: str
    value: str
    stance: str | None = None
    intensity: int | None = None
    status: str
    created_at: datetime | None = None

class ClarificationThreadSchema(BaseModel):
    id: str
    twin_id: str
    tenant_id: str
    status: str
    mode: str
    original_query: str | None = None
    question: str
    options: list[dict[str, Any]] | None = None
    memory_write_proposal: dict[str, Any] | None = None
    owner_memory_id: str | None = None
    created_at: datetime | None = None

class ClarificationResolveRequest(BaseModel):
    answer: str
    selected_option: str | None = None

# Phase 9: Verification & Governance Schemas

class AuditLogSchema(BaseModel):
    id: str
    twin_id: str
    actor_id: str | None = None
    event_type: str
    action: str
    metadata: dict[str, Any] | None = None
    created_at: datetime

class GovernancePolicySchema(BaseModel):
    id: str
    twin_id: str
    policy_type: str
    name: str
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class GovernancePolicyCreateRequest(BaseModel):
    policy_type: str
    name: str
    content: str
    is_active: bool = True

class TwinVerificationSchema(BaseModel):
    id: str
    twin_id: str
    status: str
    verification_method: str
    metadata: dict[str, Any] | None = None
    requested_at: datetime
    verified_at: datetime | None = None
    verified_by: str | None = None

class TwinVerificationRequest(BaseModel):
    verification_method: str = "MANUAL_REVIEW"
    metadata: dict[str, Any] | None = None

class DeepScrubRequest(BaseModel):
    source_id: str
    reason: str | None = None

# Phase 8: Actions Engine Schemas

class EventSchema(BaseModel):
    id: str
    twin_id: str
    event_type: str
    payload: dict[str, Any]
    source_context: dict[str, Any] | None = None
    created_at: datetime

class TriggerConditions(BaseModel):
    intent_contains: list[str] | None = None
    keywords: list[str] | None = None
    review_required: bool | None = None
    group_id: str | None = None

class ActionTriggerSchema(BaseModel):
    id: str
    twin_id: str
    name: str
    description: str | None = None
    event_type: str
    conditions: dict[str, Any]
    connector_id: str | None = None
    action_type: str
    action_config: dict[str, Any]
    requires_approval: bool
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime

class TriggerCreateRequest(BaseModel):
    name: str
    description: str | None = None
    event_type: str
    conditions: dict[str, Any] | None = None
    connector_id: str | None = None
    action_type: str
    action_config: dict[str, Any] | None = None
    requires_approval: bool = True

class TriggerUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: dict[str, Any] | None = None
    action_config: dict[str, Any] | None = None
    requires_approval: bool | None = None
    is_active: bool | None = None
    priority: int | None = None

class ActionDraftSchema(BaseModel):
    id: str
    trigger_id: str | None = None
    event_id: str | None = None
    twin_id: str
    status: str
    proposed_action: dict[str, Any]
    context: dict[str, Any]
    approval_note: str | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

class DraftApproveRequest(BaseModel):
    approval_note: str | None = None

class DraftRejectRequest(BaseModel):
    rejection_note: str | None = None

class DraftRespondRequest(BaseModel):
    """Owner response to a triggered action - creates a saved response"""
    response_message: str
    save_as_verified: bool = False  # If true, save as verified QnA for future use

class ActionExecutionSchema(BaseModel):
    id: str
    draft_id: str | None = None
    trigger_id: str | None = None
    twin_id: str
    connector_id: str | None = None
    action_type: str
    status: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    error_message: str | None = None
    execution_duration_ms: int | None = None
    executed_by: str | None = None
    executed_at: datetime

class ToolConnectorSchema(BaseModel):
    id: str
    twin_id: str
    connector_type: str
    name: str
    config: dict[str, Any]
    is_active: bool
    last_used_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

class ConnectorCreateRequest(BaseModel):
    connector_type: str
    name: str
    config: dict[str, Any] | None = None

class ConnectorTestResponse(BaseModel):
    success: bool
    message: str | None = None
    error: str | None = None

class EventEmitRequest(BaseModel):
    event_type: str
    payload: dict[str, Any]
    source_context: dict[str, Any] | None = None


# ============================================================================
# Governance & Audit Schemas
# ============================================================================

class AuditLogSchema(BaseModel):
    id: str
    twin_id: str | None = None
    tenant_id: str | None = None
    actor_id: str | None = None
    event_type: str
    action: str
    metadata: dict[str, Any]
    created_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class GovernancePolicySchema(BaseModel):
    id: str
    tenant_id: str | None = None
    twin_id: str | None = None
    policy_type: str
    name: str
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


class GovernancePolicyCreateRequest(BaseModel):
    policy_type: str = "refusal_rule"
    name: str
    content: str


class TwinVerificationRequest(BaseModel):
    verification_method: str = "MANUAL_REVIEW"
    metadata: dict[str, Any] | None = None


class DeepScrubRequest(BaseModel):
    reason: str | None = None


# =============================================================================
# Training Metrics Schemas (creator-scoped Profile Metrics)
# =============================================================================

class TrainingMetricsSchema(BaseModel):
    """
    creator-scoped training metrics for twin/profile display.

    V1 Heuristic Implementation:
    - words_processed: Total words from successfully ingested sources
    - questions_answerable_est: Estimated coverage based on content volume
    - mind_score: 0-100 training completeness score

    NOTE: This is an ESTIMATE, not a literal count of validated questions.
    See docs/training_metrics_v1.md for formula details.
    """
    words_processed: int = 0
    words_processed_display: str = "0"
    questions_answerable_est: int = 0
    questions_answerable_display: str = "0"
    mind_score: int = 0
    mind_score_label: str = "Early"
    method_version: str = "v1_heuristic"
    last_computed_at: str | None = None
    notes: str = "Estimated metrics based on ingested content volume, diversity, and extraction quality."


class TwinWithTrainingMetricsSchema(BaseModel):
    """Twin response including training metrics."""
    id: str
    name: str
    tenant_id: str
    description: str | None = None
    status: str | None = None
    settings: dict[str, Any] | None = None
    training_metrics: TrainingMetricsSchema = Field(default_factory=TrainingMetricsSchema)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ============================================================================
# Deep Research Schemas (Phase 1A+)
# ============================================================================

class CrawlRunCreateRequest(BaseModel):
    """Request to create a new crawl run."""
    seed_urls: list[str]
    max_pages: int = 50
    max_depth: int = 2
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    url_canonicalization_rules: dict[str, Any] | None = None
    safety_config: dict[str, Any] | None = None


class CrawlRunSchema(BaseModel):
    """Crawl run response schema."""
    id: str
    twin_id: str
    status: str
    pages_found: int
    pages_ingested: int
    pages_failed: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class CrawlPageSchema(BaseModel):
    """Crawl page response schema."""
    id: str
    crawl_id: str
    url: str
    canonical_url: str
    status: str
    content_length: int | None
    snippet: str | None
    error_category: str | None
    fetched_at: datetime | None


class CrawlChangesResponse(BaseModel):
    """Response for crawl changes endpoint."""
    unchanged_pages: int
    changed_pages: int
    new_pages: int
    removed_pages: int
    changes: list[dict[str, Any]]


class ResearchRunCreateRequest(BaseModel):
    """Request to create a new research run."""
    query: str
    max_depth: int = 2
    claim_classes: list[str] | None = None
    web_verify_policy: str = "eligible_only"
    force_new: bool = False


class ResearchRunSchema(BaseModel):
    """Research run response schema."""
    id: str
    twin_id: str
    status: str
    original_query: str
    planned_subquestions: int
    completed_subquestions: int
    failed_subquestions: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ResearchSubquestionSchema(BaseModel):
    """Research subquestion response schema."""
    id: str
    research_run_id: str
    sequence_number: int
    status: str
    question_text: str
    query_used: str | None
    claims_extracted: int
    claims_verified_locally: int
    claims_verified_web: int
    started_at: datetime | None
    completed_at: datetime | None


class ResearchProgressEvent(BaseModel):
    """Streaming event for research progress."""
    type: str  # research_created, plan_ready, progress, verification_complete, etc.
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
