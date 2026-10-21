import type { Metadata } from 'next';
import Nav from '@/components/LandingClassy/Nav';
import Hero from '@/components/LandingClassy/Hero';
import BeforeAfter from '@/components/LandingClassy/BeforeAfter';
import Problem from '@/components/LandingClassy/Problem';
import Stages from '@/components/LandingClassy/Stages';
import ExperienceSection from '@/components/LandingClassy/ExperienceSection';
import WhoFor from '@/components/LandingClassy/WhoFor';
import RealNotSynthetic from '@/components/LandingClassy/RealNotSynthetic';
import Closing from '@/components/LandingClassy/Closing';
import Footer from '@/components/LandingClassy/Footer';

export const metadata: Metadata = {
  // `absolute` so the root layout's "%s | PersonaOn" template does not append
  // a redundant " | PersonaOn" to the homepage title.
  title: { absolute: 'PersonaOn — Your portfolio, but it answers.' },
  description:
    'Paste your resume. Get a living portfolio that answers questions about your work, books your meetings, and captures interest — free, live in minutes.',
  alternates: { canonical: '/' },
  openGraph: {
    title: 'PersonaOn — Your portfolio, but it answers.',
    description:
      'Paste your resume. Get a living portfolio that answers questions, books meetings, and works while you sleep. Free.',
    type: 'website',
    url: '/',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'PersonaOn — Your portfolio, but it answers.',
    description: 'Resume in. Living portfolio out. It answers, books, and works while you sleep.',
  },
};

export default function HomePage(): React.JSX.Element {
  return (
    <div
      className="min-h-screen antialiased"
      style={{ backgroundColor: 'var(--fog)' }}
    >
      <Nav />
      <main>
        <Hero />
        <ExperienceSection />
        <BeforeAfter />
        <Problem />
        <Stages />
        <WhoFor />
        <RealNotSynthetic />
        <Closing />
      </main>
      <Footer />
    </div>
  );
}
