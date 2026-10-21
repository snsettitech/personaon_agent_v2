'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { useAuthFetch } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

// ── Types ──────────────────────────────────────────────────────────

type ActionType = 'booking_link' | 'webhook' | 'respond_with_message' | 'mode_switch' | 'native_calendar';

interface ActionConfig {
  url?: string;
  message?: string;
  webhook_url?: string;
  confirmation?: string;
  mode?: string;
  prompt_override?: string;
  // native_calendar config
  business_hours_start?: string;
  business_hours_end?: string;
  slot_duration?: number;
  buffer_minutes?: number;
  fallback_url?: string;
}

interface PersonaAction {
  id: string;
  type: ActionType;
  trigger: string;          // Primary trigger (first in triggers array, for display)
  triggers: string[];       // Multi-keyword array: ["/coffeechat", "#coffeechat", "coffee chat", "want to meet"]
  label: string;
  config: ActionConfig;
  collect_fields: string[];
  is_active: boolean;
}

interface ActionExecution {
  id: string;
  action_type: string;
  status: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  executed_by: string;
  created_at: string;
}

const ACTION_TYPE_LABELS: Record<ActionType, string> = {
  booking_link: 'Booking Link',
  webhook: 'Webhook',
  respond_with_message: 'Custom Response',
  mode_switch: 'Mode Switch',
  native_calendar: 'Calendar Booking',
};

const ACTION_TYPE_COLORS: Record<ActionType, string> = {
  booking_link: 'bg-blue-50 text-blue-700 border-blue-200',
  webhook: 'bg-purple-50 text-purple-700 border-purple-200',
  respond_with_message: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  mode_switch: 'bg-slate-50 text-slate-700 border-slate-200',
  native_calendar: 'bg-sky-50 text-sky-700 border-sky-200',
};

const COLLECT_FIELD_OPTIONS = ['name', 'email', 'message', 'topic'];

// ── Helpers ────────────────────────────────────────────────────────

