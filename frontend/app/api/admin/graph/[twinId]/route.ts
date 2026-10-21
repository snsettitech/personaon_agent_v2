import { proxyBackendJsonResponse } from '@/lib/admin-backend';

export async function GET(
  _request: Request,
  context: { params: Promise<{ twinId: string }> }
) {
  const { twinId } = await context.params;
  return proxyBackendJsonResponse(`/admin/graph/diagnostics/${twinId}`);
}
