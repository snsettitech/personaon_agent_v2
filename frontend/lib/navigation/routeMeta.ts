export interface DashboardRouteAction {
  label: string;
  href: string;
}

export interface DashboardRouteMeta {
  /** Deprecated: no longer rendered (per-section eyebrow retired). Kept optional for back-compat. */
  eyebrow?: string;
  title: string;
  description: string;
  primaryAction?: DashboardRouteAction;
  secondaryAction?: DashboardRouteAction;
  status?: string;
  showHeader?: boolean;
}

const exactRoutes: Record<string, DashboardRouteMeta> = {
  '/dashboard': {
    eyebrow: 'Persona Command Center',
    title: 'Your PersonaOn workspace.',
    description: 'Add sources, test answers, send your persona to meetings, and choose what becomes public.',
    primaryAction: { label: 'Send persona to a meeting', href: '/dashboard/meetings' },
    secondaryAction: { label: 'Chat with persona', href: '/dashboard/chat' },
    showHeader: false,
  },
  '/dashboard/profile': {
    eyebrow: 'Build',
    title: 'Persona Profile',
    description: 'Edit the facts, links, story, and intro your persona uses when it represents you.',
    primaryAction: { label: 'Edit profile', href: '/dashboard/profile' },
    secondaryAction: { label: 'Test in chat', href: '/dashboard/chat' },
  },
  '/dashboard/knowledge': {
    eyebrow: 'Build',
    title: 'Knowledge',
    description: 'Add the information your persona should use when answering people.',
    primaryAction: { label: 'Add knowledge', href: '/dashboard/knowledge' },
  },
  '/dashboard/studio': {
    eyebrow: 'Build',
    title: 'Persona Studio',
    description: 'Shape tone, boundaries, and behavior before your persona speaks for you.',
    primaryAction: { label: 'Calibrate persona', href: '/dashboard/studio' },
    secondaryAction: { label: 'Review profile', href: '/dashboard/profile' },
  },
  '/dashboard/chat': {
    eyebrow: 'Chat',
    title: 'Try Your Persona',
    description: 'Ask real questions and see how your persona responds before you share it or send it to a meeting.',
    primaryAction: { label: 'Add sources', href: '/dashboard/knowledge' },
    secondaryAction: { label: 'Review conversations', href: '/dashboard/conversations' },
  },
  '/dashboard/conversations': {
    eyebrow: 'Chat',
    title: 'Conversation Review',
    description: 'See what people asked and turn real gaps into better approved answers.',
    primaryAction: { label: 'Teach unanswered questions', href: '/dashboard/queued-questions' },
    secondaryAction: { label: 'Open chat', href: '/dashboard/chat' },
  },
  '/dashboard/queued-questions': {
    eyebrow: 'Chat',
    title: 'Teach Persona',
    description: 'Answer gaps once so your persona can respond better next time.',
    primaryAction: { label: 'Answer questions', href: '/dashboard/queued-questions' },
    secondaryAction: { label: 'Review conversations', href: '/dashboard/conversations' },
  },
  '/dashboard/actions': {
    eyebrow: 'Chat',
    title: 'Actions',
    description: 'Decide what your persona can do when someone asks, with approval where needed.',
    primaryAction: { label: 'Create action', href: '/dashboard/actions' },
    secondaryAction: { label: 'Approval inbox', href: '/dashboard/actions/inbox' },
    status: 'User controlled',
  },
  '/dashboard/actions/inbox': {
    eyebrow: 'Actions',
    title: 'Approval Inbox',
    description: 'Review anything your persona should not send or do without you.',
    primaryAction: { label: 'Review approvals', href: '/dashboard/actions/inbox' },
    secondaryAction: { label: 'Action rules', href: '/dashboard/actions/triggers' },
  },
  '/dashboard/actions/triggers': {
    eyebrow: 'Actions',
    title: 'Action Rules',
    description: 'Choose the phrases or intents that trigger persona actions.',
    primaryAction: { label: 'Create rule', href: '/dashboard/actions/triggers' },
    secondaryAction: { label: 'Action history', href: '/dashboard/actions/history' },
  },
  '/dashboard/actions/history': {
    eyebrow: 'Actions',
    title: 'Action History',
    description: 'Audit what your persona attempted and what happened.',
    primaryAction: { label: 'Open approval inbox', href: '/dashboard/actions/inbox' },
    secondaryAction: { label: 'Manage actions', href: '/dashboard/actions' },
  },
  '/dashboard/actions/connectors': {
    eyebrow: 'Actions',
    title: 'Connectors',
    description: 'See connector status without creating fake connected services.',
    primaryAction: { label: 'Open settings', href: '/dashboard/settings' },
    secondaryAction: { label: 'Back to actions', href: '/dashboard/actions' },
    status: 'No fake connections',
  },
  '/dashboard/meetings': {
    eyebrow: 'Meetings',
    title: 'Meetings',
    description: 'Your persona joins your meetings, takes notes in your voice, and remembers every follow-up.',
    primaryAction: { label: 'Join a meeting', href: '/dashboard/meetings' },
    secondaryAction: { label: 'Add sources first', href: '/dashboard/knowledge' },
  },
  '/dashboard/share': {
    eyebrow: 'Publish',
    title: 'Publish',
    description: 'Share your persona with a public link, website embed, or meeting experience.',
    primaryAction: { label: 'Copy public link', href: '/dashboard/share' },
    secondaryAction: { label: 'Open Share Studio', href: '/dashboard/widget' },
  },
  '/dashboard/widget': {
    eyebrow: 'Publish',
    title: 'Share Studio',
    description: 'Place your persona wherever people already find you: website, email, QR, LinkedIn, and social bios.',
    primaryAction: { label: 'Add to website', href: '/dashboard/widget/website' },
    secondaryAction: { label: 'Widget settings', href: '/dashboard/widget/settings' },
  },
  '/dashboard/widget/website': {
    eyebrow: 'Share Studio',
    title: 'Website Embed',
    description: 'Add a PersonaOn chat surface to your website with real setup steps.',
    primaryAction: { label: 'Create website code', href: '/dashboard/widget/website' },
    secondaryAction: { label: 'Widget settings', href: '/dashboard/widget/settings' },
  },
  '/dashboard/widget/settings': {
    eyebrow: 'Share Studio',
    title: 'Widget Behavior',
    description: 'Control how your public chat greets visitors, captures leads, and stays within scope.',
    primaryAction: { label: 'Save widget settings', href: '/dashboard/widget/settings' },
    secondaryAction: { label: 'View leads', href: '/dashboard/widget/leads' },
  },
  '/dashboard/widget/leads': {
    eyebrow: 'Share Studio',
    title: 'Lead Inbox',
    description: 'See who engaged with your persona and where the next follow-up should happen.',
    primaryAction: { label: 'Install website widget', href: '/dashboard/widget/website' },
    secondaryAction: { label: 'Publish', href: '/dashboard/share' },
  },
  '/dashboard/widget/email-signature': {
    eyebrow: 'Share Studio',
    title: 'Email Signature',
    description: 'Let people meet your persona from every email you send.',
    primaryAction: { label: 'Copy signature', href: '/dashboard/widget/email-signature' },
    secondaryAction: { label: 'Publish', href: '/dashboard/share' },
  },
  '/dashboard/widget/linkedin': {
    eyebrow: 'Share Studio',
    title: 'LinkedIn Presence',
    description: 'Add your persona to your professional profile without fake posting automation.',
    primaryAction: { label: 'Copy profile text', href: '/dashboard/widget/linkedin' },
    secondaryAction: { label: 'Social links', href: '/dashboard/widget/social' },
  },
  '/dashboard/widget/qr': {
    eyebrow: 'Share Studio',
    title: 'QR & Print',
    description: 'Bring your persona into rooms, events, and meetings with a scannable card.',
    primaryAction: { label: 'Download QR', href: '/dashboard/widget/qr' },
    secondaryAction: { label: 'Email signature', href: '/dashboard/widget/email-signature' },
  },
  '/dashboard/widget/social': {
    eyebrow: 'Share Studio',
    title: 'Social Links',
    description: 'Share your persona from social bios and posts with copyable links and text.',
    primaryAction: { label: 'Copy social link', href: '/dashboard/widget/social' },
    secondaryAction: { label: 'Publish', href: '/dashboard/share' },
  },
  '/dashboard/api-keys': {
    eyebrow: 'Publish',
    title: 'API Keys',
    description: 'Create secure access for widgets and integrations that need a real key.',
    primaryAction: { label: 'Create API key', href: '/dashboard/api-keys' },
    secondaryAction: { label: 'Website embed', href: '/dashboard/widget/website' },
  },
  '/dashboard/insights': {
    eyebrow: 'Control',
    title: 'Insights',
    description: 'Understand what people ask and where your persona needs better sources.',
    primaryAction: { label: 'Review gaps', href: '/dashboard/queued-questions' },
    secondaryAction: { label: 'Open conversations', href: '/dashboard/conversations' },
  },
  '/dashboard/responses': {
    eyebrow: 'Control',
    title: 'Responses',
    description: 'Set how your persona starts conversations, handles uncertainty, and chooses response style.',
    secondaryAction: { label: 'Test in chat', href: '/dashboard/chat' },
  },
  '/dashboard/billing': {
    eyebrow: 'Control',
    title: 'Plan',
    description: 'Manage access, usage, and billing without changing persona content.',
    primaryAction: { label: 'Manage billing', href: '/dashboard/billing' },
    secondaryAction: { label: 'Settings', href: '/dashboard/settings' },
  },
  '/dashboard/settings': {
    eyebrow: 'Control',
    title: 'Settings',
    description: 'Manage account access, voice, notifications, and persona behavior.',
    primaryAction: { label: 'Review Profile', href: '/dashboard/profile' },
  },
  '/dashboard/products': {
    eyebrow: 'Launch hidden',
    title: 'Offer Library',
    description: 'Keep product links organized only when they are part of a real persona workflow.',
    primaryAction: { label: 'Back to command center', href: '/dashboard' },
  },
};

