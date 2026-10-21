import { test, expect } from 'bun:test';
import { toPortfolioProfile } from './toPortfolioProfile';

test('maps core fields, prefers occupation→headline and short_description→bio', () => {
  const p = toPortfolioProfile({
    name: 'Jane Smith',
    occupation: 'Product Leader',
    headline: 'ignored when occupation present',
    short_description: 'Builder.',
    bio: 'ignored when short_description present',
    image_url: 'https://x/a.png',
    verified_profile: true,
    areas_of_expertise: ['Growth'],
    work_experience: [{ company: 'Acme', role: 'VP', description: 'led', start_year: 2020, end_year: 2023 }],
    education: [{ institution: 'Stanford', degree: 'MBA', field: 'Biz', period: '2018' }],
    suggested_questions: ['What do you do?'],
  });
  expect(p.name).toBe('Jane Smith');
  expect(p.headline).toBe('Product Leader');
  expect(p.bio).toBe('Builder.');
  expect(p.avatarUrl).toBe('https://x/a.png');
  expect(p.verified).toBe(true);
  expect(p.expertise).toEqual(['Growth']);
  expect(p.workExperience[0]).toEqual({ company: 'Acme', role: 'VP', description: 'led', period: '2020 – 2023' });
  expect(p.education[0].period).toBe('2018');
  expect(p.pinnedQuestions).toEqual(['What do you do?']);
});

test('sanitizes social links (http(s) only) and honors visibility', () => {
  const p = toPortfolioProfile({
    name: 'X',
    social_links: { linkedin: 'linkedin.com/in/x', evil: 'javascript:alert(1)', hidden: 'https://h' },
    social_link_visibility: { hidden: false },
  });
  const platforms = p.socialLinks.map((s) => s.platform);
  expect(platforms).toContain('linkedin');
  expect(platforms).not.toContain('hidden'); // visibility=false
  // Dangerous schemes are dropped outright (safeHttpUrl returns '' and the
  // link is filtered), never coerced into a clickable url.
  expect(platforms).not.toContain('evil');
  expect(p.socialLinks.find((s) => s.platform === 'linkedin')?.url).toBe('https://linkedin.com/in/x');
  expect(p.socialLinks.every((s) => /^https?:\/\//.test(s.url))).toBe(true);
});

test('drops hidden featured items and empties absent collections', () => {
  const p = toPortfolioProfile({
    name: 'X',
    featured_content: [
      { type: 'link', url: 'https://a', title: 'A' },
      { type: 'youtube', url: 'https://yt', hidden: true },
    ],
  });
  expect(p.featured).toEqual([{ type: 'link', url: 'https://a', title: 'A' }]);
  expect(p.achievements).toEqual([]);
  expect(p.traits).toEqual([]);
});

test('builds lifeLine from nationality + years when present', () => {
  expect(toPortfolioProfile({ name: 'X', nationality: 'British', birth_year: 1900, death_year: 1980 }).lifeLine)
    .toBe('British • 1900 - 1980');
  expect(toPortfolioProfile({ name: 'X' }).lifeLine).toBeUndefined();
});
