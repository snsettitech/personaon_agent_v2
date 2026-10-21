/**
 * Auth API Client
 * Connected accounts (LinkedIn, etc.) for onboarding and profile.
 */

import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { API_ENDPOINTS } from '@/lib/constants';

const BASE_URL = resolveApiBaseUrl();

export interface ConnectedAccount {
  id: string;
  user_id: string;
  provider: string;
  provider_user_id?: string;
  profile_snapshot?: {
    profile_url?: string;
    display_name?: string;
    image_url?: string;
    headline?: string;
  };
  created_at: string;
  updated_at: string;
}

export interface ConnectedAccountsResponse {
  accounts: ConnectedAccount[];
}

function normalizeLinkedInProfileUrl(value?: string): string {
  const text = String(value || '').trim();
  if (!text) return '';

  let candidate = text;
  if (candidate.startsWith('/in/')) {
    candidate = `https://www.linkedin.com${candidate}`;
  } else if (
    candidate.toLowerCase().startsWith('linkedin.com/') ||
    candidate.toLowerCase().startsWith('www.linkedin.com/')
  ) {
    candidate = `https://${candidate}`;
  } else if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(candidate)) {
    const slug = candidate.replace(/^\/?in\//i, '').replace(/^\/+|\/+$/g, '');
    if (!slug) return '';
    candidate = `https://www.linkedin.com/in/${slug}`;
  }

  try {
    const url = new URL(candidate);
    const host = url.hostname.toLowerCase();
    const path = url.pathname.replace(/\/+$/, '');
    if (!['linkedin.com', 'www.linkedin.com'].includes(host)) return '';
    if (!['http:', 'https:'].includes(url.protocol)) return '';
    if (!path.toLowerCase().startsWith('/in/')) return '';
    const slug = path.slice(4).replace(/^\/+|\/+$/g, '');
    if (!slug) return '';
    return `https://www.linkedin.com/in/${slug}`;
  } catch {
    return '';
  }
}

function isSynthesizedLinkedInUrl(profileUrl?: string, providerUserId?: string): boolean {
  const normalizedUrl = normalizeLinkedInProfileUrl(profileUrl);
  const normalizedProviderUserId = String(providerUserId || '').trim();
  if (!normalizedUrl || !normalizedProviderUserId) return false;
  return normalizedUrl === `https://www.linkedin.com/in/${normalizedProviderUserId}`;
}

export function selectBestLinkedInAccount(
  accounts: ConnectedAccount[]
): ConnectedAccount | undefined {
  const linkedinAccounts = accounts.filter((account) =>
    ['linkedin', 'linkedin_oidc'].includes(account.provider)
  );
  if (linkedinAccounts.length === 0) return undefined;

  return linkedinAccounts.reduce<ConnectedAccount | undefined>((best, account) => {
    if (!best) return account;

    const currentUrl = normalizeLinkedInProfileUrl(account.profile_snapshot?.profile_url);
    const bestUrl = normalizeLinkedInProfileUrl(best.profile_snapshot?.profile_url);
    const currentHasRealUrl =
      !!currentUrl &&
      !isSynthesizedLinkedInUrl(currentUrl, account.provider_user_id);
    const bestHasRealUrl =
      !!bestUrl &&
      !isSynthesizedLinkedInUrl(bestUrl, best.provider_user_id);
    if (currentHasRealUrl !== bestHasRealUrl) {
      return currentHasRealUrl ? account : best;
    }

    const currentProviderScore = account.provider === 'linkedin_oidc' ? 2 : 1;
    const bestProviderScore = best.provider === 'linkedin_oidc' ? 2 : 1;
    if (currentProviderScore !== bestProviderScore) {
      return currentProviderScore > bestProviderScore ? account : best;
    }

    const currentHasName = Boolean(account.profile_snapshot?.display_name?.trim());
    const bestHasName = Boolean(best.profile_snapshot?.display_name?.trim());
    if (currentHasName !== bestHasName) {
      return currentHasName ? account : best;
    }

    return best;
  }, undefined);
}

export async function getConnectedAccounts(): Promise<ConnectedAccountsResponse> {
  const url = `${BASE_URL}${API_ENDPOINTS.AUTH_CONNECTED_ACCOUNTS}`;
  const response = await authFetchStandalone(url);
  if (!response.ok) {
    return { accounts: [] };
  }
  return response.json();
}
