'use client';

import { useRef, useState } from 'react';
import { FileText, UploadCloud } from 'lucide-react';

import { analytics } from '@/lib/analytics/events';

const MAX_BYTES = 10 * 1024 * 1024;
const MONO = "'JetBrains Mono', monospace";
const SANS = "'Geist', sans-serif";

export function UploadStep({ onNext }: { onNext: (file: File) => void }) {
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [picked, setPicked] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const choose = (file: File | null) => {
    if (!file) return;
    const name = file.name.toLowerCase();
    const okExt = name.endsWith('.pdf') || name.endsWith('.docx') || name.endsWith('.txt');
    if (!okExt) {
      setError('Please upload a PDF, DOCX, or TXT file.');
      return;
    }
    if (file.size > MAX_BYTES) {
      setError('That file is over 10MB.');
      return;
    }
    setError('');
    setPicked(file);
  };

  return (
    <div>
      <p className="mb-2 text-[10px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
        Step 1 — Your resume
      </p>
      <h2 className="text-[26px]" style={{ color: 'var(--ink)', fontFamily: "'Instrument Serif', Georgia, serif", lineHeight: 1.1 }}>
        Start with your resume
      </h2>
      <p className="mt-2 text-[14px]" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
        We&apos;ll read it to compile your digital twin. PDF, DOCX, or TXT — up to 10MB.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(e.dataTransfer.files?.[0] ?? null);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click();
        }}
        className="mt-6 flex cursor-pointer flex-col items-center justify-center px-6 py-12 text-center transition-colors"
        style={{
          borderRadius: 20,
          border: `1.5px dashed ${dragging ? 'var(--ink)' : 'rgba(29,29,31,0.18)'}`,
          background: dragging ? 'rgba(29,29,31,0.03)' : 'var(--fog-2)',
        }}
      >
        <span
          className="flex h-12 w-12 items-center justify-center rounded-full"
          style={{ background: 'var(--ink)', color: '#fff' }}
        >
          {picked ? <FileText size={20} /> : <UploadCloud size={20} />}
        </span>
        <p className="mt-4 text-[14px]" style={{ color: 'var(--fg)', fontFamily: SANS, fontWeight: 500 }}>
          {picked ? picked.name : 'Drag & drop your resume, or click to browse'}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          className="hidden"
          onChange={(e) => choose(e.target.files?.[0] ?? null)}
        />
      </div>

      {error && (
        <p className="mt-3 text-[13px]" style={{ color: '#c0392b', fontFamily: SANS }}>
          {error}
        </p>
      )}

      <p className="mt-4 text-[12px]" style={{ color: 'var(--fg-3)', fontFamily: SANS }}>
        Processed in memory to build a temporary demo and discarded automatically — never stored.
      </p>

      <button
        type="button"
        disabled={!picked}
        onClick={() => {
          if (!picked) return;
          // Only type/size — never the filename, which can contain the
          // visitor's real name (resumes are PII).
          analytics.experienceResumeUploaded({ file_type: picked.type || 'unknown', file_size: picked.size });
          onNext(picked);
        }}
        className="mt-7 inline-flex items-center rounded-full px-6 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
        style={{ height: 44, background: 'var(--ink)', color: '#fff', fontFamily: SANS, fontSize: 14, fontWeight: 500 }}
      >
        Continue
      </button>
    </div>
  );
}
