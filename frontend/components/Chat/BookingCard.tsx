'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { analytics } from '@/lib/analytics/events';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BookingCardProps {
  twinId: string;
  apiBaseUrl: string;
  onBooked: (result: { booking_id: string; message: string }) => void;
  onCancel: () => void;
  fallbackUrl?: string;
  /** Persona display name used in the success copy ("{name} will review your booking"). */
  personaName?: string;
  /** Lead ID from public capture — links the booking to the captured lead. */
  leadId?: string | null;
}

interface TimeSlot {
  start: string;   // ISO 8601
  end: string;     // ISO 8601
  available: boolean;
}

interface DateOption {
  date: string;      // YYYY-MM-DD
  label: string;     // e.g. "Mon 31"
  dayName: string;   // e.g. "Mon"
  dayNum: number;    // e.g. 31
}

type BookingStep = 'loading' | 'dates' | 'slots' | 'form' | 'submitting' | 'booked' | 'error';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Generate next N business days from today (Mon-Fri). */
function getNextBusinessDays(count: number): DateOption[] {
  const results: DateOption[] = [];
  const cursor = new Date();
  cursor.setHours(0, 0, 0, 0);

  while (results.length < count) {
    cursor.setDate(cursor.getDate() + 1);
    const day = cursor.getDay();
    // Skip Saturday (6) and Sunday (0)
    if (day === 0 || day === 6) continue;

    const yyyy = cursor.getFullYear();
    const mm = String(cursor.getMonth() + 1).padStart(2, '0');
    const dd = String(cursor.getDate()).padStart(2, '0');

    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    results.push({
      date: `${yyyy}-${mm}-${dd}`,
      label: `${dayNames[day]} ${cursor.getDate()}`,
      dayName: dayNames[day],
      dayNum: cursor.getDate(),
    });
  }

  return results;
}

/** Format an ISO time string to visitor's local time (e.g. "2:30 PM"). */
function formatTimeLocal(isoString: string, timezone: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: timezone,
    });
  } catch {
    // Fallback if timezone is invalid
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  }
}

/** Detect visitor timezone. */
function getVisitorTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

/** Simple email validation. */
function isValidEmail(email: string): boolean {
  return email.includes('@') && email.includes('.');
}

