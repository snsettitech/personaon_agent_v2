'use client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SampleQAEntry {
  question: string;
  answer: string;
  citations?: string[];
  title?: string;
  confidence?: number;
}

interface SampleQAProps {
  entries: SampleQAEntry[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SampleQA({ entries }: SampleQAProps) {
  if (!entries || entries.length === 0) return null;

  return (
    <div className="space-y-4">
      {entries.map((entry, i) => (
        <div
          key={i}
          className="rounded-2xl p-5"
          style={{
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          {/* Question */}
          <p
            className="text-sm font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            {entry.question}
          </p>

          {/* Answer */}
          <p
            className="mt-2 text-sm leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            {entry.answer}
          </p>

          {/* Citations */}
          {entry.citations && entry.citations.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {entry.citations.map((citation, ci) => (
                <span
                  key={ci}
                  className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                  style={{
                    backgroundColor: 'rgba(245,158,11,0.12)',
                    color: 'var(--accent-trust-dark)',
                    border: '1px solid rgba(245,158,11,0.25)',
                  }}
                >
                  [{ci + 1}] {citation}
                </span>
              ))}
            </div>
          )}

          {/* Confidence indicator */}
          {typeof entry.confidence === 'number' && entry.confidence > 0 && (
            <div className="mt-2 flex items-center gap-2">
              <div
                className="h-1 flex-1 rounded-full overflow-hidden"
                style={{ backgroundColor: 'var(--bg-surface)' }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.round(entry.confidence * 100)}%`,
                    backgroundColor: 'var(--primary-500)',
                  }}
                />
              </div>
              <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                {Math.round(entry.confidence * 100)}%
              </span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
