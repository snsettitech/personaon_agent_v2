export type SourceType =
  | 'document'
  | 'web'
  | 'youtube'
  | 'podcast'
  | 'x_thread'
  | 'manual'
  | 'profile';

export interface Source {
  id: string;
  twin_id?: string;
  filename: string;
  file_size: number;
  status: string;
  created_at: string;
  source_type: SourceType;
  citation_url?: string;
  file_url?: string;
  chunk_count?: number;
  last_event_at?: string;
  health_status?: string;
}
