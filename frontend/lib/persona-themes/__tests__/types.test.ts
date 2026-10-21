import { test, expect } from 'bun:test';
import { isThemeId, THEME_IDS } from '../types';

test('THEME_IDS contains the v1 set', () => {
  expect(THEME_IDS).toEqual(['classic','founder-site','conversion-warm','editorial','split','site']);
});

test('isThemeId accepts known ids', () => {
  expect(isThemeId('classic')).toBe(true);
  expect(isThemeId('founder-site')).toBe(true);
  expect(isThemeId('conversion-warm')).toBe(true);
});

test('isThemeId rejects unknown / non-string', () => {
  expect(isThemeId('editorial-broadsheet')).toBe(false);
  expect(isThemeId('')).toBe(false);
  expect(isThemeId(null)).toBe(false);
  expect(isThemeId(undefined)).toBe(false);
  expect(isThemeId(42 as unknown)).toBe(false);
});
