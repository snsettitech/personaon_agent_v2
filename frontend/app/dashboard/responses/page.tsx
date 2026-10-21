'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { motion, type Variants } from 'framer-motion';

import { useToast } from '@/components/ui';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import { useTwin } from '@/lib/context/TwinContext';
import { useAuthFetch } from '@/lib/hooks/useAuthFetch';

type ResponseLength = 'intelligent' | 'concise' | 'explanatory' | 'custom';
type Creativity = 'strict' | 'adaptive' | 'creative';

type ResponseSettings = {
  initialMessage: string;
  noAnswerMessage: string;
  purpose: string;
  customInstructions: string;
  responseLength: ResponseLength;
  customResponseLength: string;
  creativity: Creativity;
  speakingStyle: string;
  showCitations: boolean;
  disclaimer: string;
};

type Option<T extends string> = {
  value: T;
  label: string;
  description: string;
};

const INITIAL_MESSAGE_MAX = 400;
const NO_ANSWER_MAX = 400;
const PURPOSE_MAX = 6000;
const SPEAKING_STYLE_MAX = 5000;
const DISCLAIMER_MAX = 400;
const CUSTOM_RESPONSE_LENGTH_MAX = 400;
const MAX_INSTRUCTIONS = 20;

const responseLengthOptions: Option<ResponseLength>[] = [
  {
    value: 'intelligent',
    label: 'Intelligent',
    description: 'Your persona will choose the best response length for each question.',
  },
  {
    value: 'concise',
    label: 'Concise',
    description: 'Keep answers short and direct.',
  },
  {
    value: 'explanatory',
    label: 'Explanatory',
    description: 'Give more context when a thoughtful answer needs it.',
  },
  {
    value: 'custom',
    label: 'Custom',
    description: 'Use your own response length guidance.',
  },
];

const creativityOptions: Option<Creativity>[] = [
  {
    value: 'strict',
    label: 'Strict',
    description: 'Stay closely grounded in approved profile details and uploaded knowledge.',
  },
  {
    value: 'adaptive',
    label: 'Adaptive',
    description: 'Stay grounded while connecting related ideas naturally.',
  },
  {
    value: 'creative',
    label: 'Creative',
    description: 'Infer what you might say in new situations from training data.',
  },
];

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: 'easeOut' as const } },
};

function normalizeResponseLength(value: unknown): ResponseLength {
  if (value === 'concise') return 'concise';
  if (value === 'explanatory' || value === 'detailed') return 'explanatory';
  if (value === 'custom') return 'custom';
  return 'intelligent';
}

function normalizeCreativity(value: unknown): Creativity {
  if (value === 'strict') return 'strict';
  if (value === 'creative') return 'creative';
  return 'adaptive';
}

function legacyResponseLength(value: ResponseLength): string {
  if (value === 'concise') return 'concise';
  if (value === 'explanatory') return 'detailed';
  return 'balanced';
}

function getInstructionCount(value: string): number {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean).length;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function FieldShell({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <label className="block">
      <div className="mb-2 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{label}</p>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{description}</p>
        </div>
      </div>
      {children}
    </label>
  );
}

function Count({ value, max }: { value: string; max: number }): React.JSX.Element {
  const over = value.length > max;
  return (
    <span className="mt-2 block text-right text-xs font-medium" style={{ color: over ? 'var(--accent-red)' : 'var(--text-muted)' }}>
      {value.length} / {max.toLocaleString()}
    </span>
  );
}

function TextareaField({
  label,
  description,
  value,
  onChange,
  maxLength,
  rows = 4,
  placeholder,
}: {
  label: string;
  description: string;
  value: string;
  onChange: (value: string) => void;
  maxLength: number;
  rows?: number;
  placeholder?: string;
}): React.JSX.Element {
  return (
    <FieldShell label={label} description={description}>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        maxLength={maxLength}
        placeholder={placeholder}
        className="w-full resize-y rounded-2xl px-4 py-3 text-sm leading-6 outline-none transition focus:ring-2 focus:ring-[var(--primary-500)]"
        style={{
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-subtle)',
          color: 'var(--text-primary)',
        }}
      />
      <Count value={value} max={maxLength} />
    </FieldShell>
  );
}

function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
}): React.JSX.Element {
  const selected = options.find((option) => option.value === value) ?? options[0];

  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className="rounded-2xl border px-4 py-3 text-left text-sm font-semibold transition"
              style={{
                backgroundColor: active ? '#1d1d1f' : 'var(--bg-elevated)',
                borderColor: active ? '#1d1d1f' : 'var(--border-subtle)',
                color: active ? '#ffffff' : 'var(--text-primary)',
              }}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      <p className="mt-3 text-sm" style={{ color: 'var(--text-muted)' }}>{selected.description}</p>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="relative h-7 w-12 rounded-full transition"
      style={{ backgroundColor: checked ? 'var(--primary-600)' : 'var(--border-default)' }}
    >
      <span
        className="absolute left-0 top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform"
        style={{ transform: checked ? 'translateX(22px)' : 'translateX(4px)' }}
      />
    </button>
  );
}

