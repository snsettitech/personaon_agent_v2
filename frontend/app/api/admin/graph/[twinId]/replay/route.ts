import { proxyBackendJsonResponse } from '@/lib/admin-backend';

export async function POST(
  request: Request,
  context: { params: Promise<{ twinId: string }> }
) {
  const { twinId } = await context.params;
  const body = await request.text();
  return proxyBackendJsonResponse(`/admin/graph/replay-name-research/${twinId}`, {
    method: 'POST',
    body,
    headers: {
      'Content-Type': request.headers.get('content-type') || 'application/json',
    },
  });
}
