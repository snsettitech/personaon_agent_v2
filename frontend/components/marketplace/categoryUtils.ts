export const PROFESSION_CATEGORIES = [
  'Business', 'Tech', 'Health', 'Creative', 'Academic', 'Legal', 'Finance',
] as const;

export type ProfessionCategory = typeof PROFESSION_CATEGORIES[number];

export const CATEGORY_KEYWORDS: Record<ProfessionCategory, string[]> = {
  Business:  ['ceo', 'founder', 'executive', 'entrepreneur', 'manager', 'director', 'sales', 'marketing', 'business', 'startup', 'consultant', 'strategist', 'operations'],
  Tech:      ['engineer', 'developer', 'software', 'data', 'machine learning', 'ai', 'product', 'cto', 'architect', 'devops', 'programmer', 'tech'],
  Health:    ['doctor', 'physician', 'nurse', 'therapist', 'health', 'medical', 'dentist', 'surgeon', 'nutritionist', 'psychologist', 'psychiatrist', 'wellness'],
  Creative:  ['designer', 'artist', 'writer', 'creative', 'filmmaker', 'musician', 'photographer', 'ux', 'illustrator', 'animator', 'author', 'journalist'],
  Academic:  ['professor', 'researcher', 'academic', 'scientist', 'scholar', 'phd', 'lecturer', 'educator', 'teacher', 'dean'],
  Legal:     ['lawyer', 'attorney', 'legal', 'counsel', 'judge', 'paralegal', 'solicitor', 'barrister', 'compliance'],
  Finance:   ['investor', 'analyst', 'banker', 'finance', 'accountant', 'cfo', 'portfolio', 'hedge', 'trader', 'wealth', 'financial'],
};

export function inferCategory(occupation: string): ProfessionCategory | null {
  if (!occupation) return null;
  const lower = occupation.toLowerCase();
  for (const [category, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
    if (keywords.some((kw) => lower.includes(kw))) return category as ProfessionCategory;
  }
  return null;
}
