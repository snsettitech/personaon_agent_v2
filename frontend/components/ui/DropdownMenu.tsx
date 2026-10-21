'use client';

import * as React from 'react';
import * as RadixDropdown from '@radix-ui/react-dropdown-menu';
import type { LucideIcon } from 'lucide-react';

export interface DropdownMenuItem {
  label: string;
  onSelect: () => void;
  icon?: LucideIcon;
  destructive?: boolean;
}

interface DropdownMenuProps {
  /** Interactive element used as the trigger (rendered via asChild). */
  trigger: React.ReactNode;
  items: DropdownMenuItem[];
  align?: 'start' | 'end';
}

/**
 * Brand-tokened Radix DropdownMenu. Flat white popover + hairline + card
 * shadow; destructive items carry the Record-red status color. Click-outside,
 * Esc, keyboard navigation, and portal positioning all come from Radix —
 * replacing hand-rolled open-state menus that clip and trap focus.
 */
export function DropdownMenu({ trigger, items, align = 'end' }: DropdownMenuProps): React.JSX.Element {
  return (
    <RadixDropdown.Root>
      <RadixDropdown.Trigger asChild>{trigger}</RadixDropdown.Trigger>
      <RadixDropdown.Portal>
        <RadixDropdown.Content
          align={align}
          sideOffset={6}
          className="z-50 min-w-[12rem] overflow-hidden rounded-[14px] border bg-white p-1.5"
          style={{ borderColor: 'var(--fog-line)', boxShadow: 'var(--shadow-card)' }}
        >
          {items.map((item) => (
            <RadixDropdown.Item
              key={item.label}
              onSelect={item.onSelect}
              className={`flex cursor-pointer select-none items-center gap-2 rounded-[10px] px-3 py-2 text-sm outline-none transition data-[highlighted]:bg-[var(--fog-3)] ${
                item.destructive
                  ? 'text-[var(--rec)] data-[highlighted]:bg-[rgba(229,72,77,0.06)]'
                  : 'text-[var(--ink)]'
              }`}
            >
              {item.icon && <item.icon aria-hidden className="h-4 w-4" />}
              {item.label}
            </RadixDropdown.Item>
          ))}
        </RadixDropdown.Content>
      </RadixDropdown.Portal>
    </RadixDropdown.Root>
  );
}
