import mammoth from 'mammoth';
// The pdf-parse entry module runs a debug file-read when imported without a parent
// module; importing the lib entry directly avoids that side effect.
import pdfParse from 'pdf-parse/lib/pdf-parse.js';

export const MAX_RESUME_BYTES = 10 * 1024 * 1024; // 10MB
const MAX_CHARS = 15000; // keep the extraction prompt bounded

const ALLOWED_MIME = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
]);

export interface ParsedResume {
  text: string;
  chars: number;
}

/** Returns an error message if the file is invalid, else null. */
export function validateResume(file: { type: string; size: number; name: string }): string | null {
  if (!file || file.size === 0) return 'Please choose a resume file.';
  if (file.size > MAX_RESUME_BYTES) return 'Resume is too large (max 10MB).';
  const name = file.name.toLowerCase();
  const okExt = name.endsWith('.pdf') || name.endsWith('.docx') || name.endsWith('.txt');
  if (!ALLOWED_MIME.has(file.type) && !okExt) return 'Please upload a PDF, DOCX, or TXT resume.';
  return null;
}

export async function extractResumeText(buffer: Buffer, filename: string, mime: string): Promise<ParsedResume> {
  const name = filename.toLowerCase();
  let text = '';

  if (name.endsWith('.pdf') || mime === 'application/pdf') {
    const res = await pdfParse(buffer);
    text = res.text || '';
  } else if (name.endsWith('.docx') || mime.includes('word')) {
    const res = await mammoth.extractRawText({ buffer });
    text = res.value || '';
  } else {
    text = buffer.toString('utf8');
  }

  text = text
    .replace(/ /g, ' ')
    .replace(/[ \t]+/g, ' ')
    // Collapse letter-spaced words that styled headers produce and pdf-parse emits
    // verbatim (e.g. "S A I N A T H  S E T T I" -> "SAINATH SETTI"), so the person's
    // name and section headers extract correctly instead of confusing the compiler.
    .replace(/\b[A-Za-z](?: [A-Za-z]){2,}\b/g, (m) => m.replace(/ /g, ''))
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  if (text.length > MAX_CHARS) text = text.slice(0, MAX_CHARS);
  return { text, chars: text.length };
}
