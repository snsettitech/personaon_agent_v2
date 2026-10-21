import type { Page, Route } from '@playwright/test';

const BACKEND_GLOB = '**';

const CORS_HEADERS: Record<string, string> = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,POST,PATCH,DELETE,OPTIONS',
  'access-control-allow-headers': 'authorization,content-type,x-correlation-id',
};

type JsonRecord = Record<string, unknown>;

function json(obj: unknown): string {
  return JSON.stringify(obj);
}

async function fulfillOptions(route: Route): Promise<void> {
  await route.fulfill({
    status: 204,
    headers: CORS_HEADERS,
    body: '',
  });
}

async function fulfillJson(route: Route, payload: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers: CORS_HEADERS,
    body: json(payload),
  });
}

export interface TrainingHarnessState {
  activeTrainingSessionId: string | null;
  startCalls: number;
  stopCalls: number;
  ownerChatBodies: JsonRecord[];
}

export function createTrainingHarnessState(): TrainingHarnessState {
  return {
    activeTrainingSessionId: null,
    startCalls: 0,
    stopCalls: 0,
    ownerChatBodies: [],
  };
}

export async function registerTrainingModuleRoutes(
  page: Page,
  state: TrainingHarnessState,
): Promise<void> {
  await page.route(`${BACKEND_GLOB}/twins/e2e-twin/clarifications*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    return fulfillJson(route, []);
  });

  await page.route(`${BACKEND_GLOB}/twins/e2e-twin/owner-memory*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    const method = route.request().method();
    const url = route.request().url();
    if (method === 'GET') {
      if (url.includes('status=active') || url.includes('status=proposed') || url.includes('/history')) {
        return fulfillJson(route, []);
      }
      return fulfillJson(route, []);
    }
    return fulfillJson(route, { ok: true });
  });

  await page.route(`${BACKEND_GLOB}/twins/e2e-twin/training-sessions/active*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    const active = !!state.activeTrainingSessionId;
    return fulfillJson(route, {
      active,
      session: active
        ? {
            id: state.activeTrainingSessionId,
            status: 'active',
            metadata: { source: 'e2e' },
          }
        : null,
    });
  });

  await page.route(`${BACKEND_GLOB}/twins/e2e-twin/training-sessions/start*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    state.startCalls += 1;
    state.activeTrainingSessionId = 'ts-e2e-1';
    return fulfillJson(route, {
      session: {
        id: state.activeTrainingSessionId,
        status: 'active',
        metadata: { source: 'training_validate_step' },
      },
    });
  });

  await page.route(`${BACKEND_GLOB}/twins/e2e-twin/training-sessions/*/stop*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    state.stopCalls += 1;
    state.activeTrainingSessionId = null;
    return fulfillJson(route, {
      session: {
        id: 'ts-e2e-1',
        status: 'stopped',
      },
    });
  });

  await page.route(`${BACKEND_GLOB}/twins/e2e-twin/graph-stats*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    return fulfillJson(route, {
      node_count: 0,
      has_graph: false,
      intent_count: 0,
      profile_count: 0,
      top_nodes: [],
    });
  });

  await page.route(`${BACKEND_GLOB}/twins/e2e-twin*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    const method = route.request().method();
    if (method === 'PATCH') {
      const body = route.request().postDataJSON() as JsonRecord;
      return fulfillJson(route, {
        id: 'e2e-twin',
        settings: body.settings || {},
      });
    }
    return fulfillJson(route, {
      id: 'e2e-twin',
      settings: {
        intent_profile: {
          use_case: 'Help answer owner questions',
          audience: 'Team members',
          boundaries: 'No hallucinated claims',
        },
        public_intro: 'E2E twin intro',
      },
    });
  });

  await page.route(`${BACKEND_GLOB}/sources/e2e-twin*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    return fulfillJson(route, []);
  });

  await page.route(`${BACKEND_GLOB}/chat/e2e-twin*`, async (route) => {
    if (route.request().method() === 'OPTIONS') return fulfillOptions(route);
    const body = (route.request().postDataJSON() || {}) as JsonRecord;
    state.ownerChatBodies.push(body);
    const mode = String(body.mode || 'owner');
    const content =
      mode === 'training'
        ? 'Training context answer.'
        : 'Owner chat answer.';
    const payload =
      `${json({ type: 'answer_metadata', conversation_id: `conv-${state.ownerChatBodies.length}`, dialogue_mode: 'ANSWER', owner_memory_refs: [], owner_memory_topics: [], planning_output: { reasoning_trace: 'trace' } })}\n` +
      `${json({ type: 'answer_token', content })}\n` +
      `${json({ type: 'done' })}\n`;
    await route.fulfill({
      status: 200,
      headers: {
        ...CORS_HEADERS,
        'content-type': 'application/x-ndjson',
      },
      body: payload,
    });
  });
}
