'use client';

import { useState, useEffect, useCallback } from 'react';

import { analytics } from '@/lib/analytics/events';
import { API_ENDPOINTS } from '@/lib/constants';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

interface MeetingNotificationPrefs {
  pre_meeting: boolean;
  post_meeting: boolean;
  weekly_digest: boolean;
}

interface LifecycleNotificationPrefs {
  product_education_enabled: boolean;
  daily_activity_enabled: boolean;
  weekly_report_enabled: boolean;
  hot_lead_alerts_enabled: boolean;
  timezone: string;
}

interface NotificationSettingsProps {
  twinId: string;
  meetingCount: number;
  initialMeetingPrefs?: Partial<MeetingNotificationPrefs>;
  onMeetingPrefsSaved?: () => Promise<void> | void;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const MEETING_TOGGLES: Array<{
  field: keyof MeetingNotificationPrefs;
  label: string;
  description: string;
}> = [
  {
    field: 'pre_meeting',
    label: 'Pre-meeting Briefings',
    description: 'Get a summary 30 minutes before each meeting with context from your sources.',
  },
  {
    field: 'post_meeting',
    label: 'Post-meeting Follow-ups',
    description: 'Receive a follow-up draft in your voice within 1 hour of each meeting ending.',
  },
  {
    field: 'weekly_digest',
    label: 'Weekly Digest',
    description: 'Every Monday: a summary of last week\'s meetings, action items, and upcoming prep.',
  },
];

const LIFECYCLE_TOGGLES: Array<{
  field: keyof Omit<LifecycleNotificationPrefs, 'timezone'>;
  category: 'product_education' | 'daily_activity' | 'weekly_report' | 'hot_lead_alert';
  label: string;
  description: string;
}> = [
  {
    field: 'product_education_enabled',
    category: 'product_education',
    label: 'Product Education',
    description: 'Tips for setup, publishing, sources, and better persona quality.',
  },
  {
    field: 'daily_activity_enabled',
    category: 'daily_activity',
    label: 'Daily Persona Activity',
    description: 'A daily summary when your persona had meaningful chats or leads.',
  },
  {
    field: 'weekly_report_enabled',
    category: 'weekly_report',
    label: 'Weekly Improvement Report',
    description: 'A weekly checklist of updates suggested by recent activity.',
  },
  {
    field: 'hot_lead_alerts_enabled',
    category: 'hot_lead_alert',
    label: 'Hot Lead Alerts',
    description: 'Email me when a website visitor shares contact information.',
  },
];

export default function NotificationSettings({
  twinId,
  meetingCount,
  initialMeetingPrefs,
  onMeetingPrefsSaved,
}: NotificationSettingsProps) {
  const [meetingPrefs, setMeetingPrefs] = useState<MeetingNotificationPrefs>({
    pre_meeting: true,
    post_meeting: true,
    weekly_digest: true,
  });
  const [lifecyclePrefs, setLifecyclePrefs] = useState<LifecycleNotificationPrefs>({
    product_education_enabled: true,
    daily_activity_enabled: true,
    weekly_report_enabled: true,
    hot_lead_alerts_enabled: true,
    timezone: 'UTC',
  });
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const meetingDisabled = meetingCount < 3;

  useEffect(() => {
    setMeetingPrefs({
      pre_meeting: initialMeetingPrefs?.pre_meeting ?? true,
      post_meeting: initialMeetingPrefs?.post_meeting ?? true,
      weekly_digest: initialMeetingPrefs?.weekly_digest ?? true,
    });
  }, [
    initialMeetingPrefs?.pre_meeting,
    initialMeetingPrefs?.post_meeting,
    initialMeetingPrefs?.weekly_digest,
  ]);

  useEffect(() => {
    let cancelled = false;

    async function loadLifecyclePrefs() {
      try {
        const res = await authFetchStandalone('/v2/notifications/preferences');
        if (!res.ok || cancelled) return;
        const body = await res.json() as { data?: Partial<LifecycleNotificationPrefs> };
        const saved = body.data || {};
        if (!cancelled) {
          setLifecyclePrefs({
            product_education_enabled: saved.product_education_enabled ?? true,
            daily_activity_enabled: saved.daily_activity_enabled ?? true,
            weekly_report_enabled: saved.weekly_report_enabled ?? true,
            hot_lead_alerts_enabled: saved.hot_lead_alerts_enabled ?? true,
            timezone: saved.timezone || 'UTC',
          });
        }
      } catch {
        // Leave defaults on load failure; save errors are surfaced below.
      }
    }

    void loadLifecyclePrefs();
    return () => { cancelled = true; };
  }, []);

  const handleMeetingToggle = useCallback(async (field: keyof MeetingNotificationPrefs) => {
    if (meetingDisabled) return;
    const prev = { ...meetingPrefs };
    const updated: MeetingNotificationPrefs = { ...meetingPrefs, [field]: !meetingPrefs[field] };
    setMeetingPrefs(updated);
    setSaveStatus('saving');
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(twinId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { meeting_notifications: updated } }),
      });
      if (!res.ok) {
        throw new Error(res.status === 401 ? 'session-expired' : 'save-failed');
      }
      analytics.notificationPreferencesUpdated({
        category: 'meeting',
        enabled: updated[field],
        source: 'settings',
      });
      await onMeetingPrefsSaved?.();
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch {
      setMeetingPrefs(prev);
      setSaveStatus('error');
    }
  }, [meetingPrefs, twinId, meetingDisabled, onMeetingPrefsSaved]);

  const handleLifecycleToggle = useCallback(async (
    field: keyof Omit<LifecycleNotificationPrefs, 'timezone'>,
    category: 'product_education' | 'daily_activity' | 'weekly_report' | 'hot_lead_alert',
  ) => {
    const prev = { ...lifecyclePrefs };
    const nextValue = !lifecyclePrefs[field];
    const updated: LifecycleNotificationPrefs = { ...lifecyclePrefs, [field]: nextValue };
    setLifecyclePrefs(updated);
    setSaveStatus('saving');
    try {
      const res = await authFetchStandalone('/v2/notifications/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: nextValue }),
      });
      if (!res.ok) {
        throw new Error('save-failed');
      }
      analytics.notificationPreferencesUpdated({
        category,
        enabled: nextValue,
        source: 'settings',
      });
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch {
      setLifecyclePrefs(prev);
      setSaveStatus('error');
    }
  }, [lifecyclePrefs]);

  function getSaveStatusText(): string {
    if (saveStatus === 'saving') return 'Saving...';
    if (saveStatus === 'saved') return 'Saved';
    if (saveStatus === 'error') return 'Failed to save. Please check your connection and try again.';
    return '';
  }

  return (
    <div
      className="rounded-3xl p-6 space-y-6"
      style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
    >
      <div>
        <h3 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
          Notification Preferences
        </h3>
        <p className="text-sm font-medium mt-1" style={{ color: 'var(--text-secondary)' }}>
          Choose which product, activity, lead, and meeting emails you receive.
        </p>
      </div>

      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-tertiary)' }}>
          Persona lifecycle
        </p>
        {LIFECYCLE_TOGGLES.map(({ field, category, label, description }) => {
          const value = lifecyclePrefs[field];
          return (
            <ToggleRow
              key={field}
              label={label}
              description={description}
              value={value}
              disabled={false}
              onToggle={() => { void handleLifecycleToggle(field, category); }}
            />
          );
        })}
      </div>

      <div className="space-y-3 border-t pt-5" style={{ borderColor: 'var(--border-subtle)' }}>
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-tertiary)' }}>
          Meeting intelligence
        </p>
        {MEETING_TOGGLES.map(({ field, label, description }) => {
          const value = meetingPrefs[field];
          return (
            <ToggleRow
              key={field}
              label={label}
              description={description}
              value={value}
              disabled={meetingDisabled}
              onToggle={() => { void handleMeetingToggle(field); }}
            />
          );
        })}
      </div>

      {meetingDisabled && (
        <p className="text-xs font-medium mt-3" style={{ color: 'var(--text-muted)' }}>
          Meeting emails activate after your first 3 meetings.
        </p>
      )}

      {saveStatus !== 'idle' && (
        <p
          className="text-xs font-medium mt-3"
          style={{ color: saveStatus === 'error' ? 'var(--accent-red)' : 'var(--text-muted)' }}
        >
          {getSaveStatusText()}
        </p>
      )}
    </div>
  );
}

function ToggleRow({
  label,
  description,
  value,
  disabled,
  onToggle,
}: {
  label: string;
  description: string;
  value: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className="flex items-center justify-between gap-4 p-4 rounded-xl"
      style={{ backgroundColor: 'var(--bg-surface)' }}
    >
      <div>
        <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          {label}
        </p>
        <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>
          {description}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        disabled={disabled}
        onClick={onToggle}
        className={`h-6 w-12 shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)] focus:ring-offset-2 ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        style={{
          backgroundColor: value ? 'var(--primary-500)' : 'var(--bg-elevated)',
          border: value ? 'none' : '1px solid var(--border-default)',
        }}
      >
        <div
          className={`h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${value ? 'translate-x-6' : 'translate-x-0.5'}`}
        />
      </button>
    </div>
  );
}
