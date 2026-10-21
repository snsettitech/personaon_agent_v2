import { NextResponse } from 'next/server';

import { adminBackendFetch } from '@/lib/admin-backend';

export async function GET() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL
    || process.env.NEXT_PUBLIC_API_URL
    || process.env.NEXT_PUBLIC_BACKEND_API_URL;
  if (!backendUrl) {
    return NextResponse.json(
      { error: 'NEXT_PUBLIC_BACKEND_URL is not configured' },
      { status: 503 },
    );
  }

  const [healthResponse, versionResponse, twinsResponse] = await Promise.all([
    fetch(`${backendUrl}/observability/health`, {
      cache: 'no-store',
    }),
    fetch(`${backendUrl}/version`, {
      cache: 'no-store',
    }),
    adminBackendFetch('/auth/my-twins'),
  ]);

  if (!twinsResponse.ok) {
    const text = await twinsResponse.text();
    return new Response(text, {
      status: twinsResponse.status,
      headers: {
        'Content-Type': twinsResponse.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
      },
    });
  }

  const [health, version, twins] = await Promise.all([
    healthResponse.ok ? healthResponse.json() : Promise.resolve(null),
    versionResponse.ok ? versionResponse.json() : Promise.resolve(null),
    twinsResponse.json(),
  ]);

  return NextResponse.json(
    {
      health,
      version,
      twins: Array.isArray(twins) ? twins : [],
    },
    {
      headers: {
        'Cache-Control': 'no-store',
      },
    }
  );
}
