import fs from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';
import { LegalDocLayout } from '@/components/legal/LegalDocLayout';

export const metadata: Metadata = {
  title: 'Biometric Consent — PersonaOn',
  description:
    "PersonaOn's Biometric Consent Form governing collection, use, and retention of biometric identifiers and biometric information.",
};

export default function BiometricConsentPage() {
  const markdown = fs.readFileSync(
    path.join(process.cwd(), 'content', 'legal', 'biometric-consent.md'),
    'utf-8',
  );
  return (
    <LegalDocLayout
      title="Biometric Consent"
      lastUpdated="April 30, 2026"
      slug="biometric-consent"
      markdown={markdown}
    />
  );
}
