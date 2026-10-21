'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';

export interface FeatureFlags {
    // Cognitive UX Features
    cognitiveMode: boolean;
    splitBrainLayout: boolean;
    knowledgeGraphPreview: boolean;

    // Premium Features
    advancedAnalytics: boolean;
    customBranding: boolean;
    teamCollaboration: boolean;

    // Experimental Features
    voiceCloning: boolean;
    realTimeSync: boolean;
    aiSuggestions: boolean;

    // Privacy & Publish Controls
    privacyControls: boolean;
    publishControls: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
    // Cognitive UX - enabled by default for new premium flow
    cognitiveMode: true,
    splitBrainLayout: true,
    knowledgeGraphPreview: true,

    // Premium Features - disabled by default
    advancedAnalytics: false,
    customBranding: false,
    teamCollaboration: false,

    // Experimental - disabled by default
    voiceCloning: false,
    realTimeSync: false,
    aiSuggestions: false,

    // Privacy & Publish Controls - enabled by default
    privacyControls: true,
    publishControls: true,
};

interface FeatureFlagContextType {
    flags: FeatureFlags;
    isEnabled: (flag: keyof FeatureFlags) => boolean;
    setFlag: (flag: keyof FeatureFlags, value: boolean) => void;
    toggleFlag: (flag: keyof FeatureFlags) => void;
    resetFlags: () => void;
}

const FeatureFlagContext = createContext<FeatureFlagContextType | undefined>(undefined);

const STORAGE_KEY = 'vdt_feature_flags';

function getInitialFlags(): FeatureFlags {
    if (typeof window === 'undefined') {
        return DEFAULT_FLAGS;
    }
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
            const parsed = JSON.parse(stored);
            return { ...DEFAULT_FLAGS, ...parsed };
        }
    } catch {
        // Ignore parsing errors
    }
    return DEFAULT_FLAGS;
}

export function FeatureFlagProvider({ children }: { children: React.ReactNode }) {
    const [flags, setFlags] = useState<FeatureFlags>(DEFAULT_FLAGS);
    const [isHydrated, setIsHydrated] = useState(false);

    // Hydrate from localStorage after mount
    useEffect(() => {
        const storedFlags = getInitialFlags();
        setFlags(storedFlags);
        setIsHydrated(true);
    }, []);

    // Persist flags to localStorage when they change
    useEffect(() => {
        if (isHydrated && typeof window !== 'undefined') {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(flags));
        }
    }, [flags, isHydrated]);

    const isEnabled = useCallback((flag: keyof FeatureFlags) => {
        return flags[flag] ?? false;
    }, [flags]);

    const setFlag = useCallback((flag: keyof FeatureFlags, value: boolean) => {
        setFlags(currentFlags => ({ ...currentFlags, [flag]: value }));
    }, []);

    const toggleFlag = useCallback((flag: keyof FeatureFlags) => {
        setFlags(currentFlags => ({ ...currentFlags, [flag]: !currentFlags[flag] }));
    }, []);

    const resetFlags = useCallback(() => {
        setFlags(DEFAULT_FLAGS);
    }, []);

    const contextValue = useMemo(() => ({
        flags,
        isEnabled,
        setFlag,
        toggleFlag,
        resetFlags
    }), [flags, isEnabled, setFlag, toggleFlag, resetFlags]);

    return (
        <FeatureFlagContext.Provider value={contextValue}>
            {children}
        </FeatureFlagContext.Provider>
    );
}

export function useFeatureFlags() {
    const context = useContext(FeatureFlagContext);
    if (!context) {
        throw new Error('useFeatureFlags must be used within a FeatureFlagProvider');
    }
    return context;
}

// Convenience hook for checking a single flag
export function useFeatureFlag(flag: keyof FeatureFlags): boolean {
    const { isEnabled } = useFeatureFlags();
    return isEnabled(flag);
}

export default FeatureFlagProvider;
