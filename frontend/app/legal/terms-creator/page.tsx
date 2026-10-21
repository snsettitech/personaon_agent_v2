import fs from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';
import { LegalDocLayout } from '@/components/legal/LegalDocLayout';

export const metadata: Metadata = {
  title: 'Creator Terms of Use — PersonaOn',
  description:
    'PersonaOn Creator Terms governing the creation, configuration, deployment, and monetization of AI Personas.',
};

export default function CreatorTermsPage() {
  const markdown = fs.readFileSync(
    path.join(process.cwd(), 'content', 'legal', 'creator-terms.md'),
    'utf-8',
  );
  return (
    <LegalDocLayout
      title="Creator Terms of Use"
      lastUpdated="April 30, 2026"
      slug="terms-creator"
      markdown={markdown}
    />
  );
}
