import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { JsonLd } from "@/components/seo/JsonLd";
import { SITE_NAME, SITE_URL } from "@/lib/seo/constants";
import { getProfile } from "@/lib/seo/profiles";

import { ProfileExperience } from "./ProfileExperience";

export const revalidate = 3600;
// No generateStaticParams: handles render on-demand via ISR (revalidate=3600).

// ---------------------------------------------------------------------------
// Safe field access against the loosely-typed redacted profile pack
// ---------------------------------------------------------------------------

function str(profile: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = profile[key];
    if (typeof value === "string" && value.trim().length > 0) return value.trim();
  }
  return undefined;
}

function stringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value.filter((item): item is string => typeof item === "string" && item.length > 0);
  return items.length > 0 ? items : undefined;
}

/** Filter an unknown value down to an array of plain (non-array) objects. */
function objectArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Record<string, unknown> =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item),
  );
}

function socialLinks(profile: Record<string, unknown>): string[] | undefined {
  const links = profile.social_links;
  if (!links || typeof links !== "object" || Array.isArray(links)) return undefined;
  const values = Object.values(links as Record<string, unknown>).filter(
    (item): item is string => typeof item === "string" && item.length > 0,
  );
  return values.length > 0 ? values : undefined;
}

/** Split a display name into OG profile first/last name parts (best-effort). */
function splitName(name: string): { firstName?: string; lastName?: string } {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return {};
  if (parts.length === 1) return { firstName: parts[0] };
  return { firstName: parts[0], lastName: parts.slice(1).join(" ") };
}

/**
 * Person JSON-LD `worksFor`: the most-recent / most-senior employer as an
 * Organization. Prefers an ongoing role (no end_year), then the highest
 * end_year, tie-broken by list order (authored most-recent-first). Returns
 * undefined when no entry carries a company.
 */
function currentEmployer(
  profile: Record<string, unknown>,
): { "@type": "Organization"; name: string } | undefined {
  const jobs = objectArray(profile.work_experience);
  let best: { name: string; score: number } | undefined;
  jobs.forEach((job, idx) => {
    const company = typeof job.company === "string" ? job.company.trim() : "";
    if (!company) return;
    const endYear = typeof job.end_year === "number" ? job.end_year : undefined;
    const startYear = typeof job.start_year === "number" ? job.start_year : 0;
    // Ongoing roles outrank any dated role; among ongoing, earliest-listed wins.
    const score =
      endYear === undefined ? Number.MAX_SAFE_INTEGER - idx : endYear * 10000 + startYear;
    if (!best || score > best.score) best = { name: company, score };
  });
  return best ? { "@type": "Organization", name: best.name } : undefined;
}

/** Person JSON-LD `alumniOf`: de-duplicated education institutions. */
function alumniOrgs(
  profile: Record<string, unknown>,
): Array<{ "@type": "EducationalOrganization"; name: string }> | undefined {
  const seen = new Set<string>();
  const orgs: Array<{ "@type": "EducationalOrganization"; name: string }> = [];
  for (const edu of objectArray(profile.education)) {
    const inst = typeof edu.institution === "string" ? edu.institution.trim() : "";
    if (!inst || seen.has(inst.toLowerCase())) continue;
    seen.add(inst.toLowerCase());
    orgs.push({ "@type": "EducationalOrganization", name: inst });
  }
  return orgs.length > 0 ? orgs : undefined;
}

/**
 * Person JSON-LD `award`: explicit owner-approved `awards`/`award` fields when
 * present, otherwise the already-public `key_achievements` list. Every source
 * is content that is already rendered on the page — nothing new is un-redacted.
 */
function awardList(profile: Record<string, unknown>): string[] | undefined {
  const explicit =
    stringArray(profile.awards) ??
    (str(profile, "award") ? [str(profile, "award") as string] : undefined);
  return explicit ?? stringArray(profile.key_achievements);
}

function descriptionFor(
  profile: Record<string, unknown>,
  name: string,
): string {
  const raw = str(profile, "short_description", "bio", "summary");
  if (raw) return raw.length > 155 ? `${raw.slice(0, 155).trimEnd()}…` : raw;
  return `Chat with ${name}'s persona on PersonaOn.`;
}

/**
 * Entity-first, fact-dense meta/OG/Twitter description (<=155 chars). Leads with
 * the entity definition ("{name} is {occupation}.") then a persona CTA scoped to
 * the top expertise. Greedily picks the richest variant that fits, degrading to
 * the bio-based description when the profile lacks occupation + expertise.
 */
