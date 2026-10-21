'use client';

import Link from 'next/link';

export type MarketplacePersona = {
  twin_id: string;
  display_name: string;
  occupation: string;
  headline: string;
  bio: string;
  short_description: string;
  avatar_url: string;
  verified_claims_count: number;
  public_topics: Array<{ slug: string; name: string }>;
  areas_of_expertise: string[];
  pinned_questions: string[];
  public_url: string | null;
  verified_profile: boolean;
};

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

export default function PersonaCard({ persona }: { persona: MarketplacePersona }) {
  const href = persona.public_url || '/marketplace';
  const summary =
    persona.short_description ||
    persona.bio ||
    'This persona is ready for conversations grounded in its published profile.';
  const expertise = persona.areas_of_expertise?.length
    ? persona.areas_of_expertise
    : persona.public_topics.map((topic) => topic.name);

  return (
    <Link
      href={href}
      className="group flex h-full flex-col rounded-[28px] p-6 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:shadow-xl"
      style={{
        backgroundColor: 'var(--bg-elevated)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          {persona.avatar_url ? (
            <img
              src={persona.avatar_url}
              alt={persona.display_name}
              className="h-16 w-16 rounded-2xl object-cover"
            />
          ) : (
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#f59e0b,#f97316)] text-lg font-semibold text-white">
              {getInitials(persona.display_name) || 'P'}
            </div>
          )}

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2
                className="truncate text-xl font-semibold"
                style={{ color: 'var(--text-primary)' }}
              >
                {persona.display_name}
              </h2>
              {persona.verified_profile && (
                <span
                  className="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em]"
                  style={{ backgroundColor: '#d1fae5', color: '#059669' }}
                >
                  Verified
                </span>
              )}
            </div>
            <p
              className="mt-1 text-sm"
              style={{ color: 'var(--text-secondary)' }}
            >
              {persona.occupation || persona.headline || 'Public digital persona'}
            </p>
          </div>
        </div>

      </div>

      <div className="mt-6 space-y-3">
        {persona.headline && (
          <p
            className="text-sm font-medium"
            style={{ color: 'var(--accent-trust-dark)' }}
          >
            {persona.headline}
          </p>
        )}
        <p
          className="line-clamp-4 text-sm leading-6"
          style={{ color: 'var(--text-secondary)' }}
        >
          {summary}
        </p>
      </div>

      {expertise.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {expertise.slice(0, 4).map((item) => (
            <span
              key={`${persona.twin_id}-${item}`}
              className="rounded-full px-3 py-1 text-xs font-medium"
              style={{
                backgroundColor: 'var(--bg-surface)',
                color: 'var(--text-secondary)',
              }}
            >
              {item}
            </span>
          ))}
        </div>
      )}

      {persona.pinned_questions.length > 0 && (
        <div
          className="mt-5 rounded-2xl px-4 py-4"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        >
          <p
            className="text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: 'var(--text-tertiary)' }}
          >
            Ask first
          </p>
          <p
            className="mt-2 text-sm"
            style={{ color: 'var(--text-secondary)' }}
          >
            &ldquo;{persona.pinned_questions[0]}&rdquo;
          </p>
        </div>
      )}

      <div
        className="mt-6 flex items-center justify-between border-t pt-4 text-sm"
        style={{
          borderColor: 'var(--border-subtle)',
          color: 'var(--text-tertiary)',
        }}
      >
        <span>{persona.verified_claims_count} verified public claims</span>
        <span
          className="font-medium transition-colors group-hover:opacity-80"
          style={{ color: 'var(--text-primary)' }}
        >
          Open profile
        </span>
      </div>
    </Link>
  );
}
