import fs from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';
import { LegalDocLayout } from '@/components/legal/LegalDocLayout';

export const metadata: Metadata = {
  title: 'Privacy Policy — PersonaOn',
  description:
    'How PersonaOn collects, uses, discloses, and retains personal information across the platform.',
};

export default function PrivacyPolicyPage() {
  const markdown = fs.readFileSync(
    path.join(process.cwd(), 'content', 'legal', 'privacy-policy.md'),
    'utf-8',
  );
  return (
    <LegalDocLayout
      title="Privacy Policy"
      lastUpdated="April 30, 2026"
      slug="privacy"
      markdown={markdown}
    />
  );
}