function metaDescriptionFor(profile: Record<string, unknown>, name: string): string {
  const occupation = str(profile, "occupation", "headline");
  const { firstName } = splitName(name);
  const who = firstName ?? name;
  const expertise = stringArray(profile.areas_of_expertise);
  const topExpertise = expertise ? expertise.slice(0, 2).join(", ") : undefined;

  const entity = occupation ? `${name} is ${occupation}.` : undefined;
  const chatFull = topExpertise
    ? `Chat with ${who}'s AI persona about ${topExpertise}.`
    : `Chat with ${who}'s AI persona.`;
  const chatShort = `Chat with ${who}'s AI persona.`;

  const candidates: Array<Array<string | undefined>> = [
    [entity, chatFull],
    [entity, chatShort],
    [entity],
    [chatFull],
    [chatShort],
  ];
  for (const parts of candidates) {
    const text = parts.filter(Boolean).join(" ");
    if (text && text.length <= 155) return text;
  }
  const fallback = descriptionFor(profile, name);
  return fallback.length > 155 ? `${fallback.slice(0, 154).trimEnd()}…` : fallback;
}

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export async function generateMetadata({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<Metadata> {
  const { handle } = await params;
  const data = await getProfile(handle);

  if (!data) {
    return {
      title: "Persona not found",
      robots: { index: false, follow: false },
    };
  }

  const profile = data.profile;
  const name = str(profile, "name", "display_name") ?? "Persona";
  const headline = str(profile, "occupation", "headline");
  // The root layout applies the "%s | PersonaOn" title template, so the brand
  // suffix is added there — don't repeat it here (it caused "… | PersonaOn | PersonaOn").
  const title = headline ? `${name} — ${headline}` : name;
  const description = metaDescriptionFor(profile, name);
  const url = `/p/${handle}`;
  const { firstName, lastName } = splitName(name);
  // Generated social card (./opengraph-image.tsx) — served at this stable
  // file-convention path; used as the Twitter card image.
  const ogImage = `${SITE_URL}/p/${handle}/opengraph-image`;

  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title,
      description,
      url,
      type: "profile",
      siteName: SITE_NAME,
      username: handle,
      ...(firstName ? { firstName } : {}),
      ...(lastName ? { lastName } : {}),
      // og:image comes from the generated card (./opengraph-image.tsx) —
      // file-convention images take precedence over config metadata anyway,
      // and the raw avatar made shared links look broken/bare.
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [ogImage],
    },
    robots: data.isIndexable
      ? { index: true, follow: true }
      : { index: false, follow: true },
  };
}

// ---------------------------------------------------------------------------
// Page (Server Component)
// ---------------------------------------------------------------------------

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}) {
  const { handle } = await params;
  const data = await getProfile(handle);
  if (!data) notFound();

  const profile = data.profile;
  const name = str(profile, "name", "display_name") ?? "Persona";
  const headline = str(profile, "occupation", "headline");
  const description = descriptionFor(profile, name);
  const image = str(profile, "image_url", "avatar_url");
  const knowsAbout = stringArray(profile.areas_of_expertise);
  const sameAs = socialLinks(profile);
  const worksFor = currentEmployer(profile);
  const alumniOf = alumniOrgs(profile);
  const award = awardList(profile);
  const dateModified =
    typeof data.lastModified === "string" && data.lastModified.trim().length > 0
      ? data.lastModified
      : undefined;

  const canonicalUrl = `${SITE_URL}/p/${handle}`;
  const personId = `${canonicalUrl}#person`;
  const ogImage = `${SITE_URL}/p/${handle}/opengraph-image`;
  const primaryImage = image ?? ogImage;

  // Shared WebSite entity the ProfilePage belongs to.
  const webSite = {
    "@type": "WebSite",
    "@id": `${SITE_URL}/#website`,
    name: SITE_NAME,
    url: SITE_URL,
  };

  const profilePageLd: Record<string, unknown> = {
    "@type": "ProfilePage",
    "@id": `${canonicalUrl}#profilepage`,
    url: canonicalUrl,
    name: headline ? `${name} — ${headline}` : name,
    ...(dateModified ? { dateModified } : {}),
    primaryImageOfPage: primaryImage,
    isPartOf: webSite,
    mainEntity: { "@id": personId },
  };

  const personLd: Record<string, unknown> = {
    "@type": "Person",
    "@id": personId,
    name,
    url: canonicalUrl,
    description,
    ...(image ? { image } : {}),
    ...(headline ? { jobTitle: headline } : {}),
    ...(knowsAbout ? { knowsAbout } : {}),
    ...(sameAs ? { sameAs } : {}),
    ...(worksFor ? { worksFor } : {}),
    ...(alumniOf ? { alumniOf } : {}),
    ...(headline ? { hasOccupation: { "@type": "Occupation", name: headline } } : {}),
    ...(award ? { award } : {}),
  };

  const breadcrumbLd: Record<string, unknown> = {
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Personas", item: `${SITE_URL}/marketplace` },
      { "@type": "ListItem", position: 3, name, item: canonicalUrl },
    ],
  };

  // Owner-approved FAQ only (extractPublicFaq reads settings.public_profile.
  // public_faq / profile.public_faq — never response seeds). Emit a FAQPage
  // node only with >=2 curated pairs on an indexable page.
  const faq = data.public_faq ?? [];
  const faqLd: Record<string, unknown> | undefined =
    faq.length >= 2
      ? {
          "@type": "FAQPage",
          mainEntity: faq.map((entry) => ({
            "@type": "Question",
            name: entry.question,
            acceptedAnswer: { "@type": "Answer", text: entry.answer },
          })),
        }
      : undefined;

  const graphLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@graph": [
      profilePageLd,
      personLd,
      breadcrumbLd,
      ...(faqLd ? [faqLd] : []),
    ],
  };

  return (
    <>
      {data.isIndexable && <JsonLd data={graphLd} />}
      <ProfileExperience
        handle={handle}
        initialTwinId={data.twinId}
        initialShareToken={data.shareToken}
        initialData={data.profile}
      />
    </>
  );
}
