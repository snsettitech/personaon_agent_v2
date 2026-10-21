# Product

## Register

product

## Users

PersonaOn is for people whose story *is* the product — the person, not a team, is the thing being evaluated.

The live ICP is the four "who it's for" cards on the landing page (`WhoFor.tsx`):

- **Job seekers** who need to beat the 7-second resume scan.
- **Freelancers and consultants** who answer the same ten lead questions and want them auto-answered and the meeting booked.
- **Founders** who get diligenced at midnight by investors they will never be awake for.
- **Coaches and experts** for whom trust is the entire product.

Their job is the same: turn a static professional presence into one that answers in their voice, grounded only in material they approved, books real meetings into their calendar, and reports afterward who was interested and what they asked. They arrive **skeptical of AI "clones"** — they need proof it will not put words in their mouth.

Inside the product, the recurring user is the **owner training and tuning the twin**: pasting source material, reviewing how it is landing, approving or correcting answers, and shipping the page. The dashboard is the instrument they use to keep the persona sharp. The persona page is the surface their visitors actually meet.

## Product Purpose

PersonaOn turns a professional presence into one that answers.

You paste your resume and source material. You get a living page at personaon.com that responds to questions about your work **in your voice** — grounded in what you provided, never synthetic, deferring when it does not know. It books meetings straight into your calendar and captures who engaged and what they asked.

The frontend is two halves of one product:

- **Brand pages** that earn the visit and convert it.
- A **real workspace** (~37 `/dashboard/*` routes today: chat, conversations, queued questions, actions, meetings, knowledge ingestion, studio, share/widget/embed, insights, responses, billing, settings, privacy) organized by user jobs, not folders — the place to train, ground, and share the twin.

Success is the owner trusting the page enough to put it in front of recruiters, investors, and clients, and the page reliably answering, booking, and reporting back on their behalf.

The Home surface is converging on a calm **"chief of staff"** assistant (`AssistantHome.tsx`) that keeps the persona sharp, reports how it is landing, and handles follow-ups — a present-tense feature that ships today, not a roadmap promise.

## Brand Personality

**Three words: premium, calm, trustworthy** — quiet confidence that lets the work speak.

**Voice and tone:** calm, precise, grounded, anti-hype. It states what the product does plainly ("Real you. Real voice. Not synthetic.") and earns trust by being accountable — every word traces back to the resume, an edit the owner made, or material they approved, and the persona defers when it does not know. Promotion is understated, Apple-style, never a shout.

**Emotional goals** for a skeptical, time-poor professional:

- **Relief** — this represents me faithfully, even when I am offline.
- **Control** — nothing is invented; I approve the source of truth.
- **Quiet pride** — this is a premium surface I am glad to attach my name to.

It must never feel like a toy companion, a hype-y AI gadget, or a generic SaaS template, and never make the user anxious it will speak out of turn. Agentic energy is welcome, but it arrives as **competence** ("handles the follow-ups," "tells you how it's landing"), not spectacle.

**Guardrail:** ploy-voice phrasings ("works while you sleep," named-agent ticker copy) are borrowed *substance*, deployed sparingly in calm copy — never default product chrome. "ploy not loud" should stay visible in the writing itself.

## Anti-references

- **ploy.ai loudness (inside the product register).** ploy.ai is the strategic north star for **narrative only** (named agents, "works while you sleep," AI-prioritized feeds, flatter surfaces). Its *surface energy* is the explicit anti-reference: ~144px FK Screamer display, candy/neon palette (pink `#FFB8FC`, lime `#D1F864`, yellow `#FFFA64`), cheeky tone. Marketing-scale type or candy accents inside the dashboard would break the information-first calm. Borrow the story; reject the volume and the palette.
- **Character.ai-style consumer-companion aesthetic** — colorful, illustrative, avatar-grid, playful, low-restraint. The opposite pole from a premium/calm/trustworthy persona product; it cheapens a B2B-leaning "represents me to recruiters/investors" positioning. Never the avatar-grid/companion look.
- **The generic "AI slop" default** — AI-purple/violet gradients, gradient **text**, decorative glassmorphism, nested rounded cards, emoji headings, sparkle/glowing-orb "AI magic" motifs (the "an AI made this" look). PersonaOn's own CSS already ships `.text-gradient`/`.gradient-text` and broad backdrop-blur (the exact tells to rein in), and the `.wordmark .pulse-dot` rule is still present as **dead CSS** (`globals.css` ~line 598): retire it, never reintroduce it. Keep the single accent **solid and functional** — banned is gradient *text*, multi-hue AI-purple glows, and decorative orbs. (One documented exception: a single low-opacity signal-blue ambient gradient behind white text on the inverted ink brand card is allowed.)
- **Sierra.ai's faceless corporate neutrality** — study it as the gold standard for product-register discipline (flat surfaces, accent rationed to the primary action, trust via real logo wall + compliance badges + in-product UI), but its zero-personality, zero-serif, 0px-corner execution is the anti-reference for PersonaOn's warmth. Adopt the flatness and the show-the-working-system rigor; reject the faceless-enterprise feel and keep the human voice + serif-accent warmth.
- **The single floating chat-bubble mockup as the whole product** — the low-effort persona/clone tell that signals shallow depth. PersonaOn has a real train/ground/share system; foreground that workspace (studio, knowledge, conversations, insights, bookings), not a lone hovering chat widget.
- **The hero-metric template and AI "editorial scaffolding"** — big number + 3 supporting stats + accent bar; eyebrow/kicker on every section; numbered 01/02/03 markers; one giant long-sentence headline. These are slop layouts that ploy's "live metric tickers" land straight into. Express agentic proof as a single real, contextual figure or a calm ranked feed (Linear Insights / Height prioritized-inbox model), not a decorative 3-stat ticker bar.

