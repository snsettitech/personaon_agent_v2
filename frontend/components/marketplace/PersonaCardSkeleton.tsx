'use client';

export default function PersonaCardSkeleton() {
  return (
    <div
      className="flex h-full flex-col rounded-[28px] p-6 shadow-sm animate-pulse"
      style={{
        backgroundColor: 'var(--bg-elevated)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      {/* Header: avatar + name */}
      <div className="flex items-start gap-4">
        <div
          className="h-16 w-16 shrink-0 rounded-2xl"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
        <div className="min-w-0 flex-1 space-y-2">
          <div
            className="h-5 w-36 rounded"
            style={{ backgroundColor: 'var(--bg-surface)' }}
          />
          <div
            className="h-4 w-48 rounded"
            style={{ backgroundColor: 'var(--bg-surface)' }}
          />
        </div>
      </div>

      {/* Body: bio lines */}
      <div className="mt-6 space-y-2">
        <div
          className="h-3 w-full rounded"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
        <div
          className="h-3 w-5/6 rounded"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
        <div
          className="h-3 w-4/6 rounded"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
      </div>

      {/* Tags */}
      <div className="mt-5 flex gap-2">
        <div
          className="h-6 w-20 rounded-full"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
        <div
          className="h-6 w-24 rounded-full"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
        <div
          className="h-6 w-16 rounded-full"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
      </div>

      {/* Footer */}
      <div
        className="mt-6 flex items-center justify-between border-t pt-4"
        style={{ borderColor: 'var(--border-subtle)' }}
      >
        <div
          className="h-3 w-32 rounded"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
        <div
          className="h-3 w-20 rounded"
          style={{ backgroundColor: 'var(--bg-surface)' }}
        />
      </div>
    </div>
  );
}
