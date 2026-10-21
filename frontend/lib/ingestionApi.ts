export interface UploadFileWithFallbackParams {
  backendUrl: string;
  twinId: string;
  file: File;
  label?: "identity" | "knowledge" | "policies";
  identityConfirmed?: boolean;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface IngestUrlWithFallbackParams {
  backendUrl: string;
  twinId: string;
  url: string;
  label?: "identity" | "knowledge" | "policies";
  identityConfirmed?: boolean;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface IngestionResponse {
  source_id?: string;
  job_id?: string | null;
  status?: string;
  duplicate?: boolean;
  message?: string;
  /** Resume (identity) uploads only: Passport claims newly proposed. */
  proposed_count?: number;
  [key: string]: unknown;
}

const toErrorMessage = (payload: unknown, fallback: string): string => {
  if (typeof payload === 'string' && payload.trim()) return payload;
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    const message = (payload as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return fallback;
};

const readPayload = async (response: Response): Promise<unknown> => {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

const toIngestionResponse = (payload: unknown): IngestionResponse => {
  if (payload && typeof payload === 'object') {
    return payload as IngestionResponse;
  }
  if (typeof payload === 'string' && payload.trim()) {
    return { message: payload };
  }
  return {};
};

const normalizeMultipartHeaders = (
  headers?: Record<string, string>
): Record<string, string> => {
  const normalized: Record<string, string> = { ...(headers || {}) };
  Object.keys(normalized).forEach((key) => {
    if (key.toLowerCase() === 'content-type') {
      delete normalized[key];
    }
  });
  return normalized;
};

export const uploadFileWithFallback = async ({
  backendUrl,
  twinId,
  file,
  label,
  identityConfirmed,
  headers,
  signal,
}: UploadFileWithFallbackParams): Promise<IngestionResponse> => {
  let response: Response;
  const uploadHeaders = normalizeMultipartHeaders(headers);

  const canonicalFormData = new FormData();
  canonicalFormData.append('file', file);
  if (label) {
    canonicalFormData.append('source_label', label);
  }
  if (typeof identityConfirmed === 'boolean') {
    canonicalFormData.append('identity_confirmed', String(identityConfirmed));
  }
  response = await fetch(`${backendUrl}/ingest/file/${twinId}`, {
    method: 'POST',
    headers: uploadHeaders,
    body: canonicalFormData,
    signal,
  });

  if (response.status === 404) {
    const legacyFormData = new FormData();
    legacyFormData.append('file', file);
    legacyFormData.append('twin_id', twinId);
    if (label) {
      legacyFormData.append('source_label', label);
    }
    if (typeof identityConfirmed === 'boolean') {
      legacyFormData.append('identity_confirmed', String(identityConfirmed));
    }
    response = await fetch(`${backendUrl}/ingest/document`, {
      method: 'POST',
      headers: uploadHeaders,
      body: legacyFormData,
      signal,
    });
  }

  const payload = await readPayload(response);
  if (!response.ok) {
    throw new Error(toErrorMessage(payload, `Upload failed (${response.status})`));
  }

  return toIngestionResponse(payload);
};

export const ingestUrlWithFallback = async ({
  backendUrl,
  twinId,
  url,
  label,
  identityConfirmed,
  headers,
  signal,
}: IngestUrlWithFallbackParams): Promise<IngestionResponse> => {
  let response = await fetch(`${backendUrl}/ingest/url/${twinId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(headers || {}) },
    body: JSON.stringify({
      url,
      source_label: label,
      identity_confirmed: identityConfirmed,
    }),
    signal,
  });

  if (response.status === 404) {
    response = await fetch(`${backendUrl}/ingest/url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(headers || {}) },
      body: JSON.stringify({
        url,
        twin_id: twinId,
        source_label: label,
        identity_confirmed: identityConfirmed,
      }),
      signal,
    });
  }

  const payload = await readPayload(response);
  if (!response.ok) {
    throw new Error(toErrorMessage(payload, `Ingestion failed (${response.status})`));
  }

  return toIngestionResponse(payload);
};
