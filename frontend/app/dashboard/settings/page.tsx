'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { getSupabaseClient } from '@/lib/supabase/client';
import { useTwin } from '@/lib/context/TwinContext';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import { resolveApiBaseUrl } from '@/lib/api';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import DeleteTwinModal from '@/components/ui/DeleteTwinModal';
import { useToast } from '@/components/ui';
import VoiceSettings from '@/components/settings/VoiceSettings';
import NotificationSettings from '@/components/settings/NotificationSettings';

interface UserProfile {
  name: string;
  email: string;
  avatarUrl: string;
}

interface TwinSettings {
  tone: string;
  responseLength: string;
  firstPerson: boolean;
}

type TabId = 'profile' | 'twin' | 'voice' | 'notifications' | 'danger';

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' as const } },
};

const tabContent: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.25, ease: 'easeOut' as const } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.15 } },
};

const tabs: Tab[] = [
  {
    id: 'profile',
    label: 'Account',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0" />
      </svg>
    ),
  },
  {
    id: 'twin',
    label: 'Persona Behavior',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      </svg>
    ),
  },
  {
    id: 'voice',
    label: 'Voice',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
      </svg>
    ),
  },
  {
    id: 'notifications',
    label: 'Notifications',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
    ),
  },
  {
    id: 'danger',
    label: 'Danger',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
      </svg>
    ),
  },
];

const API_URL = resolveApiBaseUrl();

