-- Migration: Crawl pages schema compatibility for Phase 3 crawl processor
-- Purpose: Ensure columns expected by crawl_job_processor exist in production.

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS classification TEXT;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS previous_page_id UUID;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS content_quality VARCHAR(20);

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS identity_confidence_score INT;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS confirmation_status VARCHAR(20);

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS submitted_root_url TEXT;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS failure_type TEXT;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS title TEXT;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS http_status INT;

ALTER TABLE crawl_pages
ADD COLUMN IF NOT EXISTS fetch_attempts INT;

