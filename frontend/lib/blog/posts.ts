/**
 * Blog content registry. Posts are plain data (markdown `body` rendered with
 * react-markdown) — no MDX/build step. Add a new post by appending to
 * `BLOG_POSTS`; it flows automatically into /blog, /blog/[slug], and the sitemap.
 */

export interface BlogPost {
  slug: string;
  title: string;
  /** Meta description + index excerpt (~155 chars). */
  description: string;
  /** ISO date (YYYY-MM-DD). */
  datePublished: string;
  dateModified?: string;
  author: string;
  tags: string[];
  /** Markdown body. */
  body: string;
}

export const BLOG_POSTS: BlogPost[] = [
  {
    slug: "what-is-an-always-on-professional-persona",
    title: "What is an always-on professional persona?",
    description:
      "A profile lists what you've done. A persona can answer for you — in your voice, sourced from your real work, never synthetic. Here's what that means.",
    datePublished: "2026-06-08",
    dateModified: "2026-07-04",
    author: "PersonaOn",
    tags: ["persona", "professional presence", "lead capture"],
    body: `Your time doesn't scale. The number of people who want to talk to you, learn
from you, or work with you keeps growing — but the hours in your week don't.

The internet gave professionals **profiles**. A profile lists where you've
worked, what you've built, and what you care about. What it *can't* do is answer
the questions you get every week, explain your thinking, or help someone decide
whether they should reach out before they ever do. So everyone starts from zero.

An **always-on professional persona** is the layer that fills that gap.

## A persona, not a chatbot

A persona is not a generic AI assistant and not a synthetic avatar. It's anchored
to a real person, and it answers the way that person actually would:

- **In your voice** — it reflects how you write and talk, not a generic model tone.
- **Sourced from you** — it draws on your real work, words, and approved material,
  not a guessed-at knowledge base.
- **Never synthetic** — every answer traces back to a real human who is
  accountable for it. The goal is to represent you, not to replace you.

The distinction matters. In a world filling up with fake faces, fake voices, and
experts who don't exist, the thing that becomes *more* valuable is a real person
— with real judgment and a name behind what they say.

## How it works in practice

A persona earns its keep across three connected surfaces:

1. **You talk, your page updates.** Tell your persona what's new — a project
   you shipped, a point of view you've refined — and it edits your public page
   for you. No CMS, no rewriting your own bio every quarter.
2. **Your page talks back — and captures the lead.** Visitors chat with your
   persona directly and get real answers in your voice. When a visitor's
   questions signal real interest, that conversation becomes a captured lead
   automatically, even while you're offline.
3. **A persona that compounds.** Every conversation, every edit, and every
   post you publish makes it a little more like you. Over time it becomes
   infrastructure, not a feature.

The point isn't to remove the human conversation. It's to make it easier for
the right people to find you, understand you, and reach you — before a
conversation ever has to happen.

## Who it's for

Always-on personas are most valuable for **trust-first professionals** — people
whose authority comes from credentials and earned reputation rather than a large
content following:

- Independent consultants
- Fractional executives
- Real-estate professionals
- Advisors, recruiters, and other relationship-driven specialists

These professionals don't have a YouTube channel doing their explaining for them.
Their reach is bottlenecked by their calendar. A persona gives them presence
without burnout: a page that can represent them, answer in their voice, and stay
inside their boundaries — always on, even when they're not.

## The bet

We think the bet most people are making — that *more synthetic* is the future —
is wrong. The future belongs to real people made more reachable. An always-on
persona is how you scale access to yourself without giving all of it away.`,
  },
];

export function getAllPosts(): BlogPost[] {
  return [...BLOG_POSTS].sort((a, b) =>
    b.datePublished.localeCompare(a.datePublished),
  );
}

export function getPostBySlug(slug: string): BlogPost | undefined {
  return BLOG_POSTS.find((post) => post.slug === slug);
}
