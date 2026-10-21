export type HelpUseCase = {
  title: string;
  persona: string;
  trigger: string;
  action: string;
};

export type HelpSection = {
  heading: string;
  body: string;
  bullets?: string[];
};

export type HelpArticle = {
  slug: string;
  title: string;
  description: string;
  audience: string;
  outcome: string;
  cta: {
    label: string;
    href: string;
  };
  sections: HelpSection[];
  useCases: HelpUseCase[];
};

export const HELP_ARTICLES: HelpArticle[] = [
  {
    slug: 'start-with-your-persona',
    title: 'Start With Your Persona',
    description: 'Set a clear first job for your persona, then test it with real questions.',
    audience: 'New persona owners',
    outcome: 'A persona that can answer one useful workflow today.',
    cta: { label: 'Open dashboard', href: '/dashboard' },
    sections: [
      {
        heading: 'Pick one job first',
        body: 'A broad persona is harder to improve than a focused one. Choose the first job people should use it for, such as answering founder questions, explaining your services, preparing for meetings, or qualifying website visitors.',
        bullets: [
          'Write down the top five questions the persona should answer well.',
          'Choose one audience for the first pass: prospects, visitors, teammates, investors, or students.',
          'Keep the first job narrow until the answers are consistently useful.',
        ],
      },
      {
        heading: 'Add one strong source',
        body: 'Start with one source that contains the truth you want repeated. A resume, website page, FAQ, pitch deck, case study, transcript, or writing sample is enough to create the first useful version.',
        bullets: [
          'Prefer source material that already answers real questions.',
          'Avoid dumping unrelated files before you know what visitors ask.',
          'After upload, test with questions that should be answerable from that source.',
        ],
      },
      {
        heading: 'Run a review chat',
        body: 'Ask the persona questions like a real visitor would. When an answer is thin, incorrect, or generic, add the missing detail as source material instead of manually rewriting the answer in chat.',
      },
    ],
    useCases: [
      {
        title: 'Founder profile',
        persona: 'A founder wants prospects and investors to understand their story.',
        trigger: 'Visitors ask about background, product direction, or credibility.',
        action: 'Add a bio, company overview, and three common founder questions, then test the public chat.',
      },
      {
        title: 'Consultant intake',
        persona: 'A consultant wants website visitors to self-qualify before booking.',
        trigger: 'Visitors ask what services fit their situation.',
        action: 'Add service pages and a short FAQ, then publish the widget on one high-intent page.',
      },
      {
        title: 'Internal expert',
        persona: 'A team expert wants teammates to reuse their knowledge without constant pings.',
        trigger: 'Teammates ask repeat questions about process, decisions, or customer context.',
        action: 'Add process notes and prior answers, then use owner chat to find gaps before sharing.',
      },
    ],
  },
  {
    slug: 'add-sources-that-improve-answers',
    title: 'Add Sources That Improve Answers',
    description: 'Choose source material that maps directly to questions users actually ask.',
    audience: 'Owners improving answer quality',
    outcome: 'Better citations, fewer generic answers, and clearer persona boundaries.',
    cta: { label: 'Add knowledge', href: '/dashboard/knowledge' },
    sections: [
      {
        heading: 'Prioritize high-signal sources',
        body: 'The best sources are specific, current, and easy to quote from. Add materials that explain what you do, what you know, what you sell, or how you make decisions.',
        bullets: [
          'Good: FAQ pages, docs, bios, pitch decks, transcripts, case studies, service pages.',
          'Risky: outdated pages, duplicated files, scraped pages with boilerplate, vague marketing copy.',
          'For public personas, prefer material you are comfortable exposing as answer context.',
        ],
      },
      {
        heading: 'Keep source scope clean',
        body: 'If two sources disagree, the persona may give mixed answers. Remove obsolete copies, split private and public material, and refresh stale pages when your offer or profile changes.',
      },
      {
        heading: 'Use gaps as the roadmap',
        body: 'Review unanswered questions and weak answers. Each repeated gap usually means one missing source, not a need for more random content.',
        bullets: [
          'Add the missing answer once in a durable source.',
          'Retest the exact failed question.',
          'Keep examples close to how visitors phrase the question.',
        ],
      },
    ],
    useCases: [
      {
        title: 'Sales FAQ',
        persona: 'A business owner wants the persona to answer pricing and fit questions.',
        trigger: 'Visitors ask whether the product works for their company size or use case.',
        action: 'Add pricing notes, qualification criteria, and a short objections FAQ.',
      },
      {
        title: 'Thought leader',
        persona: 'A creator wants the persona to reflect their actual point of view.',
        trigger: 'Visitors ask opinion questions and receive generic answers.',
        action: 'Add essays, interviews, podcast transcripts, and sharp examples of the creator voice.',
      },
      {
        title: 'Meeting prep',
        persona: 'A user wants briefings before calls.',
        trigger: 'Meeting emails lack enough relevant context.',
        action: 'Add customer notes, prior call summaries, and product positioning docs.',
      },
    ],
  },
  {
    slug: 'review-chats-and-improve-responses',
    title: 'Review Chats And Improve Responses',
    description: 'Turn real conversations into a short improvement loop.',
    audience: 'Owners with visitor or owner chat activity',
    outcome: 'A weekly rhythm for improving answers from actual demand.',
    cta: { label: 'Review conversations', href: '/dashboard/conversations' },
    sections: [
      {
        heading: 'Sort chats by usefulness',
        body: 'Look for conversations where the persona helped, missed the point, overreached, or should have asked a follow-up. The most useful signal usually comes from real visitor questions, not internal testing.',
        bullets: [
          'Mark questions that should be answerable but are not.',
          'Separate missing facts from wrong tone or overly long responses.',
          'Watch for repeated questions; those deserve source updates first.',
        ],
      },
      {
        heading: 'Update the source of truth',
        body: 'Do not train only from vibes. If an answer needs to change, add the missing fact, boundary, example, or policy in a durable source so future answers can cite it.',
      },
      {
        heading: 'Retest the same question',
        body: 'After updating, ask the same question again. A good fix produces a more specific answer, cites better context, or clearly states when the persona does not know.',
      },
    ],
    useCases: [
      {
        title: 'Queued question review',
        persona: 'A persona owner sees repeated visitor gaps.',
        trigger: 'The persona queues questions it could not answer confidently.',
        action: 'Add one source per repeated gap and retest the original visitor phrasing.',
      },
      {
        title: 'Tone tuning',
        persona: 'A public persona sounds too formal or too generic.',
        trigger: 'Answers are factually right but do not sound like the owner.',
        action: 'Add writing samples and adjust behavior settings, then compare before and after.',
      },
      {
        title: 'Lead follow-up',
        persona: 'A website visitor leaves an email after a chat.',
        trigger: 'A hot lead alert arrives.',
        action: 'Open the conversation, identify intent, and follow up with the most relevant context.',
      },
    ],
  },
  {
    slug: 'publish-and-share-your-persona',
    title: 'Publish And Share Your Persona',
    description: 'Review public details, test the link, then share it where questions already happen.',
    audience: 'Owners ready to make a persona public',
    outcome: 'A public persona link that is credible, useful, and safe to share.',
    cta: { label: 'Open Share Studio', href: '/dashboard/share' },
    sections: [
      {
        heading: 'Review the public profile',
        body: 'Before sharing, check the visible name, headline, bio, avatar, social links, and suggested questions. The first screen should make it obvious who the persona represents and why someone should ask it a question.',
      },
      {
        heading: 'Test like a visitor',
        body: 'Open the public link in a fresh browser state and ask questions that a visitor would ask. Confirm that the persona answers with accurate context and does not expose private material.',
        bullets: [
          'Ask about services, background, availability, and boundaries.',
          'Ask one question it should refuse or qualify.',
          'Check mobile layout before posting the link broadly.',
        ],
      },
      {
        heading: 'Share in the right channel',
        body: 'The best channel depends on intent. Use LinkedIn for credibility, an email signature for warm contacts, a website widget for inbound visitors, and QR codes for events.',
      },
    ],
    useCases: [
      {
        title: 'LinkedIn profile link',
        persona: 'A founder wants inbound visitors from LinkedIn to learn faster.',
        trigger: 'People visit the profile but ask the same intro questions in DMs.',
        action: 'Add the persona link to featured links and pin a post that asks people to try it.',
      },
      {
        title: 'Investor pre-read',
        persona: 'A founder wants investors to understand context before a meeting.',
        trigger: 'Investors repeatedly ask for background or product context.',
        action: 'Share the persona link with a short note and suggested questions.',
      },
      {
        title: 'Creator audience',
        persona: 'A creator wants followers to explore their work.',
        trigger: 'Followers ask for recommendations, background, or where to start.',
        action: 'Publish a persona with top topics and source it from essays, episodes, and FAQs.',
      },
    ],
  },
  {
    slug: 'add-persona-to-your-website',
    title: 'Add Persona To Your Website',
    description: 'Use the widget where visitors already have intent and questions.',
    audience: 'Owners with a website or landing page',
    outcome: 'A widget install that captures useful chats and qualified leads.',
    cta: { label: 'Open widget settings', href: '/dashboard/widget' },
    sections: [
      {
        heading: 'Start on one high-intent page',
        body: 'Install the widget where questions already matter: pricing, services, about, contact, or a product page. Avoid adding it everywhere before reviewing the first week of conversations.',
      },
      {
        heading: 'Set a useful lead prompt',
        body: 'Ask for contact information only after the visitor shows intent. The persona should help first, then offer follow-up when the conversation suggests a real next step.',
        bullets: [
          'Use a short prompt that fits the page context.',
          'Review captured leads with the full conversation before replying.',
          'Disable lead capture on low-intent pages if it creates noise.',
        ],
      },
      {
        heading: 'Improve from visitor language',
        body: 'Website visitors phrase questions differently than owners. Use their exact language to improve FAQs, source material, and suggested questions.',
      },
    ],
    useCases: [
      {
        title: 'Services page',
        persona: 'A consultant wants visitors to understand fit before booking.',
        trigger: 'Visitors ask about pricing, process, and whether their case is a fit.',
        action: 'Install the widget on the services page and enable lead capture after helpful answers.',
      },
      {
        title: 'Course page',
        persona: 'An educator wants students to pick the right course.',
        trigger: 'Visitors ask prerequisites or outcomes.',
        action: 'Add course FAQs and install the widget near enrollment details.',
      },
      {
        title: 'Event page',
        persona: 'A speaker wants attendees to explore topics before or after a talk.',
        trigger: 'Visitors scan the page after a talk or from a QR code.',
        action: 'Use the widget with suggested questions tied to the talk.',
      },
    ],
  },
  {
    slug: 'keep-your-persona-current',
    title: 'Keep Your Persona Current',
    description: 'Use a short weekly review to keep answers aligned with your current work.',
    audience: 'Active owners with ongoing updates',
    outcome: 'A persona that changes when your work, offer, or priorities change.',
    cta: { label: 'Review knowledge', href: '/dashboard/knowledge' },
    sections: [
      {
        heading: 'Check what changed this week',
        body: 'Your persona should reflect current positioning, services, achievements, calendar context, and boundaries. A short weekly pass prevents stale answers from becoming trusted answers.',
        bullets: [
          'Remove obsolete sources and duplicated docs.',
          'Add new announcements, case studies, and policy changes.',
          'Refresh public profile details when your role or offer changes.',
        ],
      },
      {
        heading: 'Use activity as the priority list',
        body: 'Start with the questions visitors asked, leads captured, and chats that produced weak answers. Update the most repeated or highest-value gaps first.',
      },
      {
        heading: 'Retest public and owner flows',
        body: 'Test one public visitor question, one owner training question, and one boundary question after each weekly update.',
      },
    ],
    useCases: [
      {
        title: 'New offer',
        persona: 'A founder changes pricing or launches a new package.',
        trigger: 'The persona still references old services or positioning.',
        action: 'Update service pages, remove old docs, and retest pricing and fit questions.',
      },
      {
        title: 'Fresh content',
        persona: 'A creator publishes new articles or episodes.',
        trigger: 'Visitors ask what is new or where to start.',
        action: 'Add the new content and update suggested questions around the latest themes.',
      },
      {
        title: 'Team process',
        persona: 'An internal expert changes a workflow.',
        trigger: 'Teammates ask about a process that recently changed.',
        action: 'Replace old instructions with the current process and mark deprecated material clearly.',
      },
    ],
  },
  {
    slug: 'answer-queued-questions',
    title: 'Answer Queued Questions',
    description: 'Use unanswered questions as a precise source update list.',
    audience: 'Owners seeing knowledge gaps',
    outcome: 'Fewer repeated gaps and clearer owner follow-up actions.',
    cta: { label: 'Open conversations', href: '/dashboard/conversations' },
    sections: [
      {
        heading: 'Group repeated gaps',
        body: 'Queued questions are most useful when grouped by topic. A single missing topic may produce many differently worded visitor questions.',
      },
      {
        heading: 'Answer once in a source',
        body: 'Create or update one durable source with the best answer. Include examples, boundaries, and next steps so the persona can answer follow-up questions too.',
      },
      {
        heading: 'Close the loop',
        body: 'After updating, ask the original question again. If the answer still fails, the source may be too vague, private, contradictory, or not indexed yet.',
      },
    ],
    useCases: [
      {
        title: 'Missing pricing answer',
        persona: 'A services business gets repeated pricing questions.',
        trigger: 'The persona queues pricing questions instead of answering.',
        action: 'Add a pricing FAQ with ranges, qualifiers, and booking guidance.',
      },
      {
        title: 'Boundary question',
        persona: 'An expert gets questions outside their domain.',
        trigger: 'The persona tries to answer topics it should not cover.',
        action: 'Add a boundary source that states what the persona does not advise on.',
      },
      {
        title: 'Specific bio gap',
        persona: 'Visitors ask about experience that is missing from the profile.',
        trigger: 'The persona gives a generic background answer.',
        action: 'Add a concise bio note or resume source with the missing details.',
      },
    ],
  },
  {
    slug: 'privacy-and-boundaries',
    title: 'Privacy And Boundaries',
    description: 'Decide what your persona can say, cite, and decline.',
    audience: 'Owners publishing or sharing with teams',
    outcome: 'A persona that is useful without exposing the wrong information.',
    cta: { label: 'Review settings', href: '/dashboard/settings' },
    sections: [
      {
        heading: 'Separate public and private context',
        body: 'Public personas should answer from material you are comfortable sharing. Private team or meeting context can be useful, but it should not bleed into public visitor answers.',
      },
      {
        heading: 'Teach refusal boundaries',
        body: 'A good persona knows when to say it does not know, when to qualify an answer, and when to point someone to the owner. Add explicit boundaries for regulated, sensitive, or out-of-scope topics.',
      },
      {
        heading: 'Review analytics responsibly',
        body: 'Use activity trends to improve docs and answers, not to expose sensitive visitor content. Keep notification and analytics settings aligned with the audience and surface.',
      },
    ],
    useCases: [
      {
        title: 'Public founder persona',
        persona: 'A founder shares a public link broadly.',
        trigger: 'Visitors ask about confidential roadmap or investor details.',
        action: 'Add public-safe roadmap language and a boundary for confidential details.',
      },
      {
        title: 'Team knowledge base',
        persona: 'A team shares an internal expert persona.',
        trigger: 'The persona needs private process docs.',
        action: 'Keep internal docs out of public surfaces and test access paths separately.',
      },
      {
        title: 'Lead capture',
        persona: 'A website widget captures visitor emails.',
        trigger: 'Visitors share contact info during chat.',
        action: 'Review leads in the dashboard and keep follow-up relevant to the conversation.',
      },
    ],
  },
];

const HELP_ARTICLE_BY_SLUG = new Map(HELP_ARTICLES.map((article) => [article.slug, article]));

export function getHelpArticle(slug: string): HelpArticle | undefined {
  return HELP_ARTICLE_BY_SLUG.get(slug);
}
