'use client';

import React from 'react';

interface ToggleProps {
    checked: boolean;
    onChange: (checked: boolean) => void;
    label?: string;
    description?: string;
    disabled?: boolean;
}

export function Toggle({ checked, onChange, label, description, disabled = false }: ToggleProps) {
    return (
        <label className={`flex items-start gap-4 ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
            <button
                type="button"
                role="switch"
                aria-checked={checked}
                disabled={disabled}
                onClick={() => !disabled && onChange(!checked)}
                className={`
          relative inline-flex h-6 w-11 shrink-0 
          rounded-full border-2 border-transparent 
          transition-all duration-300 ease-in-out
          focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
          ${checked
                        ? 'bg-gradient-to-r from-blue-500 to-blue-500 shadow-lg shadow-blue-500/30'
                        : 'bg-slate-200'
                    }
        `}
            >
                <span
                    className={`
            pointer-events-none inline-block h-5 w-5 
            transform rounded-full bg-white shadow-lg 
            ring-0 transition-transform duration-300 ease-in-out
            ${checked ? 'translate-x-5' : 'translate-x-0'}
          `}
                />
            </button>

            {(label || description) && (
                <div className="flex flex-col">
                    {label && (
                        <span className="text-sm font-semibold text-slate-900">{label}</span>
                    )}
                    {description && (
                        <span className="text-sm text-slate-500">{description}</span>
                    )}
                </div>
            )}
        </label>
    );
}