const prefixRoutes: Array<{ prefix: string; meta: DashboardRouteMeta }> = [
  {
    prefix: '/dashboard/knowledge/',
    meta: {
      eyebrow: 'Build',
      title: 'Knowledge Detail',
      description: 'Review what this information contributes to your persona.',
      primaryAction: { label: 'Back to knowledge', href: '/dashboard/knowledge' },
      secondaryAction: { label: 'Test in chat', href: '/dashboard/chat' },
    },
  },
  {
    prefix: '/dashboard/meetings/',
    meta: {
      eyebrow: 'Meetings',
      title: 'Meeting Brief',
      description: 'Review meeting state, persona readiness, transcript, and follow-up context.',
      primaryAction: { label: 'Open meeting room', href: '/dashboard/meetings' },
      secondaryAction: { label: 'Add sources', href: '/dashboard/knowledge' },
      status: 'Meeting context',
      // The meeting detail page (legacy AND v2 MeetingPageV2) is self-contained —
      // it has its own back link, title, and tabs. Rendering this generic shell
      // header above it produced a confusing double-header ("multiple UIs"), so
      // suppress the shell here and let the page own its chrome.
      showHeader: false,
    },
  },
];

export function getDashboardRouteMeta(pathname: string | null): DashboardRouteMeta | null {
  if (!pathname) return null;

  if (pathname.endsWith('/live') && pathname.startsWith('/dashboard/meetings/')) {
    return {
      eyebrow: 'Meetings',
      title: 'Live Meeting Console',
      description: 'Monitor your persona in the meeting, review scoped activity, and preserve follow-up context.',
      primaryAction: { label: 'Back to meetings', href: '/dashboard/meetings' },
      secondaryAction: { label: 'Knowledge', href: '/dashboard/knowledge' },
      status: 'Live console',
    };
  }

  const exact = exactRoutes[pathname];
  if (exact) return exact;

  const prefix = prefixRoutes.find((route) => pathname.startsWith(route.prefix));
  return prefix?.meta ?? null;
}
