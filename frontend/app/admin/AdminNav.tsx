'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
  { href: '/admin', label: 'Cockpit' },
  { href: '/admin/users', label: 'Users' },
  { href: '/admin/team', label: 'Team' },
  { href: '/admin/revenue', label: 'Revenue' },
  { href: '/admin/conversations', label: 'Conversations' },
  { href: '/admin/insights', label: 'Quality & Insights' },
  { href: '/admin/moderation', label: 'Moderation' },
  { href: '/admin/audit', label: 'Audit' },
  { href: '/admin/ops', label: 'Ops' },
  // Diagnostics (graph seed/replay) removed in v1.1 admin rewrite.
  // Backend endpoints for graph operations were part of the legacy
  // scribe_engine pipeline which is no longer active. Re-add when
  // the knowledge graph is revived or a new diagnostics need arises.
];

export function AdminNav() {
  const pathname = usePathname();

  return (
    <nav className="mx-auto flex max-w-7xl gap-1 px-6">
      {NAV_ITEMS.map(({ href, label }) => {
        const isActive = href === '/admin'
          ? pathname === '/admin'
          : pathname.startsWith(href);

        return (
          <Link
            key={href}
            href={href}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? 'border-slate-900 text-slate-900'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
