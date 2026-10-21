import type React from 'react';
import { isThemeId, type ThemeId, type ThemeShellProps } from './types';
import { ClassicShell } from './shells/ClassicShell';
import { ConversionWarmShell } from './shells/ConversionWarmShell';
import { FounderSiteShell } from './shells/FounderSiteShell';
import { EditorialShell } from './shells/EditorialShell';
import { SplitShell } from './shells/SplitShell';
import { SiteShell } from './shells/SiteShell';

type ShellComponent = (props: ThemeShellProps) => React.ReactElement;

// Phase 4 registers all six layout shells here.
const SHELLS: Record<ThemeId, ShellComponent> = {
  classic: ClassicShell,
  'founder-site': FounderSiteShell,
  'conversion-warm': ConversionWarmShell,
  editorial: EditorialShell,
  split: SplitShell,
  site: SiteShell,
};

/** Render the shell for `themeId`. Unknown/invalid/null ids fall back to
 *  `classic`. Never throws — a bad stored id must never break the live page. */
export function renderTheme(
  themeId: string | null | undefined,
  props: ThemeShellProps,
): React.ReactElement {
  const id: ThemeId = isThemeId(themeId) ? themeId : 'classic';
  const Shell = SHELLS[id] ?? ClassicShell;
  return <Shell {...props} />;
}
