'use client';

import React from 'react';

interface FeatureGateProps {
  enabled: boolean;
  title: string;
  description: string;
  children: React.ReactNode;
}

export default function FeatureGate({
  enabled,
  title,
  description,
  children,
}: FeatureGateProps) {
  if (enabled) {
    return <>{children}</>;
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6">
      <div className="text-xs font-bold uppercase tracking-wider text-amber-700">
        Feature Flag Disabled
      </div>
      <h2 className="mt-2 text-xl font-bold text-slate-900">{title}</h2>
      <p className="mt-2 text-sm text-slate-700">{description}</p>
      <div className="mt-4 rounded-xl border border-amber-200 bg-white p-3 text-xs text-amber-700">
        This control is intentionally gated. Enable the relevant `NEXT_PUBLIC_FF_*` flag to use it.
      </div>
    </div>
  );
}

