type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function cleanText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function formatPersonaDisplayName(name?: string | null): string {
  const cleaned = cleanText(name);
  if (!cleaned) return 'Persona';
  return cleaned.replace(/\btwin\b/gi, 'persona');
}

export function formatPersonaRoleOrganization(settings?: JsonRecord | null): string {
  const safeSettings = asRecord(settings);
  const publicProfile = asRecord(safeSettings.public_profile);
  const personaProfile = asRecord(safeSettings.persona_profile);

  const role =
    cleanText(publicProfile.role) ||
    cleanText(personaProfile.occupation) ||
    cleanText(personaProfile.role);
  const organization =
    cleanText(publicProfile.organization) ||
    cleanText(personaProfile.organization) ||
    cleanText(personaProfile.company);

  if (role && organization) return `${role} at ${organization}`;
  if (role) return role;
  if (organization) return organization;
  return 'Role and organization not set';
}
