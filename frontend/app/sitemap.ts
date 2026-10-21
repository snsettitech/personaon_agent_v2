import type { MetadataRoute } from "next";

import { getAllPosts } from "@/lib/blog/posts";
import { SITE_URL } from "@/lib/seo/constants";
import { getAllPublicProfileHandles } from "@/lib/seo/profiles";

/**
 * Dynamic sitemap: static marketing routes + blog posts + every index-eligible
 * public persona page (/p/{handle}). Index-eligibility is gated server-side by
 * the backend `is_indexable` rule, so thin/unpublished personas are excluded
 * here AND `noindex`-ed at the page level (T0-4).
 *
 * Regenerates at most hourly; on-demand revalidation (T0-6) refreshes it
 * immediately when a profile is published/edited. Single file is correct until
 * the persona count nears 50k — then shard via generateSitemaps().
 */
export const revalidate = 3600;

const MARKETING_ROUTES: MetadataRoute.Sitemap = [
  { url: `${SITE_URL}/`, changeFrequency: "daily", priority: 1 },
  { url: `${SITE_URL}/about`, changeFrequency: "monthly", priority: 0.6 },
  { url: `${SITE_URL}/pricing`, changeFrequency: "weekly", priority: 0.8 },
  { url: `${SITE_URL}/marketplace`, changeFrequency: "daily", priority: 0.8 },
  { url: `${SITE_URL}/blog`, changeFrequency: "weekly", priority: 0.7 },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const handles = await getAllPublicProfileHandles();
  const personas: MetadataRoute.Sitemap = handles.map((h) => ({
    url: `${SITE_URL}/p/${h.handle}`,
    lastModified: h.lastModified || undefined,
    changeFrequency: "weekly",
    priority: 0.7,
  }));

  const blogPosts: MetadataRoute.Sitemap = getAllPosts().map((post) => ({
    url: `${SITE_URL}/blog/${post.slug}`,
    lastModified: post.dateModified ?? post.datePublished,
    changeFrequency: "monthly",
    priority: 0.6,
  }));

  return [...MARKETING_ROUTES, ...blogPosts, ...personas];
}
