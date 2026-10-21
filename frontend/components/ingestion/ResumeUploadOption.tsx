'use client';

import React from 'react';
import type { UploadKind } from '@/lib/ingestionUploadKind';

interface ResumeUploadOptionProps {
  kind: UploadKind;
  disabled?: boolean;
  onChange: (kind: UploadKind) => void;
}

export default function ResumeUploadOption({ kind, disabled, onChange }: ResumeUploadOptionProps) {
  const isResume = kind === 'resume';
  return (
    <div className="mt-4">
      <label className="flex items-start gap-2 text-sm text-slate-600 cursor-pointer">
        <input
          type="checkbox"
          checked={isResume}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? 'resume' : 'knowledge')}
          className="mt-0.5 h-4 w-4 rounded border-slate-300"
        />
        <span>
          <span className="font-bold text-slate-700">This file is my resume / CV</span>{' '}
          (adds proposed profile facts for your review)
        </span>
      </label>
      {isResume && (
        <p className="mt-2 ml-6 text-xs text-slate-500">
          We&apos;ll read your next uploaded file as your resume and suggest profile facts from it.
          Nothing changes on your persona until you approve them.
        </p>
      )}
    </div>
  );
}
