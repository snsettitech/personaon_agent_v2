-- Add optional folder column to sources for custom grouping via PATCH /sources/{id}
ALTER TABLE sources ADD COLUMN IF NOT EXISTS folder TEXT;
