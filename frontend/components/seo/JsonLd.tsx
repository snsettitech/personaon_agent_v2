/**
 * Renders a JSON-LD <script>. Server-component safe (no "use client").
 *
 * Escapes "<" to "<" to prevent a `</script>` (or any `<`) inside the
 * data from breaking out of the script context — the XSS guard recommended by
 * the Next.js JSON-LD guidance.
 *
 * `data` is intentionally a loose record (not `any`) to stay dependency-free.
 * For compile-time schema typing, `schema-dts` can be added later and the
 * prop tightened to `WithContext<T>`.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      // JSON-LD requires a raw <script>; the value is escaped inline below.
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, "\\u003c"),
      }}
    />
  );
}
