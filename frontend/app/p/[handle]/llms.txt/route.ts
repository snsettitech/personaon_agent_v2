import { notFound } from "next/navigation";

import { SITE_URL } from "@/lib/seo/constants";
import { getProfile } from "@/lib/seo/profiles";

import { toPortfolioProfile, type RawPublicProfile } from "../toPortfolioProfile";

/**
 * Per-persona machine-readable summary: `GET /p/{handle}/llms.txt`.
 *
 * Emits a compact, LLM-friendly Markdown card (name, one-line definition, bio,
 * expertise, work, education, owner-curated Q&A) so answer engines can ground a
 * citation without executing the client-side persona experience. Mirrors the
 * page's index gate: a missing or non-indexable persona hard-404s (via
 * `notFound()`) so we never expose a machine-readable summary of a page that is
 * `noindex` on the HTML side.
 *
 * Cached on the same 1h ISR window as the page + sitemap (getProfile revalidate,
 * plus the route `revalidate` below); on-demand revalidation refreshes it too.
 */
export const revalidate = 3600;

function heading(name: string, headline: string): string[] {
  const lines = [`# ${name}`];
  if (headline) {
    // One-line, quotable definition sentence for answer-engine extraction.
    lines.push("", `${name} is ${headline}.`);
  }
  return lines;
}

function bulletSection(title: string, items: readonly string[]): string[] {
  if (items.length === 0) return [];
  return ["", `## ${title}`, "", ...items.map((item) => `- ${item}`)];
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ handle: string }> },
): Promise<Response> {
  const { handle } = await params;
  const data = await getProfile(handle);
  // Reuse the page's index signal: non-indexable / missing => 404, matching the
  // HTML page's noindex behavior so the two surfaces never disagree.
  if (!data || !data.isIndexable) notFound();

  // The redacted profile pack is loosely typed; toPortfolioProfile normalizes +
  // sanitizes it into the presentation contract the page already trusts.
  const profile = toPortfolioProfile(
    data.profile as unknown as RawPublicProfile,
  );
  const name = profile.name || "Persona";

  const lines: string[] = [...heading(name, profile.headline)];

  if (profile.bio) {
    lines.push("", profile.bio);
  }

  lines.push(...bulletSection("Expertise", profile.expertise));

  const work = profile.workExperience.filter((job) => job.role || job.company);
  if (work.length > 0) {
    lines.push("", "## Work", "");
    for (const job of work) {
      const roleCompany = [job.role, job.company].filter(Boolean).join(" at ");
      const period = job.period ? ` (${job.period})` : "";
      const description = job.description ? ` — ${job.description}` : "";
      lines.push(`- ${roleCompany}${period}${description}`);
    }
  }

  const education = profile.education.filter(
    (edu) => edu.institution || edu.degree || edu.field,
  );
  if (education.length > 0) {
    lines.push("", "## Education", "");
    for (const edu of education) {
      const degree = [edu.degree, edu.field].filter(Boolean).join(", ");
      const head = [degree, edu.institution].filter(Boolean).join(" — ");
      const period = edu.period ? ` (${edu.period})` : "";
      lines.push(`- ${head}${period}`);
    }
  }

  const faq = data.public_faq ?? [];
  if (faq.length > 0) {
    lines.push("", "## Q&A");
    for (const { question, answer } of faq) {
      lines.push("", `### ${question}`, "", answer);
    }
  }

  lines.push("", "---", `Canonical: ${SITE_URL}/p/${handle}`);
  if (data.lastModified) {
    lines.push(`Last updated: ${data.lastModified}`);
  }

  const body = `${lines.join("\n")}\n`;

  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control":
        "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
