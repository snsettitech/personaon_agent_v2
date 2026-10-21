'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { resolveApiBaseUrl } from '@/lib/api';
import { useRouter } from 'next/navigation';

// ============================================================================
// Types
// ============================================================================

export type ProfileStatus = 'draft' | 'building' | 'ready' | 'needs_attention';

export interface Profile {
  id: string;  // twin_id internally
  name: string;  // Full name as display name
  headline?: string;
  role?: string;
  location?: string;
  expertise_tags?: string[];
  status: ProfileStatus;
  tenant_id: string;
  created_at: string;
  updated_at: string;
}

export interface BuildStatus {
  profile_id: string;
  status: 'pending' | 'building' | 'ready' | 'needs_attention' | 'failed';
  stage: string;
  progress_percent: number;
  stats: Record<string, any>;
  quality_tier?: 'strong' | 'with_gaps' | 'needs_review' | 'failed';
  last_updated_at?: string;
}

interface ProfileContextType {
  // Profile state
  profile: Profile | null;
  isLoading: boolean;
  error: string | null;
  
  // Build status
  buildStatus: BuildStatus | null;
  isPollingBuild: boolean;
  
  // Actions
  refreshProfile: () => Promise<void>;
  updateProfile: (data: Partial<Profile>) => Promise<void>;
  ensureProfileLoaded: () => Promise<Profile | null>;
  pollBuildStatus: (profileId?: string) => Promise<void>;
  stopPollingBuild: () => void;
}

const ProfileContext = createContext<ProfileContextType | undefined>(undefined);

// ============================================================================
// Provider Component
// ============================================================================

export function ProfileProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [buildStatus, setBuildStatus] = useState<BuildStatus | null>(null);
  const [isPollingBuild, setIsPollingBuild] = useState(false);
  
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const supabase = getSupabaseClient();
  const API_URL = resolveApiBaseUrl();

  // Get auth token
  const getToken = useCallback(async (): Promise<string | null> => {
    try {
      const { data } = await supabase.auth.getSession();
      return data?.session?.access_token || null;
    } catch {
      return null;
    }
  }, [supabase]);

  // ============================================================================
  // Profile Actions
  // ============================================================================

  const refreshProfile = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const token = await getToken();
      if (!token) {
        setError('Authentication required');
        setProfile(null);
        return;
      }

      const response = await fetch(`${API_URL}/profile`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (response.status === 404) {
        // No profile exists - this is a valid state
        setProfile(null);
        return;
      }

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Failed to fetch profile: ${response.status} - ${text}`);
      }

      const data = await response.json();
      setProfile(data);
    } catch (err: any) {
      console.error('[ProfileContext] refreshProfile error:', err);
      setError(err.message || 'Failed to load profile');
      setProfile(null);
    } finally {
      setIsLoading(false);
    }
  }, [API_URL, getToken]);

  const updateProfile = useCallback(async (data: Partial<Profile>) => {
    const token = await getToken();
    if (!token) throw new Error('Authentication required');

    const response = await fetch(`${API_URL}/profile`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Failed to update profile: ${text}`);
    }

    const updated = await response.json();
    setProfile(updated);
    return updated;
  }, [API_URL, getToken]);

  const ensureProfileLoaded = useCallback(async (): Promise<Profile | null> => {
    if (profile) return profile;
    if (!isLoading) await refreshProfile();
    return profile;
  }, [profile, isLoading, refreshProfile]);

  // ============================================================================
  // Build Status Polling
  // ============================================================================

  const pollBuildStatus = useCallback(async (profileId?: string) => {
    const targetId = profileId || profile?.id;
    if (!targetId) return;

    // Stop any existing polling
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    setIsPollingBuild(true);

    const fetchStatus = async () => {
      try {
        const token = await getToken();
        if (!token) return;

        const response = await fetch(`${API_URL}/profile/build-status`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!response.ok) return;

        const status: BuildStatus = await response.json();
        setBuildStatus(status);

        // Stop polling if build is complete or failed
        if (status.status === 'ready' || status.status === 'failed' || status.status === 'needs_attention') {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          setIsPollingBuild(false);
        }
      } catch (err) {
        console.error('[ProfileContext] pollBuildStatus error:', err);
      }
    };

    // Fetch immediately
    await fetchStatus();

    // Then poll every 3 seconds
    pollingRef.current = setInterval(fetchStatus, 3000);
  }, [API_URL, getToken, profile?.id]);

  const stopPollingBuild = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    setIsPollingBuild(false);
  }, []);

  // ============================================================================
  // Initial Load
  // ============================================================================

  useEffect(() => {
    refreshProfile();
  }, [refreshProfile]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  // ============================================================================
  // Route to onboarding if no profile
  // ============================================================================

  useEffect(() => {
    if (!isLoading && !profile && !error) {
      // Check if we're already on onboarding or auth pages
      const pathname = window.location.pathname;
      const isOnboarding = pathname.startsWith('/onboarding');
      const isAuth = pathname.startsWith('/auth');
      const isPublic = pathname.startsWith('/share');
      
      if (!isOnboarding && !isAuth && !isPublic) {
        router.push('/onboarding');
      }
    }
  }, [profile, isLoading, error, router]);

  // ============================================================================
  // Context Value
  // ============================================================================

  const value: ProfileContextType = {
    profile,
    isLoading,
    error,
    buildStatus,
    isPollingBuild,
    refreshProfile,
    updateProfile,
    ensureProfileLoaded,
    pollBuildStatus,
    stopPollingBuild
  };

  return (
    <ProfileContext.Provider value={value}>
      {children}
    </ProfileContext.Provider>
  );
}

// ============================================================================
// Hook
// ============================================================================

export function useProfile(): ProfileContextType {
  const context = useContext(ProfileContext);
  if (context === undefined) {
    throw new Error('useProfile must be used within a ProfileProvider');
  }
  return context;
}

// ============================================================================
// Utility: Create Profile (for onboarding)
// ============================================================================

export async function createProfile(data: {
  full_name: string;
  headline?: string;
  build_mode: 'with_links' | 'name_only';
}): Promise<Profile> {
  const supabase = getSupabaseClient();
  const API_URL = resolveApiBaseUrl();
  
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  
  if (!token) throw new Error('Authentication required');

  const response = await fetch(`${API_URL}/profile`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Failed to create profile: ${text}`);
  }

  return response.json();
}

// NOTE: onboarding uses the unified twin-scoped research pipeline
// (/twins/{id}/research) via StepResearch + researchApi.
