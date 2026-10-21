'use client';

import Link from 'next/link';
import type React from 'react';
import * as AlertDialog from '@radix-ui/react-alert-dialog';

type DashboardAction = {
  label: string;
  href?: string;
  onClick?: () => void;
};

type Tone = 'neutral' | 'blue' | 'green' | 'amber' | 'red' | 'dark';

function toneClass(tone: Tone = 'neutral'): string {
  switch (tone) {
    case 'blue':
      return 'bg-[#e8f2ff] text-[#0b5cab] border-[#b8d7ff]';
    case 'green':
      return 'bg-[#e9f8ed] text-[#146c2e] border-[#b9e8c4]';
    case 'amber':
      return 'bg-[#fff4d6] text-[#7a4d00] border-[#ffe09a]';
    case 'red':
      return 'bg-[#fee2e2] text-[#7f1d1d] border-[#fecaca]';
    case 'dark':
      return 'bg-[#1d1d1f] text-white border-[#1d1d1f]';
    default:
      return 'bg-white text-[var(--fg-chrome)] border-[rgba(29,29,31,0.10)]';
  }
}

function ActionLink({
  action,
  variant,
}: {
  action: DashboardAction;
  variant: 'primary' | 'secondary' | 'danger';
}): React.JSX.Element {
  const className =
    variant === 'primary'
      ? 'inline-flex items-center justify-center rounded-full bg-[var(--signal)] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--signal-deep)]'
      : variant === 'danger'
        ? 'inline-flex items-center justify-center rounded-full border border-[rgba(229,72,77,0.30)] bg-white px-5 py-2.5 text-sm font-semibold text-[var(--rec)] transition hover:bg-[rgba(229,72,77,0.06)]'
        : 'inline-flex items-center justify-center rounded-full border border-[rgba(29,29,31,0.10)] bg-white px-5 py-2.5 text-sm font-semibold text-[var(--fg-chrome)] transition hover:text-[var(--signal)]';

  if (action.href) {
    return (
      <Link href={action.href} className={className}>
        {action.label}
      </Link>
    );
  }

  return (
    <button type="button" onClick={action.onClick} className={className}>
      {action.label}
    </button>
  );
}

export function StatusPill({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  tone?: Tone;
}): React.JSX.Element {
  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${toneClass(tone)}`}>
      {children}
    </span>
  );
}

export function DashboardPageHeader({
  title,
  description,
  primaryAction,
  secondaryAction,
  status,
}: {
  title: string;
  description: string;
  primaryAction?: DashboardAction;
  secondaryAction?: DashboardAction;
  status?: string;
}): React.JSX.Element {
  return (
    <section className="dashboard-command-header">
      <div className="min-w-0">
        <h1>{title}</h1>
        <p>{description}</p>
        {status && (
          <div className="mt-3">
            <StatusPill tone="blue">{status}</StatusPill>
          </div>
        )}
      </div>
      {(primaryAction || secondaryAction) && (
        <div className="dashboard-command-header-actions">
          {primaryAction && <ActionLink action={primaryAction} variant="primary" />}
          {secondaryAction && <ActionLink action={secondaryAction} variant="secondary" />}
        </div>
      )}
    </section>
  );
}

export function CommandCard({
  children,
  title,
  description,
  action,
  className = '',
}: {
  children: React.ReactNode;
  title?: string;
  description?: string;
  action?: DashboardAction;
  className?: string;
}): React.JSX.Element {
  return (
    <section className={`dashboard-command-card ${className}`}>
      {(title || description || action) && (
        <div className="dashboard-command-card-header">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {action && <ActionLink action={action} variant="secondary" />}
        </div>
      )}
      {children}
    </section>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: DashboardAction;
}): React.JSX.Element {
  return (
    <div className="dashboard-empty-state">
      <div className="dashboard-empty-orb">P</div>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && <ActionLink action={action} variant="primary" />}
    </div>
  );
}

export function ActionBar({
  primary,
  secondary,
  danger,
}: {
  primary?: DashboardAction;
  secondary?: DashboardAction;
  danger?: DashboardAction;
}): React.JSX.Element {
  return (
    <div className="dashboard-action-bar">
      <div className="flex flex-wrap items-center gap-3">
        {secondary && <ActionLink action={secondary} variant="secondary" />}
        {primary && <ActionLink action={primary} variant="primary" />}
      </div>
      {danger && <ActionLink action={danger} variant="danger" />}
    </div>
  );
}

/**
 * Accessible confirm dialog built on Radix AlertDialog: focus trap, Esc to
 * dismiss, scroll lock, and aria wiring all come from Radix. `trigger` must be
 * a single interactive element (it becomes the dialog trigger via asChild).
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  onConfirm,
  trigger,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  trigger: React.ReactNode;
}): React.JSX.Element {
  return (
    <AlertDialog.Root>
      <AlertDialog.Trigger asChild>{trigger}</AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="dashboard-confirm-backdrop" />
        <AlertDialog.Content className="dashboard-confirm-panel fixed left-1/2 top-1/2 z-[101] -translate-x-1/2 -translate-y-1/2">
          <AlertDialog.Title>{title}</AlertDialog.Title>
          <AlertDialog.Description>{description}</AlertDialog.Description>
          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <AlertDialog.Cancel asChild>
              <button
                type="button"
                className="rounded-full border bg-white px-5 py-2.5 text-sm font-semibold text-[var(--fg-chrome)]"
                style={{ borderColor: 'rgba(29,29,31,0.10)' }}
              >
                {cancelLabel}
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                onClick={onConfirm}
                className="rounded-full bg-[var(--rec)] px-5 py-2.5 text-sm font-semibold text-white"
              >
                {confirmLabel}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
