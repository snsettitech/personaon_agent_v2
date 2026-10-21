import type { Metadata } from "next";
import Link from "next/link";

import { getAllPosts } from "@/lib/blog/posts";

export const metadata: Metadata = {
  title: "Blog",
  description:
    "Ideas on maintaining an always-on professional persona — a public page that chats with visitors, captures leads, and stays current in your voice.",
  alternates: { canonical: "/blog" },
  openGraph: {
    title: "Blog | PersonaOn",
    description:
      "Ideas on always-on professional presence and personas maintained by an agent.",
    url: "/blog",
    type: "website",
  },
};

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// Locale-independent date formatting (avoids SSR/client hydration drift).
function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return `${MONTHS[(month ?? 1) - 1]} ${day}, ${year}`;
}

export default function BlogIndexPage() {
  const posts = getAllPosts();
  return (
    <main className="mx-auto max-w-[760px] px-6 py-24 md:py-32">
      <h1 className="text-4xl font-semibold tracking-tight text-[#111111]">Blog</h1>
      <p className="mt-3 text-[#6e6e73]">
        Ideas on maintaining an always-on professional persona — a public page
        that chats with visitors, captures leads, and stays current in your
        voice.
      </p>

      <ul className="mt-12 space-y-10">
        {posts.map((post) => (
          <li key={post.slug}>
            <article>
              <p className="text-xs uppercase tracking-[0.15em] text-[#86868b]">
                {formatDate(post.datePublished)}
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight text-[#111111]">
                <Link href={`/blog/${post.slug}`} className="hover:underline">
                  {post.title}
                </Link>
              </h2>
              <p className="mt-2 text-[#3a3a3c]">{post.description}</p>
              <Link
                href={`/blog/${post.slug}`}
                className="mt-3 inline-block text-sm text-[#0066cc] hover:underline"
              >
                Read →
              </Link>
            </article>
          </li>
        ))}
      </ul>
    </main>
  );
}
