'use client';

import { useEffect, useState } from 'react';
import { API_BASE_URL } from '@/lib/constants';

interface VersionInfo {
  git_sha: string;
  build_time: string;
  environment: 'development' | 'staging' | 'production';
  service: string;
  version: string;
}

export function EnvironmentBadge() {
  const [version, setVersion] = useState<VersionInfo | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Keep the dashboard chrome clean by default. The badge is an opt-in
    // diagnostic surface for local/staging debugging.
    const shouldShow = process.env.NEXT_PUBLIC_SHOW_ENV_BADGE === 'true';
    
    if (!shouldShow) return;

    const fetchVersion = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/version`, {
          signal: AbortSignal.timeout(3000)
        });
        if (res.ok) {
          const data = await res.json();
          setVersion(data);
          setIsVisible(true);
        }
      } catch {
        // Silently fail - badge is optional
      }
    };

    fetchVersion();
  }, []);

  if (!isVisible || !version) return null;

  const getBadgeStyles = () => {
    switch (version.environment) {
      case 'production':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'staging':
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'development':
      default:
        return 'bg-blue-100 text-blue-800 border-blue-200';
    }
  };

  const getLabel = () => {
    switch (version.environment) {
      case 'production':
        return 'PROD';
      case 'staging':
        return 'STAGING';
      case 'development':
      default:
        return 'DEV';
    }
  };

  return (
    <div 
      className={`fixed top-4 right-4 z-50 px-3 py-1.5 rounded-full text-xs font-bold border shadow-sm ${getBadgeStyles()}`}
      title={`${version.environment} • ${version.git_sha?.slice(0, 7) || 'unknown'} • ${new Date(version.build_time).toLocaleDateString()}`}
    >
      <span className="uppercase tracking-wider">{getLabel()}</span>
      <span className="ml-2 opacity-75 font-mono">
        {version.git_sha?.slice(0, 7)}
      </span>
    </div>
  );
}
