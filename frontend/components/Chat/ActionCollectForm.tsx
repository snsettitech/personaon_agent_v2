'use client';

import React, { useState, useCallback } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ActionCollectFormProps {
  fields: string[];           // e.g. ['name', 'email']
  actionLabel: string;        // e.g. 'Book a Coffee Chat'
  description?: string;       // e.g. 'Share your details so we can get back to you'
  onSubmit: (data: Record<string, string>) => void;
  onCancel: () => void;
  submitting: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Capitalize the first letter of a field name for display as label. */
function capitalizeField(field: string): string {
  if (!field) return '';
  return field.charAt(0).toUpperCase() + field.slice(1);
}

/** Determine the HTML input type based on field name. */
function inputTypeForField(field: string): string {
  const lower = field.toLowerCase();
  if (lower === 'email' || lower.endsWith('_email')) return 'email';
  if (lower === 'phone' || lower.endsWith('_phone')) return 'tel';
  if (lower === 'url' || lower === 'website') return 'url';
  return 'text';
}

/** Return a contextual placeholder based on common field names. */
function placeholderForField(field: string): string {
  const lower = field.toLowerCase();
  if (lower === 'email' || lower.endsWith('_email')) return 'you@example.com';
  if (lower === 'name') return 'Your name';
  if (lower === 'message') return 'Your message...';
  if (lower === 'topic') return 'What topic?';
  return capitalizeField(field);
}

/** Check if a field should render as a textarea instead of a single-line input. */
function isTextareaField(field: string): boolean {
  const lower = field.toLowerCase();
  return lower === 'message' || lower === 'description' || lower === 'details' || lower === 'notes';
}

/** Basic validation: all fields required, non-empty after trim, email must contain @. */
function validateFields(
  fields: string[],
  values: Record<string, string>,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const value = (values[field] || '').trim();
    if (!value) {
      errors[field] = `${capitalizeField(field)} is required`;
    } else if (inputTypeForField(field) === 'email' && !value.includes('@')) {
      errors[field] = 'Please enter a valid email address';
    }
  }
  return errors;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ActionCollectForm({
  fields,
  actionLabel,
  description,
  onSubmit,
  onCancel,
  submitting,
}: ActionCollectFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const field of fields) {
      initial[field] = '';
    }
    return initial;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleChange = useCallback((field: string, value: string) => {
    setValues((prev) => ({ ...prev, [field]: value }));
    // Clear error for this field on change
    setErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }, []);

  const handleSubmit = useCallback(() => {
    const validationErrors = validateFields(fields, values);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }
    // Trim all values before submitting
    const trimmed: Record<string, string> = {};
    for (const field of fields) {
      trimmed[field] = (values[field] || '').trim();
    }
    onSubmit(trimmed);
  }, [fields, values, onSubmit]);

  return (
    <div className="rounded-2xl border border-[#0066cc]/12 bg-[#eef5ff]/70 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 bg-gradient-to-r from-[#0066cc] to-[#0b3d91] rounded-lg flex items-center justify-center">
          <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <span className="text-sm font-semibold text-slate-700">{actionLabel}</span>
      </div>

      <p className="text-xs text-slate-500">Please fill in the following to continue:</p>
      {description && (
        <p className="text-sm text-slate-500 mt-1">{description}</p>
      )}

      {/* Field inputs */}
      {fields.map((field) => (
        <div key={field} className="space-y-1">
          <label className="block text-xs font-medium text-slate-600">
            {capitalizeField(field)}
          </label>
          {isTextareaField(field) ? (
            <textarea
              value={values[field] || ''}
              onChange={(e) => handleChange(field, e.target.value)}
              disabled={submitting}
              rows={2}
              placeholder={placeholderForField(field)}
              className={`w-full rounded-xl border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed resize-none ${
                errors[field]
                  ? 'border-rose-300 focus:ring-rose-200 focus:border-rose-400'
                  : 'border-slate-200'
              }`}
            />
          ) : (
            <input
              type={inputTypeForField(field)}
              value={values[field] || ''}
              onChange={(e) => handleChange(field, e.target.value)}
              disabled={submitting}
              placeholder={placeholderForField(field)}
              className={`w-full rounded-xl border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                errors[field]
                  ? 'border-rose-300 focus:ring-rose-200 focus:border-rose-400'
                  : 'border-slate-200'
              }`}
            />
          )}
          {errors[field] && (
            <p className="text-xs text-rose-500">{errors[field]}</p>
          )}
        </div>
      ))}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="bg-gradient-to-r from-[#0066cc] to-[#0b3d91] text-white px-5 py-2 rounded-xl text-xs font-bold uppercase tracking-wider hover:brightness-105 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-[#0066cc]/20 active:scale-95 flex items-center gap-2 cursor-pointer"
        >
          {submitting ? (
            <>
              <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Submitting...</span>
            </>
          ) : (
            <span>Submit</span>
          )}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="text-xs text-slate-400 hover:text-slate-600 transition-colors disabled:cursor-not-allowed cursor-pointer"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