## Design Principles

- **Show, don't tell.** Prove the twin works by surfacing the real system and real artifacts — actual conversations, queued questions, bookings, grounded answers with their sources — not decorative stats, placeholder cards, or marketing copy. In this category, premium is earned by product evidence, not flourish.
- **Grounding is the brand, made visible.** Trust and accountability are a first-class design surface, not a footnote. Citations, "sourced from material you approved," and the persona deferring when it does not know should be legible in the UI. Make "not synthetic" something the user can *see*, not just read.
- **Recede the chrome, foreground the work.** Non-task surfaces (nav, tabs, labels) stay quiet so the work area dominates; structure is felt, not seen. The dashboard is an instrument, not a hero — no marketing-scale type, hero gradients, oversized display, or decorative motion inside the app.
- **Opinionated defaults over generic flexibility.** Each surface gets one deliberate layout built for its specific job (the "organized by user jobs, not folders" IA), and the AI does the prioritizing — surface what the owner needs first (improve / respond / show / meet). Restraint is a product decision, not just a visual one.
- **Earn the brand, never default to it.** PersonaOn's committed identity (fog off-white + signal-blue + an editorial serif accent) now sits on the 2026 slop frontier — italic-serif headlines and cream surfaces are the current AI reflex. On live brand pages Geist 600 already carries the display scale, so the serif is rare and deliberate (a one-word italic accent, not the hero face). Keep the off-white a deliberate cool-neutral and ration the single accent, so the identity reads as specific and owned, not as a tasteful template.
- **Borrow the agentic substance, reject the volume.** Take ploy's narrative (named agents, works-while-you-sleep, ranked/summarized/acted-on-for-you) and translate it into a calm register; keep all energy inside premium restraint, and deploy ploy-voice phrasings sparingly.

## Accessibility & Inclusion

Target **WCAG 2.2 AA** across both registers. Known needs and risks specific to this codebase:

1. **Color/contrast** — light-mode only, so verify ink `#1d1d1f` / ink-2 `#2a2a2e` on fog `#f5f5f7` / white / `#FAFAFA` all clear 4.5:1 for body and 3:1 for large text and UI components; signal-blue `#0066cc` on white passes for text and focus rings. Never rely on hue alone; keep status colors (ok `#2BB673`, warn `#E0A21A`, rec `#E5484D`) paired with text or icon, since warn/amber on white is the most at-risk. The `.dashboard-v2` `!important` compatibility layer that remaps legacy teal/amber must be audited for contrast as it is retired.
2. **No gradient text** — it tanks contrast and scannability and is being removed anyway; solid ink for headings and metrics. (The one low-opacity signal-blue ambient gradient behind white text on the inverted ink brand card is `aria-hidden` background decoration and does not affect text contrast.)
3. **Reduced motion** — honor `prefers-reduced-motion` for any agentic/ticker/staggered-reveal animation; motion is minimal and decorative-only by default, so it should degrade to static cleanly. Avoid bounce/elastic easing.
4. **Glass/backdrop-blur restraint** also helps legibility — keep text off blurred backgrounds.
5. **Functional completeness counts as accessibility** for a product surface: real `:focus-visible` states, required-field markers, inline validation, and explicit empty/loading/error states (premium AI surfaces commonly omit these).
6. **Pills/icons** need accessible names and ≥44px touch targets; full-pill buttons must keep visible focus.

## Surfaces & Register Split

The **default register is the product dashboard** (the six IA groups in `lib/navigation/config.ts`: Home, Build, Chat, Meetings, Publish, Control). It is information-first: neutral chrome, the single accent rationed to primary actions and active state, status colors used only for status. ("Chief of staff" is the Home surface's content/persona in `AssistantHome.tsx`, not a seventh nav group.)

The **marketing/brand surfaces take a per-task "brand" override**: `/`, `/pricing`, `/blog`, `/marketplace`, and public persona pages `/p/[handle]`. The override permits larger type, more throw, and more expressive composition — but it answers to the same premium/calm/trustworthy personality and the same single-accent discipline. Marketing-scale type and brand throw never enter the dashboard, regardless of register.

> **For whoever authors DESIGN.md** (visual-system details deliberately left out of this strategic doc): the locked kit and the live code disagree and need reconciling, not silent preservation. The big brand-page headlines are **Geist 600 at display scale** (Hero h1 ~`clamp` 132px, WhoFor h2 ~`clamp` 88px), *not* the editorial serif; the serif is a sparing one-word italic accent. `layout.tsx` loads **four** display/serif faces (Fraunces + Instrument Serif + Newsreader + the Geist/JetBrains-Mono system) — real font-sprawl debt; the dominant accent serif on brand pages is **Newsreader italic**, with Instrument Serif as the wordmark. Open decisions to record: (a) consolidate to one editorial serif vs document the multi-serif system; (b) tighten product-card radius (currently 30px/34px `--r-card`/`--r-hero`) toward ~16px while brand pages keep the larger throw. Retire, don't extend: the ~575-line `.dashboard-v2` `!important` layer, `.text-gradient`/`.gradient-text`, broad `.glass`/backdrop-blur, dead `html.dark.*` rules, the `.pulse-dot`, and hardcoded off-palette Tailwind in product pages.
