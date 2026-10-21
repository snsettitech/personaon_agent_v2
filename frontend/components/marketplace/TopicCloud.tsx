'use client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TopicCloudProps {
  topics: Array<{ slug: string; name: string; answerability_score?: number }>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TopicCloud({ topics }: TopicCloudProps) {
  if (!topics.length) return null;

  return (
    <div className="flex flex-wrap gap-2" role="list" aria-label="Topics">
      {topics.map((topic) => {
        // Scale font size based on answerability_score (60-100 range mapped to 0.75-1.0rem)
        const normalized = Math.min(
          Math.max(((topic.answerability_score ?? 70) - 60) / 40, 0),
          1
        );
        const fontSize = topic.answerability_score !== undefined
          ? `${0.75 + normalized * 0.25}rem`
          : '0.875rem';

        return (
          <span
            key={topic.slug}
            role="listitem"
            className="rounded-full px-3 py-1 font-medium"
            style={{
              fontSize,
              backgroundColor: 'var(--bg-surface)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            {topic.name}
          </span>
        );
      })}
    </div>
  );
}
