import { test, expect } from 'bun:test';
import { isValidElement } from 'react';
import { renderTheme } from '../renderTheme';
import type { ThemeShellProps } from '../types';

const props: ThemeShellProps = {
  profile: {
    name: 'Test', headline: '', bio: '', verified: false,
    socialLinks: [], expertise: [], achievements: [], traits: [],
    contributions: [], workExperience: [], education: [], featured: [],
    pinnedQuestions: [],
  },
  interaction: null,
  visibility: {},
};

test('renderTheme("classic") returns a React element', () => {
  expect(isValidElement(renderTheme('classic', props))).toBe(true);
});

test('renderTheme falls back to classic for unknown / null / undefined and never throws', () => {
  for (const id of ['editorial-broadsheet', '', null, undefined, 123 as unknown as string]) {
    expect(() => renderTheme(id, props)).not.toThrow();
    expect(isValidElement(renderTheme(id, props))).toBe(true);
  }
});
