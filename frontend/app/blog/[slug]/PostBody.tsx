"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders a post's markdown body. Kept as a small client island so the server
 * post page stays a pure Server Component; the content still server-renders.
 */
export default function PostBody({ markdown }: { markdown: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>;
}
