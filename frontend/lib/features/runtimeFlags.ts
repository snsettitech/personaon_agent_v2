export type RuntimeFeatureFlag =
  | "dashboardChat"
  | "privacyControls"
  | "publishControls"
  | "sourceLabeling"
  | "personaThemes"
  | "notificationsAgent"
  | "notificationsAgentV1";

const toBool = (value: string | undefined, fallback: boolean): boolean => {
  if (value === undefined) return fallback;
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
};

export const RUNTIME_FLAGS: Record<RuntimeFeatureFlag, boolean> = {
  dashboardChat: toBool(process.env.NEXT_PUBLIC_FF_DASHBOARD_CHAT, true),
  privacyControls: toBool(process.env.NEXT_PUBLIC_FF_PRIVACY_CONTROLS, true),
  publishControls: toBool(process.env.NEXT_PUBLIC_FF_PUBLISH_CONTROLS, true),
  sourceLabeling: toBool(process.env.NEXT_PUBLIC_FF_SOURCE_LABELING, true),
  // Persona layout themes (Phase 3+). Gates whether a stored non-classic
  // theme_id is honored; default OFF → Classic-only. Env: NEXT_PUBLIC_PERSONA_THEMES.
  personaThemes: toBool(process.env.NEXT_PUBLIC_PERSONA_THEMES, false),
  notificationsAgent: toBool(process.env.NEXT_PUBLIC_FF_NOTIFICATIONS_AGENT, false),
  notificationsAgentV1: toBool(
    process.env.NEXT_PUBLIC_FF_NOTIFICATIONS_AGENT_V1,
    toBool(process.env.NEXT_PUBLIC_FF_NOTIFICATIONS_AGENT, false),
  ),
};

export const isRuntimeFeatureEnabled = (flag: RuntimeFeatureFlag): boolean =>
  Boolean(RUNTIME_FLAGS[flag]);
