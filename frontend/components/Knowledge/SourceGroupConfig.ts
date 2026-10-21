import type { SourceType } from '@/lib/types/source';

export const SOURCE_GROUP_CONFIG: Record<
  SourceType,
  { label: string; icon: string; color: string; bgColor: string }
> = {
  profile:  { label: 'Profile',           icon: '\u{1F464}', color: 'text-indigo-600', bgColor: 'bg-indigo-50' },
  document: { label: 'Documents',         icon: '\u{1F4C4}', color: 'text-blue-600',   bgColor: 'bg-blue-50' },
  web:      { label: 'Web Links',         icon: '\u{1F310}', color: 'text-green-600',  bgColor: 'bg-green-50' },
  youtube:  { label: 'YouTube',           icon: '\u{1F4F9}', color: 'text-red-600',    bgColor: 'bg-red-50' },
  podcast:  { label: 'Podcasts',          icon: '\u{1F399}\uFE0F', color: 'text-purple-600', bgColor: 'bg-purple-50' },
  x_thread: { label: 'X Threads',         icon: '\u{1D54F}',  color: 'text-slate-800',  bgColor: 'bg-slate-100' },
  manual:   { label: 'Manual / Captured', icon: '\u270F\uFE0F', color: 'text-amber-600',  bgColor: 'bg-amber-50' },
};

export const SOURCE_GROUP_ORDER: SourceType[] = [
  'profile',
  'document',
  'web',
  'youtube',
  'podcast',
  'x_thread',
  'manual',
];
