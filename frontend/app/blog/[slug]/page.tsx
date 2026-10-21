import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { JsonLd } from "@/components/seo/JsonLd";
import { SITE_URL } from "@/lib/seo/constants";
import { getAllPosts, getPostBySlug } from "@/lib/blog/posts";

import PostBody from "./PostBody";

export function generateStaticParams() {
  return getAllPosts().map((post) => ({ slug: post.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const post = getPostBySlug(slug);
  if (!post) {
    return { title: "Post not found", robots: { index: false, follow: true } };
  }
  return {
    title: post.title,
    description: post.description,
    alternates: { canonical: `/blog/${post.slug}` },
    openGraph: {
      title: post.title,
      description: post.description,
      url: `/blog/${post.slug}`,
      type: "article",
      publishedTime: post.datePublished,
      ...(post.dateModified ? { modifiedTime: post.dateModified } : {}),
      authors: [post.author],
    },
  };
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = getPostBySlug(slug);
  if (!post) notFound();

  const articleLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: post.title,
    description: post.description,
    datePublished: post.datePublished,
    dateModified: post.dateModified ?? post.datePublished,
    author: { "@type": "Organization", name: post.author },
    publisher: {
      "@type": "Organization",
      name: "PersonaOn",
      url: SITE_URL,
      logo: { "@type": "ImageObject", url: `${SITE_URL}/icon.svg` },
    },
    mainEntityOfPage: `${SITE_URL}/blog/${post.slug}`,
  };

  return (
    <main className="mx-auto max-w-[720px] px-6 py-24 md:py-28">
      <JsonLd data={articleLd} />
      <Link href="/blog" className="text-sm text-[#0066cc] hover:underline">
        ← Blog
      </Link>
      <article className="mt-6">
        <h1 className="text-4xl font-semibold tracking-tight text-[#111111]">
          {post.title}
        </h1>
        <p className="mt-3 text-sm text-[#86868b]">
          {post.author} · {post.datePublished}
        </p>
        <div className="prose prose-neutral mt-10 max-w-none">
          <PostBody markdown={post.body} />
        </div>
      </article>
    </main>
  );
}
