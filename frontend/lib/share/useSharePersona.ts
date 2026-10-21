import { useTwin } from '@/lib/context/TwinContext';
import type { SharePersona } from './utils';

export function useSharePersona(): SharePersona | null {
  const { activeTwin, user } = useTwin();
  if (!activeTwin) return null;

  // settings is a Supabase Json column; safe cast at this read boundary.
  const settings = (activeTwin.settings || {}) as Record<string, unknown>;
  const handle = typeof settings.handle === 'string' ? settings.handle : '';
  const pub =
    settings.public_profile &&
    typeof settings.public_profile === 'object' &&
    !Array.isArray(settings.public_profile)
      ? (settings.public_profile as Record<string, unknown>)
      : {};
  const name =
    (typeof pub.display_name === 'string' && pub.display_name.trim()) ||
    activeTwin.name ||
    user?.full_name ||
    'My Persona';
  const role = typeof pub.role === 'string' ? pub.role.trim() : '';
  const org = typeof pub.organization === 'string' ? pub.organization.trim() : '';
  const headline =
    (typeof pub.headline === 'string' && pub.headline.trim()) ||
    (role && org ? `${role} at ${org}` : role) ||
    '';
  const avatarUrl =
    (typeof pub.avatar_url === 'string' && pub.avatar_url.trim()) ||
    user?.avatar_url ||
    '';

  return { name, headline, avatarUrl, handle };
}
