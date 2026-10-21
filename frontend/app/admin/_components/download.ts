import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

/** Fetch an authenticated CSV endpoint and trigger a browser download. */
export async function downloadCsv(path: string, filename: string): Promise<void> {
  const res = await authFetchStandalone(path);
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
