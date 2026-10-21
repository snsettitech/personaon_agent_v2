export interface TwinStatusDisplay {
  label: string;
  detail: string;
  color: string;
  background: string;
}

export function formatStatus(status?: string): TwinStatusDisplay {
  switch (status) {
    case 'active':
      return { label: 'Active', detail: 'Ready to operate', color: '#ffffff', background: '#146c2e' };
    case 'persona_built':
      return { label: 'Built', detail: 'Ready for review', color: '#0b5cab', background: '#e8f2ff' };
    case 'ingesting':
      return { label: 'Building', detail: 'Context is processing', color: '#7a4d00', background: '#fff4d6' };
    case 'claims_ready':
      return { label: 'Review', detail: 'Needs approval', color: '#7a4d00', background: '#fff4d6' };
    case 'clarification_pending':
      return { label: 'Needs answers', detail: 'Clarification pending', color: '#7f1d1d', background: '#fee2e2' };
    case 'draft':
      return { label: 'Draft', detail: 'Keep building', color: '#5f6368', background: '#f1f3f4' };
    default:
      return { label: 'Persona', detail: 'Status unavailable', color: '#5f6368', background: '#f1f3f4' };
  }
}
