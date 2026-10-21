import fs from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';
import { LegalDocLayout } from '@/components/legal/LegalDocLayout';

export const metadata: Metadata = {
  title: 'Terms of Use — PersonaOn',
  description: 'PersonaOn Terms of Use governing access to and use of the platform and AI Personas.',
};

export default function TermsPage() {
  const markdown = fs.readFileSync(
    path.join(process.cwd(), 'content', 'legal', 'terms-of-use.md'),
    'utf-8',
  );
  return (
    <LegalDocLayout
      title="Terms of Use"
      lastUpdated="April 30, 2026"
      slug="terms"
      markdown={markdown}
    />
  );
}
