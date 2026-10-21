'use client';

interface GeographyFilterProps {
  regions: string[];
  selected: string | null;
  onSelect: (region: string | null) => void;
}

export default function GeographyFilter({ regions, selected, onSelect }: GeographyFilterProps) {
  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    onSelect(value === '' ? null : value);
  };

  return (
    <select
      value={selected ?? ''}
      onChange={handleChange}
      className="rounded-2xl px-4 py-2.5 text-sm font-medium appearance-none cursor-pointer focus:outline-none focus:ring-2"
      style={{
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        color: 'var(--text-primary)',
      }}
      aria-label="Filter by region"
    >
      <option value="">All Regions</option>
      {regions.map((region) => (
        <option key={region} value={region}>
          {region}
        </option>
      ))}
    </select>
  );
}
