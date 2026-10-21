'use client';

import React from 'react';

interface ResumeUploadNoticeProps {
  message: string;
  onDismiss: () => void;
}

export default function ResumeUploadNotice({ message, onDismiss }: ResumeUploadNoticeProps) {
  return (
    <div className="px-6 pb-6">
      <div
        role="status"
        className="p-4 bg-emerald-50 border border-emerald-100 rounded-xl text-emerald-800 text-sm font-medium flex items-start gap-3"
      >
        <span className="flex-1">{message}</span>
        <button
          onClick={onDismiss}
          className="text-xs text-emerald-600 hover:text-emerald-800 underline"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
