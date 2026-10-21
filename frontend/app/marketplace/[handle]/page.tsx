import type { Metadata } from "next";

import { getProfile } from "@/lib/seo/profiles";

import MarketplaceProfileExperience from "./MarketplaceProfileExperience";

export const revalidate = 3600;

/**
 * The marketplace persona detail (/marketplace/{handle}) is a secondary view of
 * the same person as /p/{handle}. We canonicalize to /p/{handle} so the persona
 * page is the single indexed URL — no duplicate-content dilution. The interactive
 * experience stays client-rendered; Google consolidates to the canonical, so the
 * content does not need to be server-rendered here (unlike /p/[handle]).
 */

function firstString(
  profile: Record<string, unknown>,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const value = profile[key];
    if (typeof value === "string" && value.trim().length > 0) return value.trim();
  }
  return undefined;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<Metadata> {
  const { handle } = await params;
  const canonical = `/p/${handle}`;
  const data = await getProfile(handle);
  if (!data) {
    return { title: "Persona", alternates: { canonical } };
  }
  const name = firstString(data.profile, "name", "display_name") ?? "Persona";
  const headline = firstString(data.profile, "occupation", "headline");
  return {
    title: headline ? `${name} — ${headline}` : name,
    alternates: { canonical },
  };
}

export default function Page() {
  return <MarketplaceProfileExperience />;
}
