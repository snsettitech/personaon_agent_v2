import type { ReactNode } from 'react';

// Marketplace is dormant — pages render but no user-facing surface promotes
// them. When we unlock at 100k users, add nav/footer links and the existing
// pages light up. No redirect gate; discovery is gated by absence of links.
export default function MarketplaceLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
