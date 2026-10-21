'use client';

import { PROFESSION_CATEGORIES, type ProfessionCategory } from './categoryUtils';

interface CategoryPillBarProps {
  selected: ProfessionCategory | null;
  onSelect: (cat: ProfessionCategory | null) => void;
  categoryCounts?: Record<string, number>;
}

export default function CategoryPillBar({ selected, onSelect, categoryCounts }: CategoryPillBarProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {/* All pill */}
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="rounded-full px-4 py-2 text-sm font-medium transition-colors"
        style={
          selected === null
            ? { backgroundColor: 'var(--primary-500)', color: '#ffffff' }
            : { backgroundColor: 'var(--bg-surface)', color: 'var(--text-secondary)' }
        }
      >
        All
      </button>

      {/* Category pills */}
      {PROFESSION_CATEGORIES.map((cat) => (
        <button
          key={cat}
          type="button"
          onClick={() => onSelect(cat)}
          className="rounded-full px-4 py-2 text-sm font-medium transition-colors"
          style={
            selected === cat
              ? { backgroundColor: 'var(--accent-trust)', color: '#ffffff' }
              : { backgroundColor: 'var(--bg-surface)', color: 'var(--text-secondary)' }
          }
        >
          {cat}
          {categoryCounts?.[cat] !== undefined && (
            <span className="ml-1.5 text-xs opacity-70">({categoryCounts[cat]})</span>
          )}
        </button>
      ))}
    </div>
  );
}