function generateId(): string {
  return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function createEmptyAction(): PersonaAction {
  return {
    id: generateId(),
    type: 'booking_link',
    trigger: '/',
    triggers: [],
    label: '',
    config: {},
    collect_fields: [],
    is_active: true,
  };
}

// ── Action Card ────────────────────────────────────────────────────

function ActionCard({
  action,
  onToggle,
  onEdit,
  onDelete,
}: {
  action: PersonaAction;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const configSummary = (() => {
    switch (action.type) {
      case 'booking_link':
        return action.config.url || 'No URL set';
      case 'webhook':
        return action.config.webhook_url || 'No webhook URL set';
      case 'respond_with_message':
        return action.config.message
          ? action.config.message.length > 80
            ? action.config.message.slice(0, 80) + '...'
            : action.config.message
          : 'No message set';
      case 'mode_switch':
        return action.config.mode || 'No mode set';
      case 'native_calendar': {
        const dur = action.config.slot_duration || 30;
        const start = action.config.business_hours_start || '09:00';
        const end = action.config.business_hours_end || '17:00';
        return `${dur}min slots, ${start} - ${end}`;
      }
      default:
        return '';
    }
  })();

  return (
    <div className="rounded-2xl border border-white/60 bg-white/80 shadow-[0_4px_20px_rgba(15,23,42,0.04)] backdrop-blur-sm p-5 transition-all hover:shadow-[0_8px_30px_rgba(15,23,42,0.08)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center rounded-lg border border-[#0066cc]/20 bg-[#0066cc]/10 px-2.5 py-1 font-mono text-xs font-bold text-[#0066cc]">
              {action.triggers?.[0] || action.trigger}
              {action.triggers && action.triggers.length > 1 && (
                <span className="ml-1 font-normal text-[#0066cc]/70">+{action.triggers.length - 1}</span>
              )}
            </span>
            <span className={`inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-semibold border ${ACTION_TYPE_COLORS[action.type]}`}>
              {ACTION_TYPE_LABELS[action.type]}
            </span>
            {!action.is_active && (
              <span className="inline-flex items-center rounded-lg bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                Inactive
              </span>
            )}
          </div>
          <h3 className="mt-2 text-base font-bold text-slate-900 truncate">{action.label || 'Untitled Action'}</h3>
          <p className="mt-1 text-sm text-slate-500 truncate">{configSummary}</p>
          {action.collect_fields.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {action.collect_fields.map((field) => (
                <span key={field} className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                  {field}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Active/Inactive toggle */}
          <button
            onClick={onToggle}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ${
              action.is_active ? 'bg-[#0066cc]' : 'bg-slate-200'
            }`}
            title={action.is_active ? 'Deactivate' : 'Activate'}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ${
                action.is_active ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
          <button
            onClick={onEdit}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            title="Edit"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
          <button
            onClick={onDelete}
            className="rounded-lg p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 transition-colors"
            title="Delete"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Action Form (Add / Edit) ───────────────────────────────────────

function ActionForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: PersonaAction;
  onSave: (action: PersonaAction) => void;
  onCancel: () => void;
}) {
  const [action, setAction] = useState<PersonaAction>(initial);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  const updateField = <K extends keyof PersonaAction>(key: K, value: PersonaAction[K]) => {
    setAction({ ...action, [key]: value });
  };

  const updateConfig = (key: string, value: string) => {
    setAction({ ...action, config: { ...action.config, [key]: value } });
  };

  const toggleCollectField = (field: string) => {
    const fields = action.collect_fields.includes(field)
      ? action.collect_fields.filter((f) => f !== field)
      : [...action.collect_fields, field];
    updateField('collect_fields', fields);
  };

  const handleSubmit = () => {
    if (!action.label.trim()) return;
    const validTriggers = (action.triggers.length > 0 ? action.triggers : [action.trigger])
      .filter((k) => k.length >= 2);
    if (validTriggers.length === 0) return;
    // Ensure trigger (primary) is synced with first valid trigger
    const finalAction: PersonaAction = {
      ...action,
      trigger: validTriggers[0],
      triggers: validTriggers,
    };
    onSave(finalAction);
  };

  return (
    <div className="rounded-2xl border border-white/60 bg-white/90 shadow-[0_10px_40px_rgba(15,23,42,0.08)] backdrop-blur-sm p-6 space-y-5">
      <h3 className="text-lg font-bold text-slate-900">
        {initial.label ? 'Edit Action' : 'New Action'}
      </h3>

      {/* Type selector */}
      <div>
        <label className="block text-sm font-semibold text-slate-700 mb-2">Type</label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {(Object.keys(ACTION_TYPE_LABELS) as ActionType[]).map((type) => (
            <button
              key={type}
              onClick={() => updateField('type', type)}
              className={`rounded-xl border px-3 py-2.5 text-sm font-semibold transition-all ${
                action.type === type
                  ? 'border-[#0066cc] bg-[#0066cc]/10 text-[#0066cc] shadow-sm'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
              }`}
            >
              {ACTION_TYPE_LABELS[type]}
            </button>
          ))}
        </div>
      </div>

      {/* Trigger Keywords */}
      <div>
        <label className="block text-sm font-semibold text-slate-700 mb-1.5">
          Trigger Keywords
          <span className="font-normal text-slate-400 ml-1">(comma-separated)</span>
        </label>
        <input
          type="text"
          value={action.triggers.length > 0 ? action.triggers.join(', ') : action.trigger}
          onChange={(e) => {
            const raw = e.target.value;
            const keywords = raw.split(',').map((k) => k.trim()).filter(Boolean);
            const primary = keywords[0] || '/';
            setAction({ ...action, trigger: primary, triggers: keywords });
            setTriggerError(
              keywords.length === 0 || keywords.every((k) => k.length < 2)
                ? 'Add at least one trigger keyword (min 2 chars)'
                : null
            );
          }}
          placeholder="/coffeechat, coffee chat, want to meet, schedule"
          className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 font-mono text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
        />
        <p className="mt-1.5 text-xs text-slate-400">
          Supports /commands, #hashtags, and natural phrases. Any message containing a keyword triggers this action.
        </p>
        {triggerError && <p className="mt-1 text-xs text-red-500">{triggerError}</p>}
      </div>

      {/* Label */}
      <div>
        <label className="block text-sm font-semibold text-slate-700 mb-1.5">Label</label>
        <input
          type="text"
          value={action.label}
          onChange={(e) => updateField('label', e.target.value)}
          placeholder="Book a Coffee Chat"
          className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
        />
      </div>

      {/* Type-specific config */}
      {action.type === 'booking_link' && (
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Booking URL</label>
          <input
            type="url"
            value={action.config.url || ''}
            onChange={(e) => updateConfig('url', e.target.value)}
            placeholder="https://calendly.com/you/30min"
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
          <label className="mt-3 block text-sm font-semibold text-slate-700 mb-1.5">
            Confirmation Message <span className="font-normal text-slate-400">(optional)</span>
          </label>
          <input
            type="text"
            value={action.config.message || ''}
            onChange={(e) => updateConfig('message', e.target.value)}
            placeholder="Opening booking page..."
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
        </div>
      )}

      {action.type === 'webhook' && (
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Webhook URL</label>
          <input
            type="url"
            value={action.config.webhook_url || ''}
            onChange={(e) => updateConfig('webhook_url', e.target.value)}
            placeholder="https://hooks.zapier.com/..."
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
          <label className="mt-3 block text-sm font-semibold text-slate-700 mb-1.5">
            Confirmation Message
          </label>
          <input
            type="text"
            value={action.config.confirmation || ''}
            onChange={(e) => updateConfig('confirmation', e.target.value)}
            placeholder="Request submitted successfully."
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
        </div>
      )}

      {action.type === 'respond_with_message' && (
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Response Message</label>
          <textarea
            value={action.config.message || ''}
            onChange={(e) => updateConfig('message', e.target.value)}
            placeholder="Thanks for reaching out! I usually respond within 24 hours..."
            rows={3}
            className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
        </div>
      )}

      {action.type === 'mode_switch' && (
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Mode Name</label>
          <input
            type="text"
            value={action.config.mode || ''}
            onChange={(e) => updateConfig('mode', e.target.value)}
            placeholder="consulting"
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
          <label className="mt-3 block text-sm font-semibold text-slate-700 mb-1.5">
            Prompt Override <span className="font-normal text-slate-400">(optional)</span>
          </label>
          <textarea
            value={action.config.prompt_override || ''}
            onChange={(e) => updateConfig('prompt_override', e.target.value)}
            placeholder="In this mode, focus on..."
            rows={2}
            className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
          />
        </div>
      )}

      {action.type === 'native_calendar' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Business Hours Start</label>
              <input
                type="time"
                value={action.config.business_hours_start || '09:00'}
                onChange={(e) => updateConfig('business_hours_start', e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Business Hours End</label>
              <input
                type="time"
                value={action.config.business_hours_end || '17:00'}
                onChange={(e) => updateConfig('business_hours_end', e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Slot Duration (min)</label>
              <select
                value={String(action.config.slot_duration || '30')}
                onChange={(e) => updateConfig('slot_duration', e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
              >
                <option value="15">15 minutes</option>
                <option value="30">30 minutes</option>
                <option value="45">45 minutes</option>
                <option value="60">60 minutes</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Buffer Between (min)</label>
              <select
                value={String(action.config.buffer_minutes || '15')}
                onChange={(e) => updateConfig('buffer_minutes', e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
              >
                <option value="0">No buffer</option>
                <option value="5">5 minutes</option>
                <option value="10">10 minutes</option>
                <option value="15">15 minutes</option>
                <option value="30">30 minutes</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">
              Fallback URL <span className="font-normal text-slate-400">(if calendar not connected)</span>
            </label>
            <input
              type="url"
              value={action.config.fallback_url || ''}
              onChange={(e) => updateConfig('fallback_url', e.target.value)}
              placeholder="https://calendly.com/you/30min"
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
            />
            <p className="mt-1 text-xs text-slate-400">
              Used when Google Calendar is not connected. Leave empty to show a &quot;not available&quot; message.
            </p>
          </div>
          <div className="rounded-xl border border-[#0066cc]/20 bg-[#0066cc]/10 p-3">
            <p className="text-xs text-[#0066cc]">
              Connect your Google Calendar in <a href="/dashboard/settings" className="font-semibold underline hover:text-[#004f9f]">Settings</a> to enable native booking.
            </p>
          </div>
        </div>
      )}

      {/* Collect fields */}
      <div>
        <label className="block text-sm font-semibold text-slate-700 mb-2">
          Collect from visitor <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <div className="flex flex-wrap gap-2">
          {COLLECT_FIELD_OPTIONS.map((field) => (
            <button
              key={field}
              onClick={() => toggleCollectField(field)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-all ${
                action.collect_fields.includes(field)
                  ? 'border-[#0066cc] bg-[#0066cc]/10 text-[#0066cc]'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'
              }`}
            >
              {field}
            </button>
          ))}
        </div>
      </div>

      {/* Buttons */}
      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          onClick={onCancel}
          className="rounded-xl border border-slate-200 px-5 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={!action.label.trim() || (action.triggers.length > 0 ? action.triggers : [action.trigger]).filter((k) => k.length >= 2).length === 0}
          className="rounded-full bg-[#0066cc] px-6 py-2.5 text-sm font-semibold text-white shadow-md shadow-[#0066cc]/25 transition-all hover:bg-[#0052a3] disabled:opacity-50"
        >
          Save Action
        </button>
      </div>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function formatRelativeTime(dateStr: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diffMs = now - date;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

// ── Executions Table ───────────────────────────────────────────────

function ExecutionsTable({ executions }: { executions: ActionExecution[] }) {
  if (executions.length === 0) {
    return (
      <div className="rounded-2xl border border-white/60 bg-white/80 shadow-[0_4px_20px_rgba(15,23,42,0.04)] backdrop-blur-sm p-8 text-center">
        <p className="text-sm text-slate-400">No action executions yet</p>
        <p className="mt-1 text-xs text-slate-300">Visitor actions will appear here when triggered</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-white/60 bg-white/80 shadow-[0_4px_20px_rgba(15,23,42,0.04)] backdrop-blur-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100">
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Trigger</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Type</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Visitor</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">When</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {executions.map((exec) => {
              const inputs = (exec.inputs || {}) as Record<string, unknown>;
              const trigger = (inputs.trigger as string) || '-';
              const collectedData = (inputs.collected_data || {}) as Record<string, string>;
              const visitorName = collectedData.name || collectedData.email || exec.executed_by || '-';
              const statusColor =
                exec.status === 'executed' ? 'bg-emerald-50 text-emerald-700'
                : exec.status === 'error' ? 'bg-red-50 text-red-700'
                : 'bg-slate-100 text-slate-600';

              return (
                <tr key={exec.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-[#0066cc]">{trigger}</td>
                  <td className="px-4 py-3 text-slate-700 capitalize">{exec.action_type.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ${statusColor}`}>
                      {exec.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600 truncate max-w-[150px]">{visitorName}</td>
                  <td
                    className="px-4 py-3 text-slate-400 text-xs"
                    title={exec.created_at ? new Date(exec.created_at).toLocaleString() : ''}
                  >
                    {exec.created_at ? formatRelativeTime(exec.created_at) : '-'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main Actions Page ──────────────────────────────────────────────

export default function ActionsPage() {
  const { activeTwin, isLoading: twinLoading, refreshTwins } = useTwin();
  const { patch } = useAuthFetch();
  const apiBase = resolveApiBaseUrl();

  const twinId = activeTwin?.id;
  const currentSettings = (activeTwin?.settings || {}) as Record<string, unknown>;
  const currentActions = (currentSettings.actions || []) as PersonaAction[];

  const [actions, setActions] = useState<PersonaAction[]>([]);
  const [executions, setExecutions] = useState<ActionExecution[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingAction, setEditingAction] = useState<PersonaAction | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync actions from twin settings (normalize old single-trigger format)
  useEffect(() => {
    const normalized = currentActions.map((a) => ({
      ...a,
      triggers: Array.isArray(a.triggers) && a.triggers.length > 0
        ? a.triggers
        : [a.trigger || '/'],
    }));
    setActions(normalized);
  }, [activeTwin]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch executions
  const fetchExecutions = useCallback(async () => {
    if (!twinId) return;
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/actions/${twinId}/executions`);
      if (res.ok) {
        const data = await res.json();
        setExecutions(data.executions || []);
      }
    } catch {
      // Non-critical
    }
  }, [apiBase, twinId]);

  useEffect(() => {
    if (twinId) void fetchExecutions();
  }, [twinId, fetchExecutions]);

  // Auto-refresh executions every 30 seconds
  useEffect(() => {
    if (!twinId || actions.length === 0) return;
    const interval = setInterval(() => void fetchExecutions(), 30000);
    return () => clearInterval(interval);
  }, [twinId, actions.length, fetchExecutions]);

  // Save actions to twins.settings.actions via PATCH
  const saveActions = async (updatedActions: PersonaAction[]) => {
    if (!twinId) return;
    setSaving(true);
    setError(null);
    try {
      const nextSettings = { ...currentSettings, actions: updatedActions };
      const res = await patch(`/twins/${twinId}`, { settings: nextSettings });
      if (!res.ok) {
        throw new Error(`Failed to save (${res.status})`);
      }
      setActions(updatedActions);
      await refreshTwins();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save actions';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleAddAction = (action: PersonaAction) => {
    const updated = [...actions, action];
    void saveActions(updated);
    setShowForm(false);
  };

  const handleEditAction = (action: PersonaAction) => {
    const updated = actions.map((a) => (a.id === action.id ? action : a));
    void saveActions(updated);
    setEditingAction(null);
  };

  const handleDeleteAction = (actionId: string) => {
    const updated = actions.filter((a) => a.id !== actionId);
    void saveActions(updated);
  };

  const handleToggleAction = (actionId: string) => {
    const updated = actions.map((a) =>
      a.id === actionId ? { ...a, is_active: !a.is_active } : a
    );
    void saveActions(updated);
  };

  // Loading state
  if (twinLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#0066cc] border-t-transparent" />
      </div>
    );
  }

  // No twin
  if (!twinId) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="text-center max-w-md p-8">
          <h2 className="text-2xl font-bold text-slate-900 mb-3">No Persona Found</h2>
          <p className="text-slate-500 mb-6">Create your persona first to set up actions.</p>
          <a
            href="/dashboard"
            className="inline-block rounded-full bg-[#0066cc] px-6 py-2.5 text-sm font-semibold text-white shadow-md shadow-[#0066cc]/25 transition-all hover:bg-[#0052a3]"
          >
            Go to Dashboard
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="-mx-4 min-h-[calc(100vh-8rem)] bg-[#f3f1ef] px-4 pb-16 pt-4 md:-mx-8 md:px-8 md:pt-8">
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-black tracking-tight text-slate-900">Actions</h1>
            <p className="text-sm text-slate-500">Let visitors do more than just chat</p>
          </div>
          {!showForm && !editingAction && (
            <button
              onClick={() => setShowForm(true)}
              className="rounded-full bg-[#0066cc] px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-[#0066cc]/25 transition-all hover:bg-[#0052a3]"
            >
              + Add Action
            </button>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
            <button onClick={() => setError(null)} className="ml-3 font-semibold underline">
              Dismiss
            </button>
          </div>
        )}

        {/* Saving indicator */}
        {saving && (
          <div className="flex items-center gap-2 text-sm text-[#0066cc]">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-[#0066cc] border-t-transparent" />
            Saving...
          </div>
        )}

        {/* Add Action Form */}
        {showForm && (
          <ActionForm
            initial={createEmptyAction()}
            onSave={handleAddAction}
            onCancel={() => setShowForm(false)}
          />
        )}

        {/* Edit Action Form */}
        {editingAction && (
          <ActionForm
            initial={editingAction}
            onSave={handleEditAction}
            onCancel={() => setEditingAction(null)}
          />
        )}

        {/* Actions List */}
        {actions.length === 0 && !showForm ? (
          <div className="rounded-2xl border border-white/60 bg-white/80 shadow-[0_4px_20px_rgba(15,23,42,0.04)] backdrop-blur-sm p-12 text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[#0066cc]/10 text-[#0066cc]">
              <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <h3 className="text-lg font-bold text-slate-900">No actions yet</h3>
            <p className="mt-2 text-sm text-slate-500 max-w-sm mx-auto">
              Actions let visitors book meetings, trigger webhooks, or get preset responses through your persona&apos;s chat.
            </p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-6 rounded-full bg-[#0066cc] px-6 py-2.5 text-sm font-semibold text-white shadow-md shadow-[#0066cc]/25 transition-all hover:bg-[#0052a3]"
            >
              Create Your First Action
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {actions.map((action) => (
              <ActionCard
                key={action.id}
                action={action}
                onToggle={() => handleToggleAction(action.id)}
                onEdit={() => setEditingAction(action)}
                onDelete={() => handleDeleteAction(action.id)}
              />
            ))}
          </div>
        )}

        {/* Recent Executions */}
        {actions.length > 0 && (
          <div className="pt-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-bold text-slate-900">Recent Executions</h2>
              <button
                onClick={() => void fetchExecutions()}
                className="rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-500 hover:bg-slate-100 transition-colors"
              >
                Refresh
              </button>
            </div>
            <ExecutionsTable executions={executions} />
          </div>
        )}
      </div>
    </div>
  );
}
