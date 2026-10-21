import { afterEach, describe, expect, it, mock } from 'bun:test';
import { uploadFileWithFallback } from '@/lib/ingestionApi';
import {
  RESUME_DUPLICATE_NOTICE,
  RESUME_NO_FACTS_NOTICE,
  RESUME_PROPOSED_NOTICE,
  resumeProposedCountNotice,
  resumeUploadNotice,
  uploadLabelFields,
} from '@/lib/ingestionUploadKind';

interface CapturedRequest {
  url: string;
  form: FormData;
}

const originalFetch = globalThis.fetch;

function stubFetch(statuses: number[]): CapturedRequest[] {
  const calls: CapturedRequest[] = [];
  let i = 0;
  const fake = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), form: init?.body as FormData });
    const status = statuses[Math.min(i++, statuses.length - 1)];
    return new Response(JSON.stringify({ source_id: 'src-1', status: 'live' }), { status });
  });
  // Cast: bun's mock() lacks fetch's static `preconnect` member.
  globalThis.fetch = fake as unknown as typeof fetch;
  return calls;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
});

const file = new File(['Jane Doe — Staff Engineer'], 'resume.pdf', { type: 'application/pdf' });

describe('uploadLabelFields', () => {
  it('defaults knowledge uploads to the knowledge label, unconfirmed', () => {
    expect(uploadLabelFields('knowledge')).toEqual({ label: 'knowledge', identityConfirmed: false });
  });

  it('marks resume uploads as confirmed identity sources', () => {
    expect(uploadLabelFields('resume')).toEqual({ label: 'identity', identityConfirmed: true });
  });
});

describe('resumeUploadNotice', () => {
  it('returns nothing for knowledge uploads', () => {
    expect(resumeUploadNotice('knowledge', { source_id: 'x' })).toBeNull();
  });

  it('explains proposed facts for a new resume', () => {
    expect(resumeUploadNotice('resume', { source_id: 'x', duplicate: false })).toBe(RESUME_PROPOSED_NOTICE);
  });

  it('says no facts were proposed for a duplicate resume', () => {
    expect(resumeUploadNotice('resume', { source_id: 'x', duplicate: true })).toBe(RESUME_DUPLICATE_NOTICE);
  });

  it('shows the proposed count when the backend reports one', () => {
    expect(resumeUploadNotice('resume', { duplicate: false, proposed_count: 4 })).toBe(
      resumeProposedCountNotice(4)
    );
    expect(resumeProposedCountNotice(4)).toContain('4 profile facts added as proposals');
    expect(resumeProposedCountNotice(1)).toContain('1 profile fact added as proposals');
  });

  it('shows the count for a re-uploaded file newly marked as a resume', () => {
    expect(resumeUploadNotice('resume', { duplicate: true, proposed_count: 3 })).toBe(
      resumeProposedCountNotice(3)
    );
  });

  it('distinguishes zero new facts for new and duplicate uploads', () => {
    expect(resumeUploadNotice('resume', { duplicate: false, proposed_count: 0 })).toBe(RESUME_NO_FACTS_NOTICE);
    expect(resumeUploadNotice('resume', { duplicate: true, proposed_count: 0 })).toBe(RESUME_DUPLICATE_NOTICE);
  });
});

describe('uploadFileWithFallback form fields', () => {
  it('sends source_label=identity and identity_confirmed=true for a resume', async () => {
    const calls = stubFetch([200]);
    await uploadFileWithFallback({
      backendUrl: 'https://api.test',
      twinId: 'twin-1',
      file,
      ...uploadLabelFields('resume'),
    });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('https://api.test/ingest/file/twin-1');
    expect(calls[0].form.get('source_label')).toBe('identity');
    expect(calls[0].form.get('identity_confirmed')).toBe('true');
  });

  it('sends source_label=knowledge and identity_confirmed=false by default', async () => {
    const calls = stubFetch([200]);
    await uploadFileWithFallback({
      backendUrl: 'https://api.test',
      twinId: 'twin-1',
      file,
      ...uploadLabelFields('knowledge'),
    });
    expect(calls[0].form.get('source_label')).toBe('knowledge');
    expect(calls[0].form.get('identity_confirmed')).toBe('false');
  });

  it('keeps the identity fields on the /ingest/document fallback', async () => {
    const calls = stubFetch([404, 200]);
    await uploadFileWithFallback({
      backendUrl: 'https://api.test',
      twinId: 'twin-1',
      file,
      ...uploadLabelFields('resume'),
    });
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toBe('https://api.test/ingest/document');
    expect(calls[1].form.get('twin_id')).toBe('twin-1');
    expect(calls[1].form.get('source_label')).toBe('identity');
    expect(calls[1].form.get('identity_confirmed')).toBe('true');
  });
});
