import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

export interface WidgetApiKey {
  id: string;
  key_prefix: string;
  name: string;
  allowed_domains: string[];
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  widget_config?: WidgetConfig;
}

export interface WidgetConfig {
  bubble_color?: string;
  position?: 'bottom-right' | 'bottom-left';
  welcome_message?: string;
  lead_capture_enabled?: boolean;
  lead_capture_prompt?: string;
}

export interface WidgetLead {
  id: string;
  visitor_name: string | null;
  visitor_email: string | null;
  source_domain: string | null;
  created_at: string;
  turn_count: number;
  conversation_id: string | null;
  offer_state: string | null;
  api_key_id: string | null;
  inferred_visitor_type: string | null;
  inferred_intent: string | null;
  contacted_at: string | null;
}

export async function listWidgetKeys(twinId: string): Promise<WidgetApiKey[]> {
  const res = await authFetchStandalone(`/widget/keys/${twinId}`);
  if (!res.ok) throw new Error(`Failed to list keys: ${res.status}`);
  return res.json();
}

export class PlanUpgradeRequiredError extends Error {
  constructor() {
    super('This feature requires a Pro subscription.');
    this.name = 'PlanUpgradeRequiredError';
  }
}

export async function createWidgetKey(twinId: string, name = 'Widget Key'): Promise<{ key: string; id: string }> {
  const res = await authFetchStandalone(`/widget/keys/${twinId}`, {
    method: 'POST',
    body: JSON.stringify({ name, allowed_domains: [] }),
  });
  if (res.status === 402 || res.status === 403) throw new PlanUpgradeRequiredError();
  if (!res.ok) throw new Error(`Failed to create key: ${res.status}`);
  return res.json();
}

export async function revokeWidgetKey(keyId: string): Promise<void> {
  const res = await authFetchStandalone(`/widget/keys/${keyId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to revoke key: ${res.status}`);
}

export async function updateWidgetConfig(keyId: string, patch: WidgetConfig): Promise<void> {
  const res = await authFetchStandalone(`/widget/config/${keyId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update config: ${res.status}`);
}

export async function listWidgetLeads(twinId: string, limit = 100): Promise<WidgetLead[]> {
  const res = await authFetchStandalone(`/widget/leads/list/${twinId}?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to list leads: ${res.status}`);
  return res.json();
}

export async function markLeadContacted(leadId: string): Promise<void> {
  const res = await authFetchStandalone(`/widget/leads/${leadId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ contacted_at: new Date().toISOString() }),
  });
  if (!res.ok) throw new Error(`Failed to update lead: ${res.status}`);
}

export async function deleteLead(leadId: string): Promise<void> {
  const res = await authFetchStandalone(`/widget/leads/${leadId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete lead: ${res.status}`);
}