export default function ResponsesPage(): React.JSX.Element {
  const { activeTwin, isLoading, refreshTwins } = useTwin();
  const { patch } = useAuthFetch();
  const { showToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const displayName = formatPersonaDisplayName(activeTwin?.name);

  const defaultNoAnswerMessage = useMemo(() => {
    if (displayName && displayName !== 'Your Persona') {
      return `Sorry, I can't answer that yet. Let me ask the real ${displayName} and get back to you.`;
    }
    return "Sorry, I can't answer that yet. Let me ask the real person and get back to you.";
  }, [displayName]);

  const [form, setForm] = useState<ResponseSettings>({
    initialMessage: 'How can I help?',
    noAnswerMessage: '',
    purpose: '',
    customInstructions: '',
    responseLength: 'intelligent',
    customResponseLength: '',
    creativity: 'adaptive',
    speakingStyle: '',
    showCitations: true,
    disclaimer: '',
  });

  useEffect(() => {
    const settings = asRecord(activeTwin?.settings);
    const responses = asRecord(settings.responses);
    const personality = asRecord(settings.personality);
    const publicProfile = asRecord(settings.public_profile);
    const customInstructions = Array.isArray(responses.customInstructions)
      ? responses.customInstructions.join('\n')
      : String(responses.customInstructions || '');

    setForm({
      initialMessage: String(responses.initialMessage || 'How can I help?'),
      noAnswerMessage: String(responses.noAnswerMessage || defaultNoAnswerMessage),
      purpose: String(responses.purpose || ''),
      customInstructions,
      responseLength: normalizeResponseLength(responses.responseLength || personality.responseLength),
      customResponseLength: String(responses.customResponseLength || ''),
      creativity: normalizeCreativity(responses.creativity),
      speakingStyle: String(responses.speakingStyle || publicProfile.speaking_style || ''),
      showCitations: responses.showCitations !== false,
      disclaimer: String(responses.disclaimer || ''),
    });
    setSaved(false);
  }, [activeTwin?.settings, defaultNoAnswerMessage]);

  const instructionCount = getInstructionCount(form.customInstructions);
  const tooManyInstructions = instructionCount > MAX_INSTRUCTIONS;
  const updateForm = <K extends keyof ResponseSettings>(key: K, value: ResponseSettings[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const saveResponses = async () => {
    if (!activeTwin || tooManyInstructions) return;

    setSaving(true);
    try {
      const currentSettings = asRecord(activeTwin.settings);
      const publicProfile = asRecord(currentSettings.public_profile);
      const personality = asRecord(currentSettings.personality);
      const instructions = form.customInstructions
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, MAX_INSTRUCTIONS);

      const nextSettings = {
        ...currentSettings,
        personality: {
          ...personality,
          responseLength: legacyResponseLength(form.responseLength),
        },
        public_profile: {
          ...publicProfile,
          speaking_style: form.speakingStyle.trim(),
        },
        responses: {
          initialMessage: form.initialMessage.trim(),
          noAnswerMessage: form.noAnswerMessage.trim(),
          purpose: form.purpose.trim(),
          customInstructions: instructions,
          responseLength: form.responseLength,
          customResponseLength: form.customResponseLength.trim(),
          creativity: form.creativity,
          speakingStyle: form.speakingStyle.trim(),
          showCitations: form.showCitations,
          disclaimer: form.disclaimer.trim(),
          updatedAt: new Date().toISOString(),
        },
      };

      const response = await patch(`/twins/${activeTwin.id}`, { settings: nextSettings });
      if (!response.ok) {
        throw new Error(`Failed to save responses (${response.status})`);
      }

      await refreshTwins();
      setSaved(true);
      showToast('Responses saved', 'success');
    } catch (error) {
      console.error('[Responses] Save failed:', error);
      showToast('Failed to save responses', 'error');
    } finally {
      setSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-80 items-center justify-center">
        <div className="h-12 w-12 animate-spin rounded-full border-4" style={{ borderColor: 'var(--primary-600)', borderTopColor: 'transparent' }} />
      </div>
    );
  }

  if (!activeTwin) {
    return (
      <div className="rounded-3xl p-8 text-center" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>No persona selected</h2>
        <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>Create or select a persona before editing responses.</p>
      </div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={fadeUp} className="space-y-6 pb-12">
      <section
        className="grid gap-4 rounded-3xl p-6 lg:grid-cols-[1.35fr_0.65fr]"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
            Persona response setup
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
            Control how {displayName} responds.
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6" style={{ color: 'var(--text-secondary)' }}>
            Set the greeting, fallback answer, style, and boundaries your persona should use in chat and public conversations.
          </p>
        </div>
        <div
          className="rounded-2xl p-4"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
        >
          <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Saved to persona settings</p>
          <p className="mt-1 text-sm leading-6" style={{ color: 'var(--text-muted)' }}>
            These settings stay with the selected persona and can be updated any time.
          </p>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
          <TextareaField
            label="Initial Message"
            description="The first message your persona sends when starting a new conversation."
            value={form.initialMessage}
            onChange={(value) => updateForm('initialMessage', value)}
            maxLength={INITIAL_MESSAGE_MAX}
            rows={3}
            placeholder="How can I help?"
          />
        </div>

        <div className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
          <TextareaField
            label="Message on No Answer"
            description="Your persona's response when it does not have enough information."
            value={form.noAnswerMessage}
            onChange={(value) => updateForm('noAnswerMessage', value)}
            maxLength={NO_ANSWER_MAX}
            rows={3}
          />
        </div>
      </section>

      <section className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        <TextareaField
          label="Purpose"
          description="This shapes training and informs how your persona responds."
          value={form.purpose}
          onChange={(value) => updateForm('purpose', value)}
          maxLength={PURPOSE_MAX}
          rows={6}
          placeholder="This persona is a..."
        />
      </section>

      <section className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        <FieldShell
          label="Custom Instructions"
          description="Add short instructions for your persona to follow during interactions."
        >
          <textarea
            value={form.customInstructions}
            onChange={(event) => updateForm('customInstructions', event.target.value)}
            rows={6}
            placeholder={"Answer in first person.\nAsk for clarification before guessing.\nAvoid topics not covered in my knowledge."}
            className="w-full resize-y rounded-2xl px-4 py-3 text-sm leading-6 outline-none transition focus:ring-2 focus:ring-[var(--primary-500)]"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-primary)',
            }}
          />
          <div className="mt-2 flex items-center justify-between gap-3 text-xs font-medium">
            <span style={{ color: tooManyInstructions ? 'var(--accent-red)' : 'var(--text-muted)' }}>
              {instructionCount} / {MAX_INSTRUCTIONS} instructions
            </span>
            <span style={{ color: 'var(--text-muted)' }}>One instruction per line</span>
          </div>
        </FieldShell>
      </section>

      <section className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        <div className="mb-4">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Response Length</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>How long responses to users should be.</p>
        </div>
        <SegmentedControl
          value={form.responseLength}
          options={responseLengthOptions}
          onChange={(value) => updateForm('responseLength', value)}
        />
        {form.responseLength === 'custom' ? (
          <div className="mt-5">
            <TextareaField
              label="Custom response length"
              description="Describe when your persona should be brief or detailed."
              value={form.customResponseLength}
              onChange={(value) => updateForm('customResponseLength', value)}
              maxLength={CUSTOM_RESPONSE_LENGTH_MAX}
              rows={3}
              placeholder="Start concise. Add detail when the topic is complex or the visitor asks for more."
            />
          </div>
        ) : null}
      </section>

      <section className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        <div className="mb-4">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Creativity</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>How closely your persona should follow uploaded knowledge.</p>
        </div>
        <SegmentedControl
          value={form.creativity}
          options={creativityOptions}
          onChange={(value) => updateForm('creativity', value)}
        />
      </section>

      <section className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        <TextareaField
          label="Speaking Style"
          description="Define how your persona speaks and writes."
          value={form.speakingStyle}
          onChange={(value) => updateForm('speakingStyle', value)}
          maxLength={SPEAKING_STYLE_MAX}
          rows={6}
          placeholder="Warm and conversational, uses simple language, and explains ideas clearly."
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div
          className="flex items-start justify-between gap-4 rounded-3xl p-6"
          style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
        >
          <div className="min-w-0">
            <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Show Citations</h2>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
              Allow users to view the sources used for responses.
            </p>
          </div>
          <div className="shrink-0 pt-0.5">
            <Toggle checked={form.showCitations} onChange={(checked) => updateForm('showCitations', checked)} />
          </div>
        </div>

        <div className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
          <TextareaField
            label="Disclaimer"
            description="Optional warning shown on your persona profile."
            value={form.disclaimer}
            onChange={(value) => updateForm('disclaimer', value)}
            maxLength={DISCLAIMER_MAX}
            rows={3}
            placeholder="Example: This persona is for educational purposes only."
          />
        </div>
      </section>

      {tooManyInstructions ? (
        <div className="rounded-2xl px-4 py-3 text-sm font-medium" style={{ backgroundColor: 'var(--accent-red-light)', color: 'var(--accent-red)' }}>
          Keep custom instructions to {MAX_INSTRUCTIONS} lines or fewer before saving.
        </div>
      ) : null}

      <div className="sticky bottom-4 z-20 flex justify-end">
        <button
          type="button"
          onClick={saveResponses}
          disabled={saving || tooManyInstructions}
          className="rounded-full px-6 py-3 text-sm font-semibold text-white shadow-[0_18px_44px_rgba(30,124,255,0.22)] transition disabled:opacity-50"
          style={{ backgroundColor: saved ? 'var(--accent-emerald)' : 'var(--primary-600)' }}
        >
          {saving ? 'Saving...' : saved ? 'Saved' : 'Save Responses'}
        </button>
      </div>
    </motion.div>
  );
}
