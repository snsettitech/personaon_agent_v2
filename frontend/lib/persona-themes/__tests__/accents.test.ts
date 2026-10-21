import { test, expect } from 'bun:test';
import { ACCENT_IDS, isAccent, ACCENT_HEX, DEFAULT_ACCENT_FOR } from '../types';

test('ACCENT_IDS is the curated 6', () => {
  expect(ACCENT_IDS).toEqual(['blue','orange','forest','violet','slate','crimson']);
});
test('isAccent narrows + every id has a hex', () => {
  for (const id of ACCENT_IDS) { expect(isAccent(id)).toBe(true); expect(ACCENT_HEX[id]).toMatch(/^#[0-9a-f]{6}$/i); }
  expect(isAccent('neon-pink')).toBe(false);
  expect(isAccent(null)).toBe(false);
});
test('every theme has a default accent', () => {
  for (const t of ['classic','founder-site','conversion-warm','editorial','split'] as const) {
    expect(ACCENT_IDS).toContain(DEFAULT_ACCENT_FOR[t]);
  }
});
