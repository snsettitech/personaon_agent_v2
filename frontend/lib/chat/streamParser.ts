/**
 * Shared SSE stream parser for chat endpoints.
 * Handles Server-Sent Events (SSE) format from the v2 chat API:
 *   event: <type>
 *   data: <json>
 *
 * Also handles NDJSON as a fallback for backward compatibility.
 */

export type ChatStreamEventType = 'metadata' | 'clarify' | 'content' | 'done' | 'error';

export interface ChatStreamCallbacks {
  onMetadata?: (data: Record<string, unknown>) => void;
  onClarify?: (data: Record<string, unknown>) => void;
  onContent?: (data: { content?: string }) => void;
  onDone?: (data?: Record<string, unknown>) => void;
  onError?: (data?: Record<string, unknown>) => void;
  onBytesReceived?: () => void;
}

function dispatchEvent(
  eventType: string,
  data: Record<string, unknown>,
  callbacks: ChatStreamCallbacks
): void {
  if (eventType === 'clarify') {
    callbacks.onClarify?.(data);
  } else if (eventType === 'answer_metadata' || eventType === 'metadata') {
    callbacks.onMetadata?.(data);
  } else if (eventType === 'message' || eventType === 'answer_token' || eventType === 'content') {
    // SSE uses event: message with data: {"text": "..."}, map to onContent
    const content = (data.text as string) ?? (data.content as string) ?? '';
    callbacks.onContent?.({ content });
  } else if (eventType === 'done') {
    callbacks.onDone?.(data);
  } else if (eventType === 'error') {
    callbacks.onError?.(data);
  } else if (eventType === 'session') {
    // Session event — metadata about the conversation, dispatch as metadata
    callbacks.onMetadata?.(data);
  }
}

/**
 * Parse a chat stream (SSE or NDJSON) and invoke callbacks for each event type.
 * Resolves when the stream ends or is aborted.
 */
export async function parseChatStream(
  body: ReadableStream<Uint8Array>,
  callbacks: ChatStreamCallbacks,
  options?: { signal?: AbortSignal }
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (options?.signal?.aborted) break;

      if (value) {
        callbacks.onBytesReceived?.();
        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            currentEvent = '';
            continue;
          }

          // SSE format: "event: <type>" followed by "data: <json>"
          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.slice(6).trim();
            continue;
          }

          if (trimmed.startsWith('data:')) {
            const rawData = trimmed.slice(5).trim();
            if (!rawData) continue;
            try {
              const data = JSON.parse(rawData) as Record<string, unknown>;
              const eventType = currentEvent || (data.type as string) || '';
              dispatchEvent(eventType, data, callbacks);
            } catch {
              // Not JSON — ignore
            }
            currentEvent = '';
            continue;
          }

          // NDJSON fallback: plain JSON line
          try {
            const data = JSON.parse(trimmed) as Record<string, unknown>;
            const type = (data.type as string) || '';
            dispatchEvent(type, data, callbacks);
          } catch {
            // Not JSON — ignore
          }
        }
      }
    }

    // Handle remaining buffer
    const tail = buffer.trim();
    if (tail) {
      // Try SSE data line
      const rawData = tail.startsWith('data:') ? tail.slice(5).trim() : tail;
      if (rawData) {
        try {
          const data = JSON.parse(rawData) as Record<string, unknown>;
          const type = currentEvent || (data.type as string) || '';
          dispatchEvent(type, data, callbacks);
          currentEvent = '';
        } catch {
          // Not JSON — ignore
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