export default function SettingsPage() {
  const { activeTwin, user, refreshTwins, isLoading: twinLoading, clearActiveTwin } = useTwin();
  const supabase = getSupabaseClient();
  const { showToast } = useToast();
  const searchParams = useSearchParams();

  const [activeTab, setActiveTab] = useState<TabId>('profile');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [showResetModal, setShowResetModal] = useState(false);
  const [twinActionLoading, setTwinActionLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const router = useRouter();
  const activeTwinId = activeTwin?.id;

  useEffect(() => {
    const requestedTab = searchParams.get('tab');
    if (requestedTab && tabs.some((tab) => tab.id === requestedTab)) {
      setActiveTab(requestedTab as TabId);
    }
  }, [searchParams]);

  // Empty defaults - will be populated from activeTwin
  const [profile, setProfile] = useState<UserProfile>({
    name: '',
    email: '',
    avatarUrl: ''
  });

  // Password change state
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);

  // Empty defaults - will be populated from activeTwin.settings
  const [twinSettings, setTwinSettings] = useState<TwinSettings>({
    tone: 'friendly',
    responseLength: 'balanced',
    firstPerson: true
  });

  // Meeting count — used to gate notification toggles (disabled when < 3)
  const [meetingCount, setMeetingCount] = useState(0);

  // Lead capture settings
  const [leadCaptureEnabled, setLeadCaptureEnabled] = useState(false);
  const [valueFrame, setValueFrame] = useState('interest');
  const [bookingUrl, setBookingUrl] = useState('');
  const [captureSaving, setCaptureSaving] = useState(false);
  const [captureSaved, setCaptureSaved] = useState(false);

  // Handle password change
  const handlePasswordChange = async () => {
    if (!newPassword.trim()) {
      showToast('Please enter a new password', 'error');
      return;
    }
    if (newPassword.length < 8) {
      showToast('Password must be at least 8 characters', 'error');
      return;
    }
    if (newPassword !== confirmPassword) {
      showToast('Passwords do not match', 'error');
      return;
    }

    setChangingPassword(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) {
        console.error('[Settings] Password change error:', error);
        showToast(error.message || 'Failed to change password', 'error');
        return;
      }
      showToast('Password changed successfully', 'success');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      console.error('[Settings] Password error:', err);
      showToast('Failed to change password', 'error');
    } finally {
      setChangingPassword(false);
    }
  };

  // Initialize from activeTwin when it changes
  useEffect(() => {
    if (activeTwin) {
      const settings = (activeTwin.settings || {}) as Record<string, unknown>;
      const personality = (settings.personality || {}) as Record<string, unknown>;

      setTwinSettings({
        tone: (personality.tone as string) || 'friendly',
        responseLength: (personality.responseLength as string) || 'balanced',
        firstPerson: personality.firstPerson !== false
      });
      setLeadCaptureEnabled(settings.lead_capture_enabled === true);
      setValueFrame((settings.value_frame as string) || 'interest');
      const widgetUi = (settings.widget_ui || {}) as Record<string, unknown>;
      setBookingUrl((widgetUi.booking_url as string) || '');
      setSettingsLoaded(true);
    }
  }, [activeTwin]); // Re-run when twin switches or settings refresh

  // Initialize profile from user
  useEffect(() => {
    if (user) {
      setProfile({
        name: user.full_name || '',
        email: user.email || '',
        avatarUrl: user.avatar_url || ''
      });
    }
  }, [user]);

  // Fetch meeting count for notification gate (disabled when < 3 meetings)
  useEffect(() => {
    if (!activeTwinId) return;
    let cancelled = false;

    async function fetchMeetingCount() {
      try {
        const res = await authFetchStandalone(`${API_URL}/v2/meetings?twin_id=${activeTwinId}&limit=1&count=true`);
        if (!res.ok || cancelled) return;
        const body = await res.json() as { count?: number };
        if (!cancelled) {
          setMeetingCount(body.count ?? 0);
        }
      } catch {
        // Default 0 is conservative — keeps toggles disabled rather than enabling prematurely
      }
    }

    void fetchMeetingCount();
    return () => { cancelled = true; };
  }, [activeTwinId]);

  // Real PATCH save with TwinContext refresh
  const handleSave = async () => {
    if (!activeTwin) return;

    setSaving(true);
    try {
      const response = await authFetchStandalone(`${API_URL}/twins/${activeTwin.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          settings: {
            personality: {
              tone: twinSettings.tone,
              responseLength: twinSettings.responseLength,
              firstPerson: twinSettings.firstPerson,
            },
          },
        }),
      });

      if (response.ok) {
        // Refresh TwinContext so header + other pages reflect changes
        await refreshTwins();
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
        showToast('Settings saved', 'success');
      } else {
        const errText = await response.text();
        console.error('[Settings] Save failed:', errText);
        showToast('Failed to save settings', 'error');
      }
    } catch (error) {
      console.error('[Settings] Error saving:', error);
      showToast('Failed to save settings', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleCaptureSave = async () => {
    if (!activeTwin) return;
    setCaptureSaving(true);
    try {
      const body: Record<string, unknown> = { lead_capture_enabled: leadCaptureEnabled };
      if (valueFrame) body.value_frame = valueFrame;
      if (bookingUrl !== undefined) body.booking_url = bookingUrl;
      const response = await authFetchStandalone(`${API_URL}/profile`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      if (response.ok) {
        await refreshTwins();
        setCaptureSaved(true);
        setTimeout(() => setCaptureSaved(false), 2000);
        showToast('Capture settings saved', 'success');
      } else {
        const errText = await response.text();
        console.error('[Settings] Capture save failed:', errText);
        showToast('Failed to save capture settings', 'error');
      }
    } catch (err) {
      console.error('[Settings] Capture save error:', err);
      showToast('Failed to save capture settings', 'error');
    } finally {
      setCaptureSaving(false);
    }
  };

  // Reset profile handler (single-profile mode)
  const handleResetProfile = async (_permanent: boolean): Promise<void> => {
    if (!activeTwin) throw new Error('No active persona');
    setTwinActionLoading(true);

    try {
      const response = await authFetchStandalone(`${API_URL}/profile/reset`, { method: 'POST' });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' })) as { detail?: string };
        showToast(errorData.detail || 'Failed to delete persona', 'error');
        throw new Error(errorData.detail || 'Failed to delete persona');
      }

      await refreshTwins({ allowEmpty: true });
      try {
        localStorage.removeItem('activeTwinId');
      } catch {
        // Ignore storage errors.
      }
      clearActiveTwin();
      showToast('Profile reset. Start onboarding again.', 'success');
      router.push('/onboarding');
    } finally {
      setTwinActionLoading(false);
    }
  };

  // Export twin handler
  const handleExportTwin = async () => {
    if (!activeTwin) {
      showToast('No persona selected', 'warning');
      return;
    }

    try {
      setExporting(true);
      const response = await authFetchStandalone(`${API_URL}/twins/${activeTwin.id}/export`);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' })) as { detail?: string };
        showToast(`Export failed: ${errorData.detail}`, 'error');
        return;
      }

      // Trigger download
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `persona_${activeTwin.id}_export.json`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      showToast('Persona export downloaded', 'success');
    } catch (error) {
      console.error('[Settings] Export error:', error);
      showToast('Failed to export persona', 'error');
    } finally {
      setExporting(false);
    }
  };

  // Delete account handler
  const [showDeleteAccountModal, setShowDeleteAccountModal] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState('');
  const [deletingAccount, setDeletingAccount] = useState(false);

  const handleDeleteAccount = async () => {
    if (deleteConfirmation !== 'DELETE' && deleteConfirmation !== user?.email) {
      showToast('Please type DELETE or your email to confirm', 'warning');
      return;
    }

    setDeletingAccount(true);
    try {
      const response = await authFetchStandalone(`${API_URL}/account/delete`, {
        method: 'POST',
        body: JSON.stringify({ confirmation: deleteConfirmation }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' })) as { detail?: string };
        showToast(`Account deletion failed: ${errorData.detail}`, 'error');
        return;
      }

      // Show success before signing out + redirecting
      showToast('Account deleted', 'success');
      await new Promise((resolve) => setTimeout(resolve, 400));
      await supabase.auth.signOut();
      clearActiveTwin();
      router.push('/');
    } catch (error) {
      console.error('[Settings] Delete account error:', error);
      showToast('Failed to delete account', 'error');
    } finally {
      setDeletingAccount(false);
    }
  };

  const initialMeetingPrefs = ((activeTwin?.settings as Record<string, unknown> | undefined)?.meeting_notifications
    || {}) as {
      pre_meeting?: boolean;
      post_meeting?: boolean;
      weekly_digest?: boolean;
    };

  // Loading state
  if (twinLoading || (activeTab === 'twin' && !settingsLoaded && activeTwin)) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <div
            className="w-12 h-12 border-4 rounded-full animate-spin mx-auto mb-4"
            style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
          />
          <p style={{ color: 'var(--text-muted)' }}>Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={fadeUp} className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>Settings</h1>
        <p className="mt-1" style={{ color: 'var(--text-muted)' }}>Manage account access and customer-facing persona controls.</p>
      </div>

      {/* Tab navigation */}
      <div className="flex gap-1 overflow-x-auto" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="flex shrink-0 items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors"
            style={{
              borderColor: activeTab === tab.id ? 'var(--primary-600)' : 'transparent',
              color: activeTab === tab.id ? 'var(--primary-600)' : 'var(--text-muted)',
            }}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      <AnimatePresence mode="wait">
        {activeTab === 'profile' && (
          <motion.div key="profile" initial="hidden" animate="visible" exit="exit" variants={tabContent}>
            <div
              className="rounded-3xl p-6 space-y-6"
              style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
            >
              <div>
                <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Account</h2>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                  These details come from your sign-in account.
                </p>
              </div>

              <div className="flex items-center gap-6">
                <div className="w-20 h-20 rounded-full flex items-center justify-center text-2xl font-bold text-white overflow-hidden">
                  {profile.avatarUrl ? (
                    <img src={profile.avatarUrl} alt="Profile photo" className="w-full h-full object-cover" />
                  ) : (
                    <div
                      className="w-full h-full flex items-center justify-center"
                      style={{ background: 'linear-gradient(135deg, var(--primary-500), var(--primary-600))' }}
                    >
                      {(profile.name || profile.email || 'P').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()}
                    </div>
                  )}
                </div>
                <div>
                  <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Profile photo</p>
                  <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
                    Shown from your account profile.
                  </p>
                </div>
              </div>

              <div className="grid md:grid-cols-2 gap-6">
                <div
                  className="rounded-2xl p-4"
                  style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
                >
                  <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>Name</p>
                  <p className="mt-2 font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {profile.name || 'Not set'}
                  </p>
                </div>
                <div
                  className="rounded-2xl p-4"
                  style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
                >
                  <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>Email</p>
                  <p className="mt-2 font-semibold break-all" style={{ color: 'var(--text-primary)' }}>
                    {profile.email || 'Not set'}
                  </p>
                </div>
                <div
                  className="rounded-2xl p-4"
                  style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
                >
                  <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>Sign-in</p>
                  <p className="mt-2 font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {profile.email ? 'Email account' : 'Account provider'}
                  </p>
                </div>
              </div>

              <div
                className="flex flex-col gap-4 rounded-2xl p-5 sm:flex-row sm:items-center sm:justify-between"
                style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
              >
                <div>
                  <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Persona profile</p>
                  <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                    Edit your bio, experience, expertise, and public profile in Review Profile.
                  </p>
                </div>
                <Link
                  href="/dashboard/profile"
                  className="inline-flex items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold text-white transition-colors"
                  style={{ backgroundColor: 'var(--primary-600)' }}
                >
                  Open Review Profile
                </Link>
              </div>

              {/* Password */}
              <div className="pt-6" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <h3 className="font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>Change Password</h3>
                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>New Password</label>
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-4 py-3 rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                      style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>Confirm Password</label>
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-4 py-3 rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                      style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
                    />
                  </div>
                </div>
                <button
                  onClick={handlePasswordChange}
                  disabled={changingPassword || !newPassword.trim()}
                  className="mt-4 px-4 py-2 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                  style={{ backgroundColor: 'var(--primary-600)' }}
                >
                  {changingPassword ? 'Updating...' : 'Update Password'}
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {activeTab === 'twin' && (
          <motion.div key="twin" initial="hidden" animate="visible" exit="exit" variants={tabContent}>
            <div
              className="rounded-3xl p-6 space-y-6"
              style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
            >
              <div>
                <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Persona Behavior</h2>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                  Tune how your persona speaks. Edit facts and bio in Review Profile.
                </p>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <Link
                  href="/dashboard/profile"
                  className="rounded-2xl p-4 transition-colors"
                  style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
                >
                  <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Review Profile</p>
                  <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                    Update bio, experience, education, and expertise.
                  </p>
                </Link>
                <Link
                  href="/dashboard/share"
                  className="rounded-2xl p-4 transition-colors"
                  style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
                >
                  <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Publish</p>
                  <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                    Manage the public persona link and sharing options.
                  </p>
                </Link>
              </div>

              <div className="pt-6" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <h3 className="font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>Response style</h3>
                <div className="grid md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>Tone</label>
                    <select
                      value={twinSettings.tone}
                      onChange={(e) => setTwinSettings({ ...twinSettings, tone: e.target.value })}
                      className="w-full px-4 py-3 rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                      style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
                    >
                      <option value="professional">Professional</option>
                      <option value="friendly">Friendly</option>
                      <option value="casual">Casual</option>
                      <option value="technical">Technical</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>Response Length</label>
                    <select
                      value={twinSettings.responseLength}
                      onChange={(e) => setTwinSettings({ ...twinSettings, responseLength: e.target.value })}
                      className="w-full px-4 py-3 rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                      style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
                    >
                      <option value="concise">Concise</option>
                      <option value="balanced">Balanced</option>
                      <option value="detailed">Detailed</option>
                    </select>
                  </div>
                </div>

                {/* First Person Toggle */}
                <div
                  className="mt-4 flex items-center justify-between p-4 rounded-xl"
                  style={{ backgroundColor: 'var(--bg-surface)' }}
                >
                  <div>
                    <p className="font-medium" style={{ color: 'var(--text-primary)' }}>Speak as &ldquo;I&rdquo;</p>
                    <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Use first person pronouns</p>
                  </div>
                  <button
                    onClick={() => setTwinSettings({ ...twinSettings, firstPerson: !twinSettings.firstPerson })}
                    className="w-12 h-6 rounded-full transition-colors"
                    style={{ backgroundColor: twinSettings.firstPerson ? 'var(--primary-500)' : 'var(--bg-elevated)' }}
                  >
                    <div
                      className={`w-5 h-5 bg-white rounded-full shadow-sm transition-transform ${twinSettings.firstPerson ? 'translate-x-6' : 'translate-x-0.5'}`}
                    />
                  </button>
                </div>
              </div>

              <div className="pt-6" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <div className="flex items-center justify-between mb-1">
                  <h3 className="font-semibold" style={{ color: 'var(--text-primary)' }}>Lead Capture</h3>
                  <button
                    onClick={() => setLeadCaptureEnabled(!leadCaptureEnabled)}
                    className="w-12 h-6 rounded-full transition-colors shrink-0"
                    style={{ backgroundColor: leadCaptureEnabled ? 'var(--primary-500)' : 'var(--bg-elevated)' }}
                  >
                    <div
                      className={`w-5 h-5 bg-white rounded-full shadow-sm transition-transform ${leadCaptureEnabled ? 'translate-x-6' : 'translate-x-0.5'}`}
                    />
                  </button>
                </div>
                <p className="text-sm mb-4" style={{ color: 'var(--text-muted)' }}>
                  Collect visitor contact info during conversations on your public persona page.
                </p>

                {leadCaptureEnabled && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>Offer framing</label>
                      <select
                        value={valueFrame}
                        onChange={(e) => setValueFrame(e.target.value)}
                        className="w-full px-4 py-3 rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                        style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
                      >
                        <option value="interest">Stay in touch</option>
                        <option value="lead">Schedule a conversation</option>
                        <option value="opportunity">Explore opportunities</option>
                        <option value="inquiry">Send an inquiry</option>
                        <option value="collaboration">Discuss collaboration</option>
                      </select>
                      <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                        Controls the offer your persona makes when a visitor shows engagement.
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                        Booking / meeting link <span style={{ color: 'var(--text-muted)' }}>(optional)</span>
                      </label>
                      <input
                        type="url"
                        value={bookingUrl}
                        onChange={(e) => setBookingUrl(e.target.value)}
                        placeholder="https://cal.com/yourname"
                        className="w-full px-4 py-3 rounded-xl transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                        style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
                      />
                      <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                        Included when the persona offers to book a meeting. Leave blank to omit.
                      </p>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between mt-4">
                  <Link href="/dashboard/widget/leads" className="text-sm font-medium" style={{ color: 'var(--primary-600)' }}>
                    View leads →
                  </Link>
                  <button
                    onClick={handleCaptureSave}
                    disabled={captureSaving}
                    className="px-4 py-2 font-semibold text-sm rounded-xl text-white transition-all disabled:opacity-50"
                    style={{ backgroundColor: captureSaved ? 'var(--accent-emerald)' : 'var(--primary-600)' }}
                  >
                    {captureSaving ? 'Saving…' : captureSaved ? 'Saved!' : 'Save'}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}

        {activeTab === 'voice' && activeTwin && (
          <motion.div key="voice" initial="hidden" animate="visible" exit="exit" variants={tabContent}>
            <VoiceSettings twinId={activeTwin.id} twinName={formatPersonaDisplayName(activeTwin.name)} />
          </motion.div>
        )}

        {activeTab === 'notifications' && activeTwin && (
          <motion.div key="notifications" initial="hidden" animate="visible" exit="exit" variants={tabContent}>
            <NotificationSettings
              twinId={activeTwin.id}
              meetingCount={meetingCount}
              initialMeetingPrefs={initialMeetingPrefs}
              onMeetingPrefsSaved={refreshTwins}
            />
          </motion.div>
        )}

        {activeTab === 'danger' && (
          <motion.div key="danger" initial="hidden" animate="visible" exit="exit" variants={tabContent}>
            {/* Keep red border for danger zone — intentionally semantic */}
            <div className="rounded-3xl p-6 space-y-6" style={{ border: '1px solid #FECACA' }}>
              <h2 className="text-lg font-bold text-red-600">Danger Zone</h2>
              <p style={{ color: 'var(--text-secondary)' }}>These actions are permanent and cannot be undone.</p>

              <div className="space-y-4">
                <div className="p-4 border border-red-200 rounded-xl flex items-center justify-between">
                  <div>
                    <p className="font-medium" style={{ color: 'var(--text-primary)' }}>Export Data</p>
                    <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Download all your persona&apos;s data</p>
                  </div>
                  <button
                    onClick={handleExportTwin}
                    disabled={!activeTwin || exporting}
                    className="px-4 py-2 font-medium text-sm rounded-xl transition-colors disabled:opacity-50"
                    style={{
                      border: '1px solid var(--border-subtle)',
                      color: 'var(--text-secondary)',
                      backgroundColor: 'transparent',
                    }}
                  >
                    {exporting ? 'Exporting...' : 'Export'}
                  </button>
                </div>
                <div className="p-4 border border-red-200 rounded-xl flex items-center justify-between">
                  <div>
                    <p className="font-medium" style={{ color: 'var(--text-primary)' }}>Reset Profile</p>
                    <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Clear profile sources and restart onboarding (account stays)</p>
                  </div>
                  <button
                    onClick={() => setShowResetModal(true)}
                    disabled={!activeTwin || twinActionLoading}
                    className="px-4 py-2 bg-red-500 text-white font-medium text-sm rounded-xl hover:bg-red-600 transition-colors disabled:opacity-50"
                  >
                    {twinActionLoading ? 'Working...' : 'Reset'}
                  </button>
                </div>
                <div className="p-4 border border-red-200 rounded-xl flex items-center justify-between">
                  <div>
                    <p className="font-medium" style={{ color: 'var(--text-primary)' }}>Delete Account</p>
                    <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Full account closure and compliance-level data deletion</p>
                  </div>
                  <button
                    onClick={() => setShowDeleteAccountModal(true)}
                    className="px-4 py-2 bg-red-600 text-white font-medium text-sm rounded-xl hover:bg-red-700 transition-colors"
                  >
                    Delete Account
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Save Button */}
      {activeTab === 'twin' && (
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-3 font-semibold text-sm rounded-xl text-white transition-all disabled:opacity-50"
            style={{ backgroundColor: saved ? 'var(--accent-emerald)' : 'var(--primary-600)' }}
          >
            {saving ? 'Saving...' : saved ? 'Saved!' : 'Save Changes'}
          </button>
        </div>
      )}

      {/* Reset Profile Modal */}
      <DeleteTwinModal
        isOpen={showResetModal}
        onClose={() => setShowResetModal(false)}
        onDelete={handleResetProfile}
        twinName={formatPersonaDisplayName(activeTwin?.name)}
        twinHandle={(activeTwin?.settings as Record<string, string> | undefined)?.handle || ''}
        twinId={activeTwin?.id || ''}
      />

      {/* Delete Account Modal */}
      {showDeleteAccountModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div
            className="rounded-2xl p-6 max-w-md w-full mx-4 shadow-xl"
            style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
          >
            <h2 className="text-xl font-bold text-red-600 mb-2">Delete Account</h2>
            <p className="mb-4" style={{ color: 'var(--text-secondary)' }}>
              This will close your account and permanently delete profile data where possible.
              Any blocked records will be archived pending cleanup.
            </p>
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
              <p className="text-sm text-red-700">
                <strong>Warning:</strong> This action is irreversible and may take time to fully complete.
              </p>
            </div>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                Type <strong>DELETE</strong> or your email to confirm:
              </label>
              <input
                type="text"
                value={deleteConfirmation}
                onChange={(e) => setDeleteConfirmation(e.target.value)}
                placeholder="DELETE"
                className="w-full px-3 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-red-500"
                style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowDeleteAccountModal(false);
                  setDeleteConfirmation('');
                }}
                className="flex-1 px-4 py-2 rounded-lg transition-colors"
                style={{ border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)', backgroundColor: 'transparent' }}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deletingAccount || (deleteConfirmation !== 'DELETE' && deleteConfirmation !== user?.email)}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {deletingAccount ? 'Deleting...' : 'Delete Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
