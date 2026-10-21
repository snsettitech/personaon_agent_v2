'use client';

import React from 'react';

interface PublicProfile {
  name?: string;
  occupation?: string;
  bio?: string;
  headline?: string;
  areas_of_expertise?: string[];
  key_achievements?: string[];
  work_experience?: Array<{
    company?: string;
    role?: string;
    description?: string;
    start_year?: number;
    end_year?: number;
  }>;
  education?: Array<{
    institution?: string;
    degree?: string;
    field?: string;
    end_year?: number;
  }>;
  social_links?: Record<string, string>;
  image_url?: string;
  avatar_url?: string;
  suggested_questions?: string[];
}

interface ProfileDrawerProps {
  profile: PublicProfile;
  isOpen: boolean;
  onClose: () => void;
}

const SAFE_URL_PROTOCOLS = new Set(['http:', 'https:']);

function sanitizeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return SAFE_URL_PROTOCOLS.has(parsed.protocol) ? url : undefined;
  } catch {
    return undefined;
  }
}

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function socialLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
}

export function ProfileDrawer({ profile, isOpen, onClose }: ProfileDrawerProps) {
  const avatarSrc = profile.image_url || profile.avatar_url;
  const displayName = profile.name ?? '';
  const headline = profile.occupation || profile.headline || '';

  const drawerContent = (
    <div className="p-6 space-y-6">
      {/* Avatar + Name + Headline */}
      <div className="flex items-start gap-4">
        {avatarSrc ? (
          <img
            src={avatarSrc}
            alt={displayName}
            className="w-16 h-16 rounded-full object-cover shrink-0"
          />
        ) : (
          <div
            className="w-16 h-16 rounded-full flex items-center justify-center shrink-0 text-xl font-semibold"
            style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
          >
            {getInitials(displayName) || 'P'}
          </div>
        )}
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold font-sans" style={{ color: 'var(--text-primary)' }}>
            {displayName}
          </h2>
          {headline && (
            <p className="text-base font-normal font-sans mt-1" style={{ color: 'var(--text-secondary)' }}>
              {headline}
            </p>
          )}
        </div>
      </div>

      {/* Areas of Expertise */}
      {profile.areas_of_expertise && profile.areas_of_expertise.length > 0 && (
        <div>
          <h3
            className="text-sm font-semibold uppercase tracking-wider font-sans mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            Areas of Expertise
          </h3>
          <div className="flex flex-wrap gap-2">
            {profile.areas_of_expertise.map((area) => (
              <span
                key={area}
                className="text-sm font-sans px-3 py-1 rounded-full"
                style={{
                  color: 'var(--text-link)',
                  backgroundColor: 'rgba(37,99,235,0.12)',
                  borderRadius: 'var(--radius-full)',
                }}
              >
                {area}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Bio */}
      {profile.bio && (
        <div>
          <h3
            className="text-sm font-semibold uppercase tracking-wider font-sans mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            About
          </h3>
          <p
            className="text-base font-normal font-sans leading-relaxed"
            style={{ color: 'var(--text-primary)', lineHeight: '1.625' }}
          >
            {profile.bio}
          </p>
        </div>
      )}

      {/* Key Achievements */}
      {profile.key_achievements && profile.key_achievements.length > 0 && (
        <div>
          <h3
            className="text-sm font-semibold uppercase tracking-wider font-sans mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            Key Achievements
          </h3>
          <ul className="list-disc list-inside space-y-1">
            {profile.key_achievements.map((achievement) => (
              <li
                key={achievement}
                className="text-sm font-normal font-sans"
                style={{ color: 'var(--text-primary)' }}
              >
                {achievement}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Work Experience */}
      {profile.work_experience && profile.work_experience.length > 0 && (
        <div>
          <h3
            className="text-sm font-semibold uppercase tracking-wider font-sans mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            Experience
          </h3>
          <div className="space-y-3">
            {profile.work_experience.map((entry, index) => (
              <div key={`work-${index}`}>
                <p className="text-sm font-semibold font-sans" style={{ color: 'var(--text-primary)' }}>
                  {entry.role || 'Role'}
                </p>
                {entry.company && (
                  <p className="text-sm font-normal font-sans" style={{ color: 'var(--text-secondary)' }}>
                    {entry.company}
                  </p>
                )}
                {entry.description && (
                  <p className="text-sm font-normal font-sans mt-1" style={{ color: 'var(--text-tertiary)' }}>
                    {entry.description}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Education */}
      {profile.education && profile.education.length > 0 && (
        <div>
          <h3
            className="text-sm font-semibold uppercase tracking-wider font-sans mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            Education
          </h3>
          <div className="space-y-3">
            {profile.education.map((entry, index) => (
              <div key={`edu-${index}`}>
                <p className="text-sm font-semibold font-sans" style={{ color: 'var(--text-primary)' }}>
                  {[entry.degree, entry.field].filter(Boolean).join(', ') || 'Degree'}
                </p>
                {entry.institution && (
                  <p className="text-sm font-normal font-sans" style={{ color: 'var(--text-secondary)' }}>
                    {entry.institution}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Social Links */}
      {profile.social_links && Object.keys(profile.social_links).length > 0 && (
        <div>
          <h3
            className="text-sm font-semibold uppercase tracking-wider font-sans mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            Links
          </h3>
          <div className="space-y-2">
            {Object.entries(profile.social_links).map(([key, url]) => {
              const href = sanitizeHref(url);
              return href ? (
                <a
                  key={key}
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-sm font-sans"
                  style={{ color: 'var(--text-link)' }}
                >
                  {socialLabel(key)}
                </a>
              ) : null;
            })}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <>
      {/* Desktop: right-side panel */}
      {isOpen && (
        <div
          className="hidden md:block fixed right-0 top-0 h-full overflow-y-auto animate-slideInRight z-40"
          style={{
            width: '320px',
            backgroundColor: 'var(--bg-elevated)',
            borderLeft: '1px solid var(--border-default)',
          }}
          role="dialog"
          aria-label="Profile drawer"
        >
          <button
            onClick={onClose}
            aria-label="Close profile drawer"
            className="absolute top-4 right-4 flex items-center justify-center rounded-full focus:outline-none"
            style={{
              width: '44px',
              height: '44px',
              color: 'var(--text-secondary)',
            }}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path
                d="M15 5L5 15M5 5l10 10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <div className="pt-14">{drawerContent}</div>
        </div>
      )}

      {/* Mobile: bottom sheet */}
      {isOpen && (
        <div className="md:hidden">
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            style={{ backgroundColor: 'var(--bg-overlay)' }}
            onClick={onClose}
            aria-hidden="true"
          />
          {/* Sheet */}
          <div
            className="fixed bottom-0 left-0 right-0 overflow-y-auto z-50"
            style={{
              maxHeight: '75vh',
              backgroundColor: 'var(--bg-elevated)',
              borderRadius: 'var(--radius-xl) var(--radius-xl) 0 0',
              transform: isOpen ? 'translateY(0)' : 'translateY(100%)',
              transition: 'transform 0.3s ease-out',
            }}
            role="dialog"
            aria-label="Profile drawer"
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-2 pb-1">
              <div
                style={{
                  width: '32px',
                  height: '4px',
                  backgroundColor: 'var(--bg-surface)',
                  borderRadius: '2px',
                  marginTop: '8px',
                }}
              />
            </div>
            {/* Close button */}
            <button
              onClick={onClose}
              aria-label="Close profile drawer"
              className="absolute top-4 right-4 flex items-center justify-center rounded-full focus:outline-none"
              style={{
                width: '44px',
                height: '44px',
                color: 'var(--text-secondary)',
              }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path
                  d="M15 5L5 15M5 5l10 10"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            {drawerContent}
          </div>
        </div>
      )}
    </>
  );
}
