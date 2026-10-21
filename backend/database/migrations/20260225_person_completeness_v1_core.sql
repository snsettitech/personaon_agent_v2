-- ============================================================================
-- Person Completeness Layer v1 - Core Schema
-- ============================================================================
-- Implements advisor-like structured person modeling on top of existing
-- research claims pipeline (Phases 8-12).
--
-- All tables use twin_id for tenant isolation and support soft deletes.
-- Created: 2026-02-25
-- ============================================================================

-- ============================================================================
-- 1. PERSON SOURCE REGISTRY
-- Extended source tracking beyond the basic sources table
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_source_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Source identification
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'website_page', 'blog', 'youtube_video', 'podcast_episode',
        'linkedin_profile', 'social_post', 'interview', 'press',
        'github', 'uploaded_file', 'research_paper', 'news_article',
        'presentation', 'twitter_thread', 'book', 'unknown'
    )),
    platform TEXT,
    
    -- Content metadata
    title TEXT,
    author TEXT,
    language TEXT DEFAULT 'en',
    published_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_crawled_at TIMESTAMPTZ,
    
    -- Content metrics
    content_hash VARCHAR(64),
    content_length_chars INTEGER DEFAULT 0,
    content_length_words INTEGER DEFAULT 0,
    transcript_confidence FLOAT CHECK (transcript_confidence >= 0.0 AND transcript_confidence <= 1.0),
    
    -- Processing state
    crawl_status TEXT NOT NULL DEFAULT 'discovered' CHECK (crawl_status IN (
        'discovered', 'queued', 'crawling', 'completed', 'failed', 'blocked', 'skipped'
    )),
    processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN (
        'pending', 'extracting', 'enriching', 'completed', 'failed'
    )),
    
    -- Quality & verification
    owner_verified_status TEXT NOT NULL DEFAULT 'unverified' CHECK (owner_verified_status IN (
        'verified', 'unverified', 'inferred', 'disputed'
    )),
    authority_tier INTEGER CHECK (authority_tier >= 1 AND authority_tier <= 7),
    quality_score FLOAT CHECK (quality_score >= 0.0 AND quality_score <= 1.0),
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb,
    raw_reference_json JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete for audit trail
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Indexes for person_source_registry
CREATE INDEX IF NOT EXISTS idx_psr_twin_id ON person_source_registry(twin_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_psr_twin_type ON person_source_registry(twin_id, source_type) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_psr_crawl_status ON person_source_registry(crawl_status) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_psr_processing_status ON person_source_registry(processing_status) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_psr_url_hash ON person_source_registry(twin_id, content_hash) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_psr_authority ON person_source_registry(twin_id, authority_tier) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_psr_discovered ON person_source_registry(twin_id, discovered_at DESC) WHERE is_active = TRUE;

-- Unique constraint: normalized URL per twin
CREATE UNIQUE INDEX IF NOT EXISTS idx_psr_unique_url 
ON person_source_registry(twin_id, normalized_url) 
WHERE is_active = TRUE;

-- ============================================================================
-- 2. PERSON CLAIMS (extends research_claims for person-specific use)
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Link to research_claims if from deep research pipeline
    research_claim_id UUID REFERENCES research_claims(id) ON DELETE SET NULL,
    
    -- Claim content
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (claim_type IN (
        'identity', 'work_experience', 'education', 'credential', 'project',
        'achievement', 'preference', 'belief', 'goal', 'bio_fact', 'skill',
        'media_appearance', 'timeline_event', 'expertise', 'uncertain'
    )),
    
    -- Structured claim (for queryable SPO triples)
    subject TEXT,
    predicate TEXT,
    object TEXT,
    
    -- Temporal
    claim_time_start TIMESTAMPTZ,
    claim_time_end TIMESTAMPTZ,
    tense_status TEXT CHECK (tense_status IN (
        'active', 'historical', 'uncertain', 'contradicted', 'superseded'
    )),
    
    -- Extraction metadata
    extraction_method TEXT NOT NULL DEFAULT 'llm' CHECK (extraction_method IN (
        'rule', 'llm', 'manual', 'imported'
    )),
    extraction_confidence FLOAT NOT NULL CHECK (extraction_confidence >= 0.0 AND extraction_confidence <= 1.0),
    extraction_source_ids JSONB DEFAULT '[]'::jsonb, -- Array of source registry IDs
    
    -- Verification
    verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (verification_status IN (
        'unverified', 'verified', 'disputed', 'rejected', 'pending_review'
    )),
    verification_confidence FLOAT CHECK (verification_confidence >= 0.0 AND verification_confidence <= 1.0),
    
    -- Owner approval
    owner_approval_status TEXT NOT NULL DEFAULT 'not_required' CHECK (owner_approval_status IN (
        'pending', 'approved', 'rejected', 'not_required'
    )),
    
    -- Visibility
    public_visibility TEXT NOT NULL DEFAULT 'public' CHECK (public_visibility IN (
        'public', 'private', 'restricted'
    )),
    
    -- Provenance
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,
    
    -- Canonical link (if claim was superseded/merged)
    canonical_claim_id UUID REFERENCES person_claims(id) ON DELETE SET NULL,
    
    -- Content fingerprint for deduplication
    claim_fingerprint VARCHAR(64),
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Indexes for person_claims
CREATE INDEX IF NOT EXISTS idx_pc_twin_id ON person_claims(twin_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_twin_type ON person_claims(twin_id, claim_type) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_verification ON person_claims(twin_id, verification_status) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_approval ON person_claims(twin_id, owner_approval_status) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_visibility ON person_claims(twin_id, public_visibility) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_fingerprint ON person_claims(twin_id, claim_fingerprint) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_canonical ON person_claims(canonical_claim_id) WHERE canonical_claim_id IS NOT NULL AND is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_temporal ON person_claims(twin_id, claim_time_start, claim_time_end) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_research_link ON person_claims(research_claim_id) WHERE research_claim_id IS NOT NULL;

-- ============================================================================
-- 3. PERSON CLAIM EVIDENCE SPANS
-- Granular evidence linking claims to source positions
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_claim_evidence_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES person_claims(id) ON DELETE CASCADE,
    source_registry_id UUID NOT NULL REFERENCES person_source_registry(id) ON DELETE CASCADE,
    
    -- Source reference
    source_url TEXT,
    
    -- Evidence type and content
    evidence_type TEXT NOT NULL CHECK (evidence_type IN (
        'quote', 'transcript_span', 'page_span', 'snippet', 'highlight', 'section_ref'
    )),
    evidence_text TEXT NOT NULL,
    
    -- Text position (for documents)
    start_offset INTEGER,
    end_offset INTEGER,
    
    -- Media timestamps (for audio/video)
    timestamp_start_sec INTEGER,
    timestamp_end_sec INTEGER,
    
    -- Structural references
    section_label TEXT,
    line_ref TEXT,
    selector TEXT, -- CSS selector or similar for HTML sources
    
    -- Quality
    evidence_confidence FLOAT NOT NULL CHECK (evidence_confidence >= 0.0 AND evidence_confidence <= 1.0),
    
    -- Source party (first vs third person attribution)
    source_party TEXT CHECK (source_party IN ('first_party', 'third_party', 'unknown')),
    
    -- Timestamps
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb
);

-- Indexes for evidence spans
CREATE INDEX IF NOT EXISTS idx_pces_claim ON person_claim_evidence_spans(claim_id);
CREATE INDEX IF NOT EXISTS idx_pces_source ON person_claim_evidence_spans(source_registry_id);
CREATE INDEX IF NOT EXISTS idx_pces_claim_source ON person_claim_evidence_spans(claim_id, source_registry_id);
CREATE INDEX IF NOT EXISTS idx_pces_evidence_type ON person_claim_evidence_spans(evidence_type);

-- ============================================================================
-- 4. PERSON TIMELINE EVENTS
-- Derived timeline from temporal claims
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_timeline_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Event classification
    event_type TEXT NOT NULL CHECK (event_type IN (
        'job_start', 'job_end', 'education_start', 'education_end',
        'founded_company', 'company_exit', 'award', 'publication',
        'media_appearance', 'move', 'milestone', 'project_start',
        'project_end', 'interview', 'speaking_engagement', 'investment',
        'board_role', 'other'
    )),
    
    -- Event content
    title TEXT NOT NULL,
    description TEXT,
    
    -- Temporal (support partial dates via date_precision)
    start_date DATE,
    start_date_precision TEXT CHECK (start_date_precision IN ('day', 'month', 'year', 'approximate')),
    end_date DATE,
    end_date_precision TEXT CHECK (end_date_precision IN ('day', 'month', 'year', 'approximate')),
    is_ongoing BOOLEAN DEFAULT FALSE,
    
    -- Location/organization context
    organization TEXT,
    location TEXT,
    role_title TEXT,
    
    -- Quality
    confidence FLOAT NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    
    -- Provenance
    derived_from_claim_ids JSONB DEFAULT '[]'::jsonb, -- Array of claim IDs
    
    -- Deduplication
    event_fingerprint VARCHAR(64),
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Indexes for timeline events
CREATE INDEX IF NOT EXISTS idx_pte_twin_id ON person_timeline_events(twin_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pte_twin_type ON person_timeline_events(twin_id, event_type) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pte_start_date ON person_timeline_events(twin_id, start_date DESC) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pte_fingerprint ON person_timeline_events(twin_id, event_fingerprint) WHERE is_active = TRUE;

-- ============================================================================
-- 5. PERSON TOPIC PROFILES
-- Topic/expertise aggregation with answerability scoring
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_topic_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Topic identification
    topic_name TEXT NOT NULL,
    topic_slug TEXT NOT NULL,
    parent_topic_id UUID REFERENCES person_topic_profiles(id) ON DELETE SET NULL,
    
    -- Evidence counts
    evidence_count INTEGER NOT NULL DEFAULT 0,
    first_party_evidence_count INTEGER NOT NULL DEFAULT 0,
    third_party_evidence_count INTEGER NOT NULL DEFAULT 0,
    
    -- Recency score (0-1, higher = more recent evidence)
    recency_score FLOAT CHECK (recency_score >= 0.0 AND recency_score <= 1.0),
    
    -- Coverage score (how much content exists on this topic)
    coverage_score FLOAT CHECK (coverage_score >= 0.0 AND coverage_score <= 1.0),
    
    -- Verification score (ratio of verified claims)
    verification_score FLOAT CHECK (verification_score >= 0.0 AND verification_score <= 1.0),
    
    -- Consistency score (lack of contradictions)
    consistency_score FLOAT CHECK (consistency_score >= 0.0 AND consistency_score <= 1.0),
    
    -- Answerability score (computed composite)
    answerability_score FLOAT CHECK (answerability_score >= 0.0 AND answerability_score <= 1.0),
    confidence_to_answer FLOAT CHECK (confidence_to_answer >= 0.0 AND confidence_to_answer <= 1.0),
    
    -- Related claims/sources for drill-down
    related_claim_ids JSONB DEFAULT '[]'::jsonb,
    related_source_ids JSONB DEFAULT '[]'::jsonb,
    
    -- Computation tracking
    last_computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    computation_version INTEGER DEFAULT 1,
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for topic profiles
CREATE INDEX IF NOT EXISTS idx_ptp_twin_id ON person_topic_profiles(twin_id);
CREATE INDEX IF NOT EXISTS idx_ptp_twin_topic ON person_topic_profiles(twin_id, topic_slug);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ptp_unique_topic ON person_topic_profiles(twin_id, topic_slug);
CREATE INDEX IF NOT EXISTS idx_ptp_parent ON person_topic_profiles(parent_topic_id) WHERE parent_topic_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ptp_answerability ON person_topic_profiles(twin_id, answerability_score DESC);
CREATE INDEX IF NOT EXISTS idx_ptp_computed ON person_topic_profiles(last_computed_at);

-- ============================================================================
-- 6. PERSON STYLE PROFILE
-- Writing/speaking style extraction (one per twin, versioned)
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_style_profile (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Versioning (one active version per twin)
    version INTEGER NOT NULL DEFAULT 1,
    is_active_version BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_by_id UUID REFERENCES person_style_profile(id) ON DELETE SET NULL,
    
    -- Style descriptors
    tone_descriptors JSONB DEFAULT '[]'::jsonb, -- Array like ["professional", "casual", "authoritative"]
    
    -- Writing features
    writing_style_features JSONB DEFAULT '{}'::jsonb, -- {
                                                      --   "formality_level": 0.7,
                                                      --   "technical_density": 0.5,
                                                      --   "storytelling_tendency": 0.6,
                                                      --   "analytical_vs_experiential": 0.4,
                                                      --   ...
                                                      -- }
    
    -- Speech features (if audio sources available)
    speech_style_features JSONB DEFAULT '{}'::jsonb, -- {
                                                     --   "pace": "moderate",
                                                     --   "filler_word_frequency": 0.1,
                                                     --   ...
                                                     -- }
    
    -- Structural patterns
    sentence_length_profile JSONB DEFAULT '{}'::jsonb, -- {"short_pct": 30, "medium_pct": 50, "long_pct": 20}
    common_phrases JSONB DEFAULT '[]'::jsonb, -- Array of frequently used phrases
    
    -- Audience adaptation notes
    audience_adaptation_notes JSONB DEFAULT '{}'::jsonb, -- {"technical_audience": "high_jargon", ...}
    
    -- Confidence and provenance
    style_confidence FLOAT CHECK (style_confidence >= 0.0 AND style_confidence <= 1.0),
    generated_from_sources_count INTEGER DEFAULT 0,
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for style profile
CREATE INDEX IF NOT EXISTS idx_psp_twin_id ON person_style_profile(twin_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_psp_active_version ON person_style_profile(twin_id) WHERE is_active_version = TRUE;
CREATE INDEX IF NOT EXISTS idx_psp_version ON person_style_profile(twin_id, version DESC);

-- ============================================================================
-- 7. PERSON CONTRADICTIONS
-- Enhanced contradiction tracking beyond consistency_issues
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_contradictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Contradiction classification
    contradiction_type TEXT NOT NULL CHECK (contradiction_type IN (
        'timeline_conflict', 'role_conflict', 'factual_conflict',
        'preference_conflict', 'identity_conflict', 'credential_conflict',
        'location_conflict', 'temporal_overlap', 'mutual_exclusion'
    )),
    
    -- Involved claims (2+ claims can be involved)
    claim_id_a UUID NOT NULL REFERENCES person_claims(id) ON DELETE CASCADE,
    claim_id_b UUID NOT NULL REFERENCES person_claims(id) ON DELETE CASCADE,
    related_claim_ids JSONB DEFAULT '[]'::jsonb, -- Additional related claims
    
    -- Severity and status
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN (
        'open', 'adjudicated', 'dismissed', 'auto_resolved'
    )),
    
    -- Resolution
    auto_resolution_suggestion TEXT,
    resolution_notes TEXT,
    resolved_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    
    -- Confidence
    detection_confidence FLOAT NOT NULL CHECK (detection_confidence >= 0.0 AND detection_confidence <= 1.0),
    
    -- Timestamps
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    adjudicated_at TIMESTAMPTZ,
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb,
    
    -- Soft delete
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Indexes for contradictions
CREATE INDEX IF NOT EXISTS idx_pc_twin_status ON person_contradictions(twin_id, status) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_type ON person_contradictions(twin_id, contradiction_type) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_severity ON person_contradictions(twin_id, severity) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_claim_a ON person_contradictions(claim_id_a) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_claim_b ON person_contradictions(claim_id_b) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_pc_detected ON person_contradictions(twin_id, detected_at DESC) WHERE is_active = TRUE;

-- ============================================================================
-- 8. PERSON ANSWERABILITY SCORES
-- Runtime answerability scoring
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_answerability_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Scope (global, topic-specific, or audience-specific)
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global', 'topic', 'audience', 'source_type')),
    scope_key TEXT NOT NULL, -- topic_slug, audience_type, or source_type value
    
    -- Component scores (0-100 scale for precision)
    coverage_score INTEGER CHECK (coverage_score >= 0 AND coverage_score <= 100),
    verification_score INTEGER CHECK (verification_score >= 0 AND verification_score <= 100),
    recency_score INTEGER CHECK (recency_score >= 0 AND recency_score <= 100),
    consistency_score INTEGER CHECK (consistency_score >= 0 AND consistency_score <= 100),
    style_fidelity_score INTEGER CHECK (style_fidelity_score >= 0 AND style_fidelity_score <= 100),
    
    -- Composite score
    answerability_score INTEGER CHECK (answerability_score >= 0 AND answerability_score <= 100),
    
    -- Machine-readable explanation
    score_explanation_json JSONB DEFAULT '{}'::jsonb, -- {
                                                      --   "coverage_reason": "...",
                                                      --   "verification_reason": "...",
                                                      --   "bottlenecks": [...]
                                                      -- }
    
    -- Computation tracking
    last_computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    computation_version INTEGER DEFAULT 1,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for answerability scores
CREATE INDEX IF NOT EXISTS idx_pas_twin_scope ON person_answerability_scores(twin_id, scope_type, scope_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pas_unique_scope ON person_answerability_scores(twin_id, scope_type, scope_key);
CREATE INDEX IF NOT EXISTS idx_pas_score ON person_answerability_scores(twin_id, answerability_score DESC);
CREATE INDEX IF NOT EXISTS idx_pas_computed ON person_answerability_scores(last_computed_at);

-- ============================================================================
-- 9. PERSON RUNTIME POLICIES
-- Per-twin runtime behavior configuration
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_runtime_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Policy identification
    policy_name TEXT NOT NULL DEFAULT 'default',
    audience TEXT NOT NULL DEFAULT 'public' CHECK (audience IN (
        'public', 'recruiter', 'investor', 'customer', 'internal', 'admin'
    )),
    
    -- Content controls
    allow_sensitive_topics JSONB DEFAULT '{}'::jsonb, -- {"politics": false, "religion": true, ...}
    blocked_topics JSONB DEFAULT '[]'::jsonb, -- Array of topic slugs to block
    
    -- Citation requirements
    require_citation BOOLEAN NOT NULL DEFAULT TRUE,
    citation_min_confidence FLOAT DEFAULT 0.6,
    
    -- Owner approval requirements
    require_owner_approval_for_opinions BOOLEAN NOT NULL DEFAULT FALSE,
    opinion_claim_types JSONB DEFAULT '["preference", "belief", "goal"]'::jsonb,
    
    -- Confidence thresholds
    confidence_threshold_answer FLOAT NOT NULL DEFAULT 0.5, -- Min confidence to attempt answer
    confidence_threshold_style FLOAT NOT NULL DEFAULT 0.6, -- Min confidence for style adaptation
    
    -- Fallback behavior
    fallback_behavior TEXT NOT NULL DEFAULT 'i_dont_know' CHECK (fallback_behavior IN (
        'i_dont_know', 'clarify', 'escalate', 'omit_style'
    )),
    fallback_message_template TEXT, -- Custom message if not using default
    
    -- PII handling
    pii_masking_rules JSONB DEFAULT '{}'::jsonb, -- {"email": "mask", "phone": "redact", ...}
    
    -- Policy status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER DEFAULT 0, -- Higher = more specific policy takes precedence
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for runtime policies
CREATE UNIQUE INDEX IF NOT EXISTS idx_prp_twin_audience ON person_runtime_policies(twin_id, audience) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_prp_twin_active ON person_runtime_policies(twin_id, is_active);

-- ============================================================================
-- 10. PIPELINE RUN TRACKING
-- Track completeness pipeline runs per twin
-- ============================================================================

CREATE TABLE IF NOT EXISTS person_completeness_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    research_run_id UUID REFERENCES research_runs(id) ON DELETE SET NULL,
    
    -- Run status
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'partial'
    )),
    
    -- Stage tracking
    current_stage TEXT CHECK (current_stage IN (
        'source_registry_built', 'claims_extracted', 'timeline_built',
        'topic_graph_built', 'style_profile_built', 'contradictions_detected',
        'answerability_scored', 'completed'
    )),
    completed_stages JSONB DEFAULT '[]'::jsonb,
    
    -- Metrics per stage
    source_registry_count INTEGER DEFAULT 0,
    claims_extracted_count INTEGER DEFAULT 0,
    evidence_spans_count INTEGER DEFAULT 0,
    timeline_events_count INTEGER DEFAULT 0,
    topic_profiles_count INTEGER DEFAULT 0,
    contradictions_detected_count INTEGER DEFAULT 0,
    
    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Error tracking
    error_message TEXT,
    error_stage TEXT,
    
    -- Idempotency
    run_fingerprint VARCHAR(64), -- Hash of input parameters
    
    -- Extended metadata
    metadata_json JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for pipeline runs
CREATE INDEX IF NOT EXISTS idx_pcr_twin_status ON person_completeness_runs(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_pcr_twin_created ON person_completeness_runs(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pcr_research_run ON person_completeness_runs(research_run_id) WHERE research_run_id IS NOT NULL;

-- ============================================================================
-- Triggers for updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_person_completeness_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables with updated_at
DO $$
DECLARE
    tbl TEXT;
    tables TEXT[] := ARRAY[
        'person_source_registry',
        'person_claims',
        'person_timeline_events',
        'person_topic_profiles',
        'person_style_profile',
        'person_contradictions',
        'person_answerability_scores',
        'person_runtime_policies',
        'person_completeness_runs'
    ];
BEGIN
    FOREACH tbl IN ARRAY tables
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trigger_%s_updated_at ON %s;',
            tbl, tbl
        );
        EXECUTE format(
            'CREATE TRIGGER trigger_%s_updated_at
             BEFORE UPDATE ON %s
             FOR EACH ROW
             EXECUTE FUNCTION update_person_completeness_updated_at();',
            tbl, tbl
        );
    END LOOP;
END $$;

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE person_source_registry IS 
'Person Completeness v1: Extended source tracking with authority tiers and quality scoring';

COMMENT ON TABLE person_claims IS 
'Person Completeness v1: Structured claims with temporal, verification, and approval tracking';

COMMENT ON TABLE person_claim_evidence_spans IS 
'Person Completeness v1: Granular evidence spans linking claims to source positions';

COMMENT ON TABLE person_timeline_events IS 
'Person Completeness v1: Derived timeline events from temporal claims';

COMMENT ON TABLE person_topic_profiles IS 
'Person Completeness v1: Topic/expertise profiles with answerability scoring';

COMMENT ON TABLE person_style_profile IS 
'Person Completeness v1: Writing/speaking style profile (versioned per twin)';

COMMENT ON TABLE person_contradictions IS 
'Person Completeness v1: Enhanced contradiction detection and tracking';

COMMENT ON TABLE person_answerability_scores IS 
'Person Completeness v1: Runtime answerability scores by scope';

COMMENT ON TABLE person_runtime_policies IS 
'Person Completeness v1: Per-twin runtime behavior configuration';

COMMENT ON TABLE person_completeness_runs IS 
'Person Completeness v1: Pipeline run tracking and metrics';

-- ============================================================================
-- Migration complete
-- ============================================================================