// ---------------------------------------------------------------------------
// Spinner component
// ---------------------------------------------------------------------------

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const sizeClass = size === 'md' ? 'h-6 w-6' : 'h-4 w-4';
  return (
    <svg className={`animate-spin ${sizeClass}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Calendar icon
// ---------------------------------------------------------------------------

function CalendarIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BookingCard({
  twinId,
  apiBaseUrl,
  onBooked,
  onCancel,
  fallbackUrl,
  personaName,
  leadId,
}: BookingCardProps) {
  const timezone = useMemo(() => getVisitorTimezone(), []);
  const dates = useMemo(() => getNextBusinessDays(5), []);

  const [step, setStep] = useState<BookingStep>('dates');
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [slots, setSlots] = useState<TimeSlot[]>([]);
  const [selectedSlot, setSelectedSlot] = useState<TimeSlot | null>(null);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Form fields
  const [visitorName, setVisitorName] = useState('');
  const [visitorEmail, setVisitorEmail] = useState('');
  const [visitorMessage, setVisitorMessage] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  // Fetch slots when a date is selected
  const fetchSlots = useCallback(async (date: string) => {
    setLoadingSlots(true);
    setErrorMessage(null);
    setSlots([]);
    setSelectedSlot(null);

    try {
      // Bug 2 fix: backend expects ?visitor_timezone=. The previous ?timezone=
      // was silently ignored (defaulted to UTC server-side).
      const res = await fetch(
        `${apiBaseUrl}/v2/calendar/${twinId}/slots?date=${date}&visitor_timezone=${encodeURIComponent(timezone)}`,
      );

      if (res.status === 404 || res.status === 422) {
        // Calendar not connected
        analytics.bookingSlotsLoadFailed({ twin_id: twinId, date, reason: 'not_connected' });
        if (fallbackUrl) {
          setErrorMessage('calendar_not_connected');
        } else {
          setErrorMessage('Calendar is not connected. Please ask the owner to connect their calendar.');
        }
        setStep('error');
        setLoadingSlots(false);
        return;
      }

      if (!res.ok) {
        analytics.bookingSlotsLoadFailed({ twin_id: twinId, date, reason: 'server_error' });
        throw new Error(`Failed to fetch slots (${res.status})`);
      }

      const data = await res.json();
      const fetchedSlots = (data.slots || []) as TimeSlot[];
      // Bug 1 fix: backend now returns `available: true` on every slot it
      // surfaces (busy ones are excluded server-side). Keep the filter as a
      // belt-and-suspenders guard against stale clients reading new responses.
      const availableSlots = fetchedSlots.filter((s) => s.available !== false);

      analytics.bookingSlotsLoaded({ twin_id: twinId, date, count: availableSlots.length });

      setSlots(availableSlots);
      setStep('slots');
    } catch {
      analytics.bookingSlotsLoadFailed({ twin_id: twinId, date, reason: 'unknown' });
      setErrorMessage('Could not load available times. Please try again.');
      setStep('error');
    } finally {
      setLoadingSlots(false);
    }
  }, [apiBaseUrl, twinId, timezone, fallbackUrl]);

  // Handle date selection
  const handleDateSelect = useCallback((date: string) => {
    setSelectedDate(date);
    void fetchSlots(date);
  }, [fetchSlots]);

  // Handle slot selection
  const handleSlotSelect = useCallback((slot: TimeSlot) => {
    if (selectedDate) {
      analytics.bookingSlotSelected({ twin_id: twinId, date: selectedDate });
    }
    setSelectedSlot(slot);
    setStep('form');
  }, [twinId, selectedDate]);

  // Validate form
  const validateForm = useCallback((): boolean => {
    const errors: Record<string, string> = {};

    if (!visitorName.trim()) {
      errors.name = 'Name is required';
    }
    if (!visitorEmail.trim()) {
      errors.email = 'Email is required';
    } else if (!isValidEmail(visitorEmail.trim())) {
      errors.email = 'Please enter a valid email address';
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  }, [visitorName, visitorEmail]);

  // Submit booking
  const handleSubmit = useCallback(async () => {
    if (!validateForm() || !selectedSlot) return;

    setStep('submitting');
    setErrorMessage(null);

    try {
      const res = await fetch(`${apiBaseUrl}/v2/calendar/${twinId}/book`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          visitor_name: visitorName.trim(),
          visitor_email: visitorEmail.trim(),
          visitor_message: visitorMessage.trim() || undefined,
          proposed_start: selectedSlot.start,
          proposed_end: selectedSlot.end,
          visitor_timezone: timezone,
          ...(leadId ? { lead_id: leadId } : {}),
        }),
      });

      // Bug 3 fix: backend now returns 409 with {error: "slot_taken"} when
      // the slot was taken between visitor opening the picker and submitting.
      // Bounce them back to the slot grid with a clear message + auto-refresh
      // so they can pick again instead of getting a generic error.
      if (res.status === 409) {
        const errorData = await res.json().catch(() => ({}));
        const detail = (errorData && typeof errorData === 'object' && 'detail' in errorData)
          ? (errorData as { detail: unknown }).detail
          : null;
        const slotTaken = detail && typeof detail === 'object' && 'error' in detail
          && (detail as { error?: string }).error === 'slot_taken';
        if (slotTaken && selectedDate) {
          analytics.bookingSubmitFailed({ twin_id: twinId, reason: 'slot_taken' });
          setSelectedSlot(null);
          setErrorMessage('That time was just taken — please pick another.');
          setStep('slots');
          // Refresh the slot grid so the now-busy time disappears
          void fetchSlots(selectedDate);
          return;
        }
      }

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({ detail: 'Booking failed' }));
        const detail = typeof errorData === 'object' && errorData !== null && 'detail' in errorData
          ? String((errorData as { detail: string }).detail)
          : 'Booking failed. Please try again.';
        throw new Error(detail);
      }

      const data = await res.json();
      analytics.bookingSubmitted({ twin_id: twinId, date: selectedDate || '' });
      setStep('booked');
      // Build the success copy client-side so we can use the real persona name
      // ("Sainath Setti will review your booking") instead of the generic
      // backend fallback ("the owner will review your booking").
      const successMessage = personaName
        ? `Request sent! ${personaName} will review your booking and you'll get a calendar invite once approved.`
        : "Request sent! You'll receive a calendar invite once the owner approves.";
      onBooked({
        booking_id: data.booking_id || data.id || '',
        message: successMessage,
      });
    } catch (err: unknown) {
      analytics.bookingSubmitFailed({ twin_id: twinId, reason: 'server' });
      const message = err instanceof Error ? err.message : 'Booking failed. Please try again.';
      setErrorMessage(message);
      setStep('form');
    }
  }, [apiBaseUrl, twinId, selectedSlot, selectedDate, visitorName, visitorEmail, visitorMessage, timezone, validateForm, onBooked, fetchSlots, personaName]);

  // Go back to date selection
  const handleBack = useCallback(() => {
    if (step === 'form') {
      setSelectedSlot(null);
      setStep('slots');
    } else if (step === 'slots') {
      setSelectedDate(null);
      setSlots([]);
      setStep('dates');
    } else if (step === 'error') {
      setSelectedDate(null);
      setSlots([]);
      setErrorMessage(null);
      setStep('dates');
    }
  }, [step]);

  // Fire bookingDatesLoaded once when the date strip first renders
  useEffect(() => {
    analytics.bookingDatesLoaded({ twin_id: twinId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clear form error on field change
  useEffect(() => {
    if (formErrors.name && visitorName.trim()) {
      setFormErrors((prev) => {
        const next = { ...prev };
        delete next.name;
        return next;
      });
    }
  }, [visitorName, formErrors.name]);

  useEffect(() => {
    if (formErrors.email && visitorEmail.trim()) {
      setFormErrors((prev) => {
        const next = { ...prev };
        delete next.email;
        return next;
      });
    }
  }, [visitorEmail, formErrors.email]);

  // ─── Render: Booked confirmation ──────────────────────────────────
  if (step === 'booked') {
    return (
      <div className="rounded-2xl border border-[#0066cc]/12 bg-[#f3f1ef] p-5 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-r from-[#0066cc] to-[#0b3d91] rounded-xl flex items-center justify-center text-white">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <span className="text-sm font-bold text-slate-800">Booking Requested</span>
        </div>
        <p className="text-sm text-slate-600">
          Your request has been sent! You&apos;ll receive an email confirmation once approved.
        </p>
      </div>
    );
  }

  // ─── Render: Error with fallback ──────────────────────────────────
  if (step === 'error' && errorMessage === 'calendar_not_connected' && fallbackUrl) {
    return (
      <div className="rounded-2xl border border-[#0066cc]/12 bg-[#f3f1ef] p-5 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-r from-[#0066cc] to-[#0b3d91] rounded-xl flex items-center justify-center text-white">
            <CalendarIcon />
          </div>
          <span className="text-sm font-bold text-slate-800">Book a Meeting</span>
        </div>
        <p className="text-sm text-slate-600">
          Use the external booking page to schedule a time:
        </p>
        <a
          href={fallbackUrl && /^https?:\/\//i.test(fallbackUrl) ? fallbackUrl : undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 bg-gradient-to-r from-[#0066cc] to-[#0b3d91] text-white px-5 py-2.5 rounded-xl text-sm font-bold hover:brightness-105 transition-all shadow-lg shadow-[#0066cc]/20"
        >
          Open Booking Page
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-[#0066cc]/12 bg-[#f3f1ef] p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-r from-[#0066cc] to-[#0b3d91] rounded-xl flex items-center justify-center text-white">
            <CalendarIcon />
          </div>
          <span className="text-sm font-bold text-slate-800">Book a Coffee Chat</span>
        </div>
        {(step === 'slots' || step === 'form') && (
          <button
            type="button"
            onClick={handleBack}
            className="text-xs text-slate-400 hover:text-slate-600 transition-colors flex items-center gap-1"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back
          </button>
        )}
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2">
        {['Date', 'Time', 'Details'].map((label, idx) => {
          const stepIndex = step === 'dates' ? 0 : step === 'slots' ? 1 : 2;
          const isActive = idx === stepIndex;
          const isComplete = idx < stepIndex;
          return (
            <div key={label} className="flex items-center gap-1.5">
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-all ${
                  isActive
                    ? 'bg-[#0066cc] text-white'
                    : isComplete
                      ? 'bg-[#dbeafe] text-[#0b3d91]'
                      : 'bg-slate-200 text-slate-400'
                }`}
              >
                {isComplete ? (
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  idx + 1
                )}
              </div>
              <span className={`text-[10px] font-semibold ${isActive ? 'text-slate-700' : 'text-slate-400'}`}>
                {label}
              </span>
              {idx < 2 && (
                <div className={`w-4 h-px ${isComplete ? 'bg-[#93c5fd]' : 'bg-slate-200'}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Timezone notice */}
      <p className="text-[10px] text-slate-400">
        Times shown in {timezone.replace(/_/g, ' ')}
      </p>

      {/* Error state */}
      {step === 'error' && errorMessage && errorMessage !== 'calendar_not_connected' && (
        <div className="space-y-2">
          <p className="text-sm text-red-600">{errorMessage}</p>
          <button
            type="button"
            onClick={handleBack}
            className="text-xs text-[#0066cc] hover:text-[#0b3d91] font-semibold transition-colors"
          >
            Try again
          </button>
        </div>
      )}

      {/* Step 1: Date selector */}
      {step === 'dates' && (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">Select a date:</p>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {dates.map((d) => (
              <button
                key={d.date}
                type="button"
                onClick={() => handleDateSelect(d.date)}
                className={`shrink-0 flex flex-col items-center rounded-xl border px-3 py-2 transition-all ${
                  selectedDate === d.date
                    ? 'border-[#0066cc] bg-[#eef5ff] text-[#0b3d91] shadow-sm'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-[#0066cc]/30 hover:bg-[#eef5ff]/70'
                }`}
              >
                <span className="text-[10px] font-semibold uppercase tracking-wider">{d.dayName}</span>
                <span className="text-lg font-bold leading-tight">{d.dayNum}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Loading slots */}
      {loadingSlots && (
        <div className="flex items-center justify-center py-6">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Spinner size="sm" />
            <span>Loading available times...</span>
          </div>
        </div>
      )}

      {/* Step 2: Time slots */}
      {step === 'slots' && !loadingSlots && (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            Available times for {selectedDate}:
          </p>
          {slots.length === 0 ? (
            <div className="py-4 text-center">
              <p className="text-sm text-slate-500">No available times on this date.</p>
              <button
                type="button"
                onClick={handleBack}
                className="mt-2 text-xs text-[#0066cc] hover:text-[#0b3d91] font-semibold transition-colors"
              >
                Pick another date
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {slots.map((slot) => {
                const timeLabel = formatTimeLocal(slot.start, timezone);
                const isSelected = selectedSlot?.start === slot.start;
                return (
                  <button
                    key={slot.start}
                    type="button"
                    onClick={() => handleSlotSelect(slot)}
                    className={`rounded-xl border px-3 py-2 text-sm font-medium transition-all ${
                      isSelected
                        ? 'border-[#0066cc] bg-[#0066cc] text-white shadow-sm'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-[#0066cc]/30 hover:bg-[#eef5ff]'
                    }`}
                  >
                    {timeLabel}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Step 3: Contact form */}
      {(step === 'form' || step === 'submitting') && selectedSlot && (
        <div className="space-y-3">
          <div className="rounded-xl bg-[#eef5ff] border border-[#0066cc]/12 px-3 py-2 text-xs text-[#0b3d91] flex items-center gap-2">
            <CalendarIcon />
            <span>
              {selectedDate} at {formatTimeLocal(selectedSlot.start, timezone)}
            </span>
          </div>

          {/* Name */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600">Name</label>
            <input
              type="text"
              value={visitorName}
              onChange={(e) => setVisitorName(e.target.value)}
              disabled={step === 'submitting'}
              placeholder="Your name"
              className={`w-full rounded-xl border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                formErrors.name ? 'border-rose-300' : 'border-slate-200'
              }`}
            />
            {formErrors.name && <p className="text-xs text-rose-500">{formErrors.name}</p>}
          </div>

          {/* Email */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600">Email</label>
            <input
              type="email"
              value={visitorEmail}
              onChange={(e) => setVisitorEmail(e.target.value)}
              disabled={step === 'submitting'}
              placeholder="you@example.com"
              className={`w-full rounded-xl border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                formErrors.email ? 'border-rose-300' : 'border-slate-200'
              }`}
            />
            {formErrors.email && <p className="text-xs text-rose-500">{formErrors.email}</p>}
          </div>

          {/* Message (optional) */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600">
              Message <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <textarea
              value={visitorMessage}
              onChange={(e) => setVisitorMessage(e.target.value)}
              disabled={step === 'submitting'}
              placeholder="What would you like to discuss?"
              rows={2}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed resize-none"
            />
          </div>

          {/* Error from submission */}
          {errorMessage && step === 'form' && (
            <p className="text-xs text-rose-500">{errorMessage}</p>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3 pt-1">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={step === 'submitting'}
              className="bg-gradient-to-r from-[#0066cc] to-[#0b3d91] text-white px-5 py-2 rounded-xl text-xs font-bold uppercase tracking-wider hover:brightness-105 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-[#0066cc]/20 active:scale-95 flex items-center gap-2 cursor-pointer"
            >
              {step === 'submitting' ? (
                <>
                  <Spinner size="sm" />
                  <span>Booking...</span>
                </>
              ) : (
                <span>Request Meeting</span>
              )}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={step === 'submitting'}
              className="text-xs text-slate-400 hover:text-slate-600 transition-colors disabled:cursor-not-allowed cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Cancel at bottom for date/slot steps */}
      {(step === 'dates' || (step === 'slots' && !loadingSlots)) && (
        <div className="pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="text-xs text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
