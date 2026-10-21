import { resolveApiBaseUrl } from '@/lib/api';

type RouteContext = {
  params: Promise<{ token: string }>;
};

async function proxyUnsubscribe(request: Request, context: RouteContext, method: 'GET' | 'POST') {
  const { token } = await context.params;
  const requestUrl = new URL(request.url);
  const backendUrl = new URL(
    `/v2/notifications/unsubscribe/${encodeURIComponent(token)}`,
    resolveApiBaseUrl()
  );

  requestUrl.searchParams.forEach((value, key) => {
    backendUrl.searchParams.append(key, value);
  });

  const headers = new Headers();
  const contentType = request.headers.get('content-type');
  if (contentType) {
    headers.set('content-type', contentType);
  }

  const response = await fetch(backendUrl.toString(), {
    method,
    headers,
    body: method === 'POST' ? await request.text() : undefined,
    cache: 'no-store',
  });
  const text = await response.text();

  return new Response(text, {
    status: response.status,
    headers: {
      'Content-Type': response.headers.get('content-type') || 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

export async function GET(request: Request, context: RouteContext) {
  return proxyUnsubscribe(request, context, 'GET');
}

export async function POST(request: Request, context: RouteContext) {
  return proxyUnsubscribe(request, context, 'POST');
}
