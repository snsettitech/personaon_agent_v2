-- Phase 4 Migration: Verified QnA Tables
-- This migration adds only the new tables for verified QnA functionality
-- Run this if you already have the base schema tables

-- Verified QnA table: Canonical verified answers
CREATE TABLE IF NOT EXISTS verified_qna (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  question_embedding TEXT, -- JSON array of floats (optional, for semantic matching via Pinecone)
  visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'shared', 'public')),
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  is_active BOOLEAN NOT NULL DEFAULT true
);

-- Answer Patches table: Version history for edits
CREATE TABLE IF NOT EXISTS answer_patches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  verified_qna_id UUID NOT NULL REFERENCES verified_qna(id) ON DELETE CASCADE,
  previous_answer TEXT NOT NULL,
  new_answer TEXT NOT NULL,
  reason TEXT,
  patched_by UUID REFERENCES users(id),
  patched_at TIMESTAMPTZ DEFAULT NOW()
);

-- Citations table: Source links for verified answers
CREATE TABLE IF NOT EXISTS citations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  verified_qna_id UUID NOT NULL REFERENCES verified_qna(id) ON DELETE CASCADE,
  source_id TEXT,
  chunk_id TEXT,
  citation_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_verified_qna_twin_id ON verified_qna(twin_id);
CREATE INDEX IF NOT EXISTS idx_verified_qna_is_active ON verified_qna(is_active);
CREATE INDEX IF NOT EXISTS idx_answer_patches_qna_id ON answer_patches(verified_qna_id);
CREATE INDEX IF NOT EXISTS idx_citations_qna_id ON citations(verified_qna_id);
