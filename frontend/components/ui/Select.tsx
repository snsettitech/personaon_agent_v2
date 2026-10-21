'use client';

// Headless Radix Select styled with the PersonaOn brand kit (pill trigger,
// flat white popover + hairline + shadow-card, signal-blue active). Replaces
// hand-rolled native <select> controls. Accessible by default: keyboard nav,
// type-ahead, focus management, and aria all come from Radix.

import * as React from 'react';
import * as RadixSelect from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  /** Accessible name for the trigger (visually hidden). */
  ariaLabel: string;
  placeholder?: string;
  className?: string;
}

/**
 * Brand-tokened Radix Select. The trigger is a pill matching the dashboard's
 * control vocabulary; the popover is a flat white surface with a hairline and
 * the card shadow (no glass). Active item carries the single Signal accent.
 */
export function Select({
  value,
  onValueChange,
  options,
  ariaLabel,
  placeholder,
  className = '',
}: SelectProps): React.JSX.Element {
  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange}>
      <RadixSelect.Trigger
        aria-label={ariaLabel}
        className={`inline-flex h-10 max-w-[260px] items-center justify-between gap-2 rounded-full border bg-white px-4 text-sm font-semibold text-[var(--ink)] outline-none transition focus:border-[var(--signal)] data-[state=open]:border-[var(--signal)] ${className}`}
        style={{ borderColor: 'var(--fog-line-2)' }}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon>
          <ChevronDown className="h-4 w-4 text-[var(--fg-chrome)]" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>

      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={6}
          className="z-50 overflow-hidden rounded-[14px] border bg-white"
          style={{
            borderColor: 'var(--fog-line)',
            boxShadow: 'var(--shadow-card)',
            minWidth: 'var(--radix-select-trigger-width)',
          }}
        >
          <RadixSelect.Viewport className="p-1.5">
            {options.map((opt) => (
              <RadixSelect.Item
                key={opt.value}
                value={opt.value}
                className="relative flex cursor-pointer select-none items-center rounded-[10px] py-2 pl-3 pr-8 text-sm text-[var(--ink)] outline-none transition data-[highlighted]:bg-[var(--fog-3)] data-[state=checked]:font-semibold"
              >
                <RadixSelect.ItemText>{opt.label}</RadixSelect.ItemText>
                <RadixSelect.ItemIndicator className="absolute right-2.5 inline-flex items-center">
                  <Check className="h-4 w-4 text-[var(--signal)]" />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
