import type { Metadata } from "next";

import MarketplaceDirectory from "./MarketplaceDirectory";

/**
 * Server wrapper for the marketplace directory: gives the page real
 * metadata + a self-canonical so it's a proper landing page (the root layout's
 * generic title no longer applies here). The list stays client-rendered — every
 * index-eligible persona is already discoverable via the sitemap, so the
 * directory doesn't need its list server-rendered for crawl coverage.
 */
export const metadata: Metadata = {
  title: "Explore AI personas",
  description:
    "Browse and chat with always-on AI personas of real professionals — ask questions and get answers in their voice, before you ever meet.",
  alternates: { canonical: "/marketplace" },
  openGraph: {
    title: "Explore AI personas | PersonaOn",
    description:
      "Browse and chat with always-on AI personas of real professionals on PersonaOn.",
    url: "/marketplace",
    type: "website",
  },
};

export default function Page() {
  return <MarketplaceDirectory />;
}
