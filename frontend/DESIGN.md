---
name: PersonaOn
description: A professional presence that answers — premium, calm, trustworthy persona product.
colors:
  signal: "#0066cc"
  signal-hot: "#1e7cff"
  signal-deep: "#0057ad"
  ink: "#1d1d1f"
  ink-2: "#2a2a2e"
  ink-3: "#3a3a3f"
  fog: "#f5f5f7"
  surface: "#fafafa"
  elevated: "#ffffff"
  text-primary: "#1d1d1f"
  text-secondary: "#1d1d1f94"
  text-tertiary: "#1d1d1f66"
  border-subtle: "#1d1d1f1a"
  border-default: "#1d1d1f2e"
  ok: "#2bb673"
  warn: "#e0a21a"
  rec: "#e5484d"
typography:
  display:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(56px, 9.8vw, 132px)"
    fontWeight: 600
    lineHeight: 0.98
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(40px, 6.6vw, 88px)"
    fontWeight: 600
    lineHeight: 1.0
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.18em"
  serif-accent:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "clamp(40px, 6.6vw, 88px)"
    fontWeight: 400
    lineHeight: 1.0
    letterSpacing: "normal"
rounded:
  chip: "14px"
  card: "30px"
  hero: "34px"
  pill: "9999px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "#1f1f22"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
  button-cta:
    backgroundColor: "{colors.signal}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "0 28px"
    height: "46px"
  button-cta-hover:
    backgroundColor: "{colors.signal-hot}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "42px"
  input-field:
    backgroundColor: "{colors.elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "42px"
  card:
    backgroundColor: "{colors.elevated}"
    rounded: "{rounded.card}"
    padding: "24px"
  status-pill:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    height: "22px"
    padding: "0 10px"
---

# Design System: PersonaOn

## 1. Overview

**Creative North Star: "The Trusted Instrument"**

PersonaOn is a premium, calm, trustworthy product whose entire job is to make a person's professional presence *answer* — grounded only in material they approved, never synthetic, deferring when it does not know. The design has to earn that trust on sight: it is an instrument the owner reaches for to keep their persona sharp, not a stage that performs. Premium here is **restraint plus specificity**, not flourish. The interface recedes; the work — real conversations, grounded answers with sources, queued questions, bookings — is what carries weight.

This is a split surface with one personality. The **product dashboard** (Home, Build, Chat, Meetings, Publish, Control) is the default register: information-first, neutral chrome, the single accent rationed to primary actions and active state, status color used only for status. The **brand pages** (`/`, `/pricing`, `/blog`, `/marketplace`, public personas `/p/[handle]`) take a per-task "brand" override that earns larger type and more compositional throw — but answers to the same warm-ink/cool-fog palette, the same single-accent discipline, and the same anti-hype voice. Brand-scale type and throw never enter the dashboard.

What this system explicitly rejects: the generic "AI made this" look (AI-purple gradients, gradient text, decorative glassmorphism, glowing orbs), the consumer-companion / avatar-grid aesthetic, faceless-enterprise neutrality with no warmth, the hero-metric template, and ploy.ai-style *loudness* (giant screaming display, candy palette, cheeky tone). ploy.ai is a north star for agentic *narrative* only — translated into a calm register.

**Key Characteristics:**
- Warm near-black ink on cool off-white fog; light mode only.
- Exactly one accent — Signal Blue — kept solid and rationed.
- Geist carries the type system end to end; serif and mono are rare, deliberate accents.
- Calm by default: motion conveys state, not spectacle; surfaces flatten toward the product register.
- Trust is a visible surface: citations, "sourced from material you approved," graceful "I don't know."

## 2. Colors

A disciplined near-monochrome — warm ink and cool fog — with a single blue that does all the pointing.

### Primary
- **Signal Blue** (`#0066cc`): the one brand accent. Reserved for primary actions, the current selection, active nav, focus rings, and links — never decoration. Hot variant **Signal Hot** (`#1e7cff`) is the hover/active lift; **Signal Deep** (`#0057ad`) is the pressed state.

### Neutral
- **Warm Ink** (`#1d1d1f`): primary text, dark cards, sidebars, and the primary button fill. Steps **Ink-2** (`#2a2a2e`) and **Ink-3** (`#3a3a3f`) layer dark surfaces.
- **Cool Fog** (`#f5f5f7`): the app body background. **Surface** (`#fafafa`) and **Elevated** (`#ffffff`) are the two content layers above it.
- **Text Secondary** (`#1d1d1f` @ 58%) and **Text Tertiary** (`#1d1d1f` @ 40%): supporting and faint text. Verify both clear 4.5:1 for body copy; do not push body text into the tertiary tone.
- **Border Subtle** (`#1d1d1f` @ 10%) / **Border Default** (`#1d1d1f` @ 18%): hairlines and dividers.

