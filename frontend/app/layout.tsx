import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { FeatureFlagProvider } from "@/lib/features/FeatureFlags";
import { ToastProvider } from "@/components/ui/Toast";
import { ThemeProvider } from "@/lib/context/ThemeContext";
import { PostHogProvider } from "@/lib/analytics/PostHogProvider";
import { JsonLd } from "@/components/seo/JsonLd";
import {
  SITE_URL,
  SITE_NAME,
  SITE_DESCRIPTION,
  SOCIAL_LINKS,
} from "@/lib/seo/constants";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "PersonaOn — Your professional persona, maintained by an agent.",
    template: "%s | PersonaOn",
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    url: SITE_URL,
    title: "PersonaOn — Your professional persona, maintained by an agent.",
    description:
      "A public page that chats with visitors, captures leads, and stays current — a persona of you that learns from every conversation.",
  },
  twitter: {
    card: "summary_large_image",
    title: "PersonaOn — Your professional persona, maintained by an agent.",
    description: "A persona of you that keeps your page current and sounds like you.",
  },
};

const organizationLd: Record<string, unknown> = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: SITE_NAME,
  url: SITE_URL,
  logo: `${SITE_URL}/icon.svg`,
  description: SITE_DESCRIPTION,
  ...(SOCIAL_LINKS.length ? { sameAs: SOCIAL_LINKS } : {}),
};

const websiteLd: Record<string, unknown> = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: SITE_NAME,
  url: SITE_URL,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400&family=Instrument+Serif:ital@0;1&family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Newsreader:ital,wght@0,400;0,500;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        className="antialiased"
      >
        <JsonLd data={organizationLd} />
        <JsonLd data={websiteLd} />
        <ThemeProvider>
          <PostHogProvider>
            <Suspense>
              <FeatureFlagProvider>
                <ToastProvider>
                  {children}
                </ToastProvider>
              </FeatureFlagProvider>
            </Suspense>
          </PostHogProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
