// Shapes mirror the real PersonaOn pipeline (ProfileSchema / _enrich_profile_from_resume)
// so the demo is faithful to what a user gets after signup. Ported from the
// standalone PersonaOnOnboarding-demo into the main app for the /experience route.

export interface WorkEntry {
  company?: string;
  role?: string;
  description?: string;
  period?: string;
}

export interface EduEntry {
  institution?: string;
  degree?: string;
  field?: string;
  period?: string;
}

export interface SampleQA {
  question: string;
  answer: string;
}

/** The full compiled twin — stays SERVER-SIDE; never sent whole to the client pre-signup. */
export interface DemoProfile {
  name: string;
  headline: string;
  occupation: string;
  bio: string;
  speakingStyle: string;
  personalityTraits: string[];
  expertise: string[];
  achievements: string[];
  contributions: string[];
  workExperience: WorkEntry[];
  education: EduEntry[];
  sampleQA: SampleQA[];
  suggestedQuestions: string[];
}

/** The ~40% slice the client receives before signing up. Locked sections are sent
 *  only as counts so the UI can render blurred placeholders without leaking content. */
export interface DemoPreview {
  name: string;
  headline: string;
  knowsTeaser: string;
  expertisePreview: string[];
  sampleQA: SampleQA;
  suggestedQuestions: string[];
  locked: {
    expertise: number;
    achievements: number;
    contributions: number;
    workExperience: number;
    education: number;
    hasBio: boolean;
    hasVoice: boolean;
  };
  /** Short gist snippets of otherwise-locked sections — a partial peek that
   *  entices signup without exposing the full content (titles/first lines only). */
  teasers: {
    bio?: string;
    work?: string;
    achievement?: string;
    education?: string;
    contribution?: string;
    voice?: string;
  };
  chatLimit: number;
}

export interface DemoQuestion {
  id: string;
  prompt: string;
  placeholder: string;
}

export const DEMO_QUESTIONS: DemoQuestion[] = [
  {
    id: 'focus',
    prompt: 'What do you do, and what are you best known for?',
    placeholder: 'e.g. I build full-stack web apps and embedded systems; known for shipping fast, reliable products.',
  },
  {
    id: 'communication',
    prompt: 'How would close colleagues describe the way you communicate?',
    placeholder: 'e.g. Direct, practical, data-driven — I lead with outcomes and metrics.',
  },
  {
    id: 'proud',
    prompt: "What's a recent win you're proud of?",
    placeholder: 'e.g. Shipped an LMS serving 390+ students; co-authored an IEEE paper.',
  },
];