### Status (reserved — never decorative)
- **Live Green** (`#2bb673`): success, live, connected.
- **Caution Amber** (`#e0a21a`): warnings. Most at-risk for contrast on white — always pair with text or icon, and darken the foreground tone when amber sits on a tint.
- **Record Red** (`#e5484d`): errors, recording, destructive.

### Named Rules
**The One Voice Rule.** Signal Blue is the only accent, used on ≤10% of any screen — primary action, active state, focus. Its rarity is the point. Status colors are not accents; they appear only to report status.

**The Solid Accent Rule.** The accent is always a solid fill. No gradient text (`background-clip: text`), no multi-hue glow, no decorative orbs. The one sanctioned gradient in the system is a single low-opacity Signal-Blue ambient wash behind white text on the inverted ink brand card — background only, `aria-hidden`.

## 3. Typography

**Display / Body Font:** Geist (with `ui-sans-serif, system-ui` fallback)
**Editorial Accent Serif:** Newsreader *italic* (with Georgia fallback)
**Wordmark / "P" Mark Serif:** Instrument Serif (with Georgia fallback)
**Label / Mono Font:** JetBrains Mono (with `ui-monospace` fallback)

**Character:** One workhorse sans (Geist) carries display, headings, body, and data — premium comes from weight and scale, not from a display face. The serif is a single italicized word dropped into a headline for warmth; the mono is the quiet, technical kicker that labels sections and statuses. The pairing is contrast-axis (geometric sans + editorial serif + mono), never two similar sans.

### Hierarchy
- **Display** (Geist 600, `clamp(56px, 9.8vw, 132px)`, lh 0.98, tracking -0.04em): brand-page heroes only. *Note: this runs above the 96px display ceiling — a deliberate brand choice; see Do's & Don'ts.*
- **Headline** (Geist 600, `clamp(40px, 6.6vw, 88px)`, lh 1.0): brand section headers. The editorial **serif-accent** (Newsreader italic) substitutes for one emphasized word here.
- **Title** (Geist 700, 20px, lh 1.2, tracking -0.025em): dashboard card and section headers — fixed rem, not fluid.
- **Body** (Geist 400, 16px, lh 1.5): default copy; cap prose at 65–75ch.
- **Label** (JetBrains Mono 500, 11px, tracking 0.18em, uppercase): kickers, eyebrows, status pills, metadata.

### Named Rules
**The Geist-Carries-Scale Rule.** Big type is Geist 600, never the serif. The serif (Newsreader italic) is a rare one-word accent; Instrument Serif is the wordmark/"P" mark. If a headline is set entirely in serif, it is wrong.

**The Mono Kicker Rule.** JetBrains Mono uppercase is the one sanctioned kicker/label voice — a deliberate system, not a reflexive eyebrow on every section. Use it to label, not to decorate.

**The Fixed-Scale-In-Product Rule.** Product UI uses a fixed rem scale (Title 20px, Body 16px). Fluid `clamp()` display belongs to brand pages only; a headline that shrinks inside a sidebar is a bug.

## 4. Elevation

The system is **soft-glass today, flattening toward the product register.** The committed kit ships long-throw ambient shadows and broad `backdrop-filter` glass; the direction is to reserve depth for genuine elevation and the brand register, and to flatten product chrome. Depth is conveyed primarily by tonal layering (Fog → Surface → Elevated) and hairline borders, with shadow added only on lift.

### Shadow Vocabulary
- **Card** (`box-shadow: 0 18px 55px rgba(0,0,0,.08), 0 1px 0 rgba(29,29,31,.06)`): resting elevation for content cards.
- **Hero** (`box-shadow: 0 28px 80px rgba(0,0,0,.10)`): large brand/hero cards.
- **Lift** (`0 8px 30px rgba(0,0,0,.08)` + 1px accent ring on `card-hover`): hover response only.

### Named Rules
**The Flat-By-Default Rule.** Product surfaces are flat at rest — tonal layering + hairlines. Shadow appears as a *response* (hover, focus, true overlay), not as resting decoration. Decorative glassmorphism (`backdrop-filter` on at-rest cards) is being retired; keep text off blurred backgrounds.

## 5. Components

