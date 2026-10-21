import { NextResponse } from 'next/server';

import { DEMO_BUILD_LIMIT, quotaExceeded, readQuota, remainingBuilds } from '@/lib/experience/deviceLimit';

// Reads the signed quota cookie so the client can show the "free previews used"
// state on page load, before the visitor bothers uploading a resume. Enforcement
// still happens server-side in the analyze route — this is a UX hint only.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const quota = readQuota(req);
  return NextResponse.json({
    limit: DEMO_BUILD_LIMIT,
    remaining: remainingBuilds(quota),
    exhausted: quotaExceeded(quota),
  });
}
