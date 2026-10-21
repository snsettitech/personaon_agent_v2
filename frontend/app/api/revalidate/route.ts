import { revalidatePath } from "next/cache";
import { NextResponse, type NextRequest } from "next/server";

/**
 * On-demand revalidation for persona SEO surfaces.
 *
 * The backend calls `POST /api/revalidate` with a shared-secret header whenever
 * a persona is published / its handle or public profile changes, so the SSR
 * persona page refreshes immediately instead of waiting for the 1h ISR window.
 *
 * Active in prod: REVALIDATE_TOKEN is configured on both the frontend and backend
 * services (shared revalidate-token secret). If the token is ever unset this
 * returns 503/401 and the backend skips the call.
 */
export async function POST(req: NextRequest): Promise<NextResponse> {
  const expected = process.env.REVALIDATE_TOKEN;
  if (!expected) {
    return NextResponse.json(
      { error: "revalidation not configured" },
      { status: 503 },
    );
  }
  if (req.headers.get("x-revalidate-token") !== expected) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  let handle: string | undefined;
  try {
    const body: unknown = await req.json();
    const raw = (body as { handle?: unknown })?.handle;
    handle = typeof raw === "string" ? raw.trim().toLowerCase() : undefined;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!handle) {
    return NextResponse.json({ error: "handle required" }, { status: 400 });
  }

  // revalidatePath refreshes the page's cached render + its data fetches
  // (including getProfile), so /p/{handle} reflects the edit immediately. The
  // sitemap refreshes on its own 1h ISR window. (Next 16's revalidateTag now
  // requires a cache-profile arg; revalidatePath is the simpler, sufficient tool.)
  revalidatePath(`/p/${handle}`);
  revalidatePath(`/marketplace/${handle}`);

  return NextResponse.json({ revalidated: true, handle });
}