Refined and restrained: every interactive element is a fully-rounded pill or a hairline-bordered surface, with the accent reserved for the one action that matters.

### Buttons
- **Shape:** fully rounded pill (`9999px`), 42px tall (CTA 46px), 14px Geist 500.
- **Primary:** Warm Ink fill, white text (`button-primary`); hover lifts to `#1f1f22`. The default affirmative on light ground.
- **CTA:** Signal Blue fill, white text (`button-cta`), 600 weight; hover → Signal Hot. The single high-intent acquisition action.
- **Secondary:** transparent with a hairline border; hover fills Surface. **Ghost:** text-only, muted, fills Surface on hover.
- **On ink:** white pill (`button-primary-on-ink`) and hairline dark pill (`button-secondary-on-ink`) for dark/hero grounds.
- **Focus:** visible focus ring in Signal Blue at ~18% — never remove it on pills.

### Inputs / Fields
- **Style:** Elevated (`#ffffff`) fill, Border Default hairline, pill radius, 42px, 14px Geist.
- **Focus:** border shifts to Signal Blue with a 3px Signal glow (`rgba(0,102,204,.18)`).
- **Error:** Record Red border + red focus glow. Placeholder uses Text Tertiary — verify it still clears 4.5:1.

### Cards / Containers
- **Corner Style:** large radius (`card` 30px / `hero` 34px). *Open decision: tighten product-card radius toward ~16px while brand keeps the larger throw.*
- **Background:** Elevated on Fog; **Border:** Border Subtle hairline; **Shadow:** Card at rest (see Elevation, flattening in product).
- **Internal Padding:** ~24px (`clamp(20px, 3vw, 28px)` on dashboard command cards). Never nest a card inside a card.

### Navigation
- Six product groups (Home, Build, Chat, Meetings, Publish, Control). Quiet by default; active item carries Signal Blue. Labels in Geist; section kickers in mono.

### Status Pill (signature)
- Mono uppercase, 22px tall, hairline, dot + label. Variants: `.live` (Live Green, pulsing dot), `.signal` (Signal Blue), `.rec` (Record Red). The system's one piece of sanctioned ambient motion (a status pulse), reduced-motion aware.

## 6. Do's and Don'ts

### Do:
- **Do** keep Signal Blue the only accent, solid, on ≤10% of any screen (The One Voice Rule).
- **Do** set big type in Geist 600; reserve the serif for a single italicized word (The Geist-Carries-Scale Rule).
- **Do** flatten product surfaces — tonal layering + hairlines at rest, shadow only on state (The Flat-By-Default Rule).
- **Do** make grounding visible: show citations, "sourced from material you approved," and a graceful "I don't know."
- **Do** give every interactive component default / hover / focus / active / disabled / loading / error, with skeletons for loading and teaching empty states.
- **Do** verify WCAG 2.2 AA contrast: ink on fog/white ≥4.5:1; pair status colors with text or icon, never color alone.
- **Do** honor `prefers-reduced-motion` on every animation, including the status pulse; ease-out only, no bounce/elastic.

### Don't:
- **Don't** use gradient text, AI-purple/violet gradients, decorative glassmorphism, glowing orbs, or sparkle "AI magic" motifs — the "an AI made this" look. (Retire the existing `.text-gradient`/`.gradient-text` utilities and broad `.glass`.)
- **Don't** reintroduce the `.wordmark .pulse-dot` — it is dead CSS in `globals.css` (~line 598); remove it, never bring it back.
- **Don't** import ploy.ai *loudness* — ~144px screaming display, candy/neon palette (pink/lime/yellow), cheeky tone. Borrow the agentic narrative, reject the volume.
- **Don't** ship the Character.ai consumer-companion / avatar-grid aesthetic — it cheapens a "represents me to recruiters and investors" product.
- **Don't** fall into faceless-enterprise neutrality (Sierra-style zero-serif, 0px corners, no voice) — keep the warmth and human voice.
- **Don't** represent the product as a single floating chat-bubble mockup — foreground the real workspace (studio, knowledge, conversations, insights, bookings).
- **Don't** use the hero-metric template (big number + 3 supporting stats + accent bar) or eyebrow/01-02-03 scaffolding on every section — express agentic proof as one real figure or a calm ranked feed.
- **Don't** bring brand-scale display (`clamp` max 112–132px) or fluid type into the dashboard; product uses a fixed rem scale.
- **Don't** let font sprawl persist — Geist + JetBrains Mono + one editorial serif is the system; **Fraunces** (loaded, unused) and **Playfair Display** (legal pages only) should be consolidated out.
