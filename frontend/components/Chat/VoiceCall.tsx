'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Loader2,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  RotateCcw,
  Volume2,
} from 'lucide-react';
import { resolveApiBaseUrl } from '@/lib/api';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

type CallStatus = 'idle' | 'requesting_mic' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'ended';

interface TranscriptEntry {
  role: 'user' | 'agent';
  text: string;
  ts: number;
}

interface CallSessionResponse {
  provider: string;
  session_id: string;
  twin_id: string;
  websocket_url: string;
  voice_available: boolean;
  audio_input?: {
    encoding?: string;
    sample_rate?: number;
  };
  audio_output?: {
    encoding?: string;
    sample_rate?: number;
  };
  expires_at: number;
}

interface VoiceCallProps {
  twinId: string;
  twinName: string;
  avatarUrl?: string | null;
  voiceName?: string | null;
  showVoiceProof?: boolean;
  isPublic?: boolean;
  shareToken?: string | null;
}

interface VoiceCallInnerProps extends VoiceCallProps {
  status: CallStatus;
  transcript: TranscriptEntry[];
  error: string | null;
  setStatus: React.Dispatch<React.SetStateAction<CallStatus>>;
  setTranscript: React.Dispatch<React.SetStateAction<TranscriptEntry[]>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
}

const INPUT_SAMPLE_RATE = 16000;
const DEFAULT_OUTPUT_SAMPLE_RATE = 24000;

function useDurationTimer(running: boolean): string {
  const [seconds, setSeconds] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      setSeconds(0);
      intervalRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [running]);

  const mins = String(Math.floor(seconds / 60)).padStart(2, '0');
  const secs = String(seconds % 60).padStart(2, '0');
  return `${mins}:${secs}`;
}

function createClientRunId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getAudioContextClass(): typeof AudioContext | null {
  if (typeof window === 'undefined') return null;
  return window.AudioContext
    || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    || null;
}

function resampleAudio(input: ArrayLike<number>, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return Float32Array.from(input);
  if (input.length === 0) return new Float32Array();

  const ratio = inputRate / outputRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i += 1) {
    const sourceIndex = i * ratio;
    const before = Math.floor(sourceIndex);
    const after = Math.min(before + 1, input.length - 1);
    const fraction = sourceIndex - before;
    output[i] = input[before] + (input[after] - input[before]) * fraction;
  }

  return output;
}

function floatToPcm16(input: ArrayLike<number>): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function pcm16ToFloat(input: ArrayLike<number>): Float32Array {
  const output = new Float32Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    output[i] = Math.max(-1, Math.min(1, input[i] / 0x8000));
  }
  return output;
}

function normalizeTranscriptRole(role: unknown): 'user' | 'agent' {
  return role === 'user' ? 'user' : 'agent';
}

function statusLabel(status: CallStatus, isMuted: boolean): string {
  if (status === 'requesting_mic') return 'Waiting for microphone';
  if (status === 'connecting') return 'Connecting';
  if (isMuted && status !== 'ended' && status !== 'idle') return 'Muted';
  if (status === 'thinking') return 'Thinking';
  if (status === 'speaking') return 'Speaking';
  if (status === 'listening') return 'Listening';
  if (status === 'ended') return 'Call ended';
  return 'Ready';
}

function isCallRunning(status: CallStatus): boolean {
  return status === 'listening' || status === 'thinking' || status === 'speaking';
}

export default function VoiceCall(props: VoiceCallProps) {
  const [status, setStatus] = useState<CallStatus>('idle');
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  return (
    <VoiceCallInner
      {...props}
      status={status}
      transcript={transcript}
      error={error}
      setStatus={setStatus}
      setTranscript={setTranscript}
      setError={setError}
    />
  );
}

function VoiceCallInner({
  twinId,
  twinName,
  avatarUrl,
  voiceName,
  showVoiceProof = true,
  isPublic = false,
  shareToken,
  status,
  transcript,
  error,
  setStatus,
  setTranscript,
  setError,
}: VoiceCallInnerProps) {
  const apiBase = resolveApiBaseUrl();
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const websocketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const inputAudioContextRef = useRef<AudioContext | null>(null);
  const outputAudioContextRef = useRef<AudioContext | null>(null);
  const mediaSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const scheduledSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const nextPlayTimeRef = useRef(0);
  const callRunIdRef = useRef<string | null>(null);
  const endingRef = useRef(false);
  const outputSampleRateRef = useRef(DEFAULT_OUTPUT_SAMPLE_RATE);
  const isMutedRef = useRef(false);
  const [isMuted, setIsMuted] = useState(false);
  const duration = useDurationTimer(isCallRunning(status));

  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  const stopScheduledAudio = useCallback(() => {
    scheduledSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        // Source may already have ended.
      }
    });
    scheduledSourcesRef.current.clear();
    nextPlayTimeRef.current = outputAudioContextRef.current?.currentTime ?? 0;
  }, []);

  const cleanupCallResources = useCallback(() => {
    const websocket = websocketRef.current;
    websocketRef.current = null;
    if (websocket && websocket.readyState !== WebSocket.CLOSED) {
      try {
        websocket.close();
      } catch {
        // Ignore close races during teardown.
      }
    }

    const processor = processorRef.current;
    processorRef.current = null;
    if (processor) {
      processor.onaudioprocess = null;
      try {
        processor.disconnect();
      } catch {
        // Already disconnected.
      }
    }

    const mediaSource = mediaSourceRef.current;
    mediaSourceRef.current = null;
    if (mediaSource) {
      try {
        mediaSource.disconnect();
      } catch {
        // Already disconnected.
      }
    }

    const stream = mediaStreamRef.current;
    mediaStreamRef.current = null;
    stream?.getTracks().forEach((track) => track.stop());

    stopScheduledAudio();

    const inputContext = inputAudioContextRef.current;
    inputAudioContextRef.current = null;
    if (inputContext && inputContext.state !== 'closed') {
      void inputContext.close().catch(() => undefined);
    }

    const outputContext = outputAudioContextRef.current;
    outputAudioContextRef.current = null;
    if (outputContext && outputContext.state !== 'closed') {
      void outputContext.close().catch(() => undefined);
    }
  }, [stopScheduledAudio]);

  useEffect(() => {
    return () => {
      endingRef.current = true;
      callRunIdRef.current = null;
      cleanupCallResources();
    };
  }, [cleanupCallResources]);

  const appendTranscript = useCallback((entry: TranscriptEntry) => {
    if (!entry.text.trim()) return;
    setTranscript((prev) => [...prev, entry]);
  }, [setTranscript]);

  const playAudioPayload = useCallback(async (payload: ArrayBuffer | Blob) => {
    const arrayBuffer = payload instanceof Blob ? await payload.arrayBuffer() : payload;
    if (arrayBuffer.byteLength < 2) return;

    const AudioContextClass = getAudioContextClass();
    if (!AudioContextClass) {
      setError('This browser cannot play live call audio.');
      return;
    }

    let audioContext = outputAudioContextRef.current;
    if (!audioContext || audioContext.state === 'closed') {
      audioContext = new AudioContextClass();
      outputAudioContextRef.current = audioContext;
    }
    if (audioContext.state === 'suspended') {
      await audioContext.resume().catch(() => undefined);
    }

    const pcm = new Int16Array(arrayBuffer);
    const samples = pcm16ToFloat(pcm);
    const audioBuffer = audioContext.createBuffer(1, samples.length, outputSampleRateRef.current);
    const channelSamples: Float32Array<ArrayBuffer> = new Float32Array(samples.length);
    channelSamples.set(samples);
    audioBuffer.copyToChannel(channelSamples, 0);

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    scheduledSourcesRef.current.add(source);
    source.onended = () => scheduledSourcesRef.current.delete(source);

    const startAt = Math.max(audioContext.currentTime + 0.025, nextPlayTimeRef.current);
    source.start(startAt);
    nextPlayTimeRef.current = startAt + audioBuffer.duration;
    setStatus((current) => (current === 'ended' || current === 'idle' ? current : 'speaking'));
  }, [setError, setStatus]);

  const handleControlMessage = useCallback((rawMessage: string) => {
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(rawMessage) as Record<string, unknown>;
    } catch {
      return;
    }

    const type = data.type;
    if (type === 'status') {
      const nextStatus = data.status;
      if (
        nextStatus === 'connecting'
        || nextStatus === 'listening'
        || nextStatus === 'thinking'
        || nextStatus === 'speaking'
      ) {
        setStatus(nextStatus);
      }
      return;
    }

    if (type === 'transcript') {
      appendTranscript({
        role: normalizeTranscriptRole(data.role),
        text: typeof data.text === 'string' ? data.text : '',
        ts: Date.now(),
      });
      return;
    }

    if (type === 'user_started_speaking') {
      stopScheduledAudio();
      setStatus((current) => (current === 'ended' || current === 'idle' ? current : 'listening'));
      return;
    }

    if (type === 'audio_done') {
      setStatus((current) => (current === 'ended' || current === 'idle' ? current : 'listening'));
      return;
    }

    if (type === 'warning') {
      const message = typeof data.message === 'string' ? data.message : '';
      if (message) setError(message);
      return;
    }

    if (type === 'error') {
      const message = typeof data.message === 'string' && data.message
        ? data.message
        : 'Voice call failed. Please try again.';
      endingRef.current = true;
      setError(message);
      setStatus('idle');
      cleanupCallResources();
    }
  }, [appendTranscript, cleanupCallResources, setError, setStatus, stopScheduledAudio]);

  const connectMicrophone = useCallback((
    stream: MediaStream,
    inputContext: AudioContext,
    websocket: WebSocket,
  ) => {
    const source = inputContext.createMediaStreamSource(stream);
    const processor = inputContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (event) => {
      if (isMutedRef.current || websocket.readyState !== WebSocket.OPEN) return;

      const input = event.inputBuffer.getChannelData(0);
      const resampled = resampleAudio(input, inputContext.sampleRate, INPUT_SAMPLE_RATE);
      const pcm = floatToPcm16(resampled);
      websocket.send(pcm);
    };

    source.connect(processor);
    processor.connect(inputContext.destination);
    mediaSourceRef.current = source;
    processorRef.current = processor;
  }, []);

  const startCall = useCallback(async () => {
    if (status !== 'idle' && status !== 'ended') return;

    const runId = createClientRunId();
    callRunIdRef.current = runId;
    endingRef.current = false;
    cleanupCallResources();
    setStatus('connecting');
    setTranscript([]);
    setError(null);
    setIsMuted(false);

    try {
      const AudioContextClass = getAudioContextClass();
      if (!AudioContextClass) {
        throw new Error('This browser does not support live voice calls.');
      }

      const initialOutputContext = new AudioContextClass();
      outputAudioContextRef.current = initialOutputContext;
      nextPlayTimeRef.current = initialOutputContext.currentTime;
      await initialOutputContext.resume().catch(() => undefined);

      const response = isPublic
        ? await fetch(
            `${apiBase}/v2/voice/${twinId}/call-session/public${
              shareToken ? `?share_token=${encodeURIComponent(shareToken)}` : ''
            }`
          )
        : await authFetchStandalone(`${apiBase}/v2/voice/${twinId}/call-session`);

      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: 'Failed to start call' })) as { detail?: string };
        throw new Error(body.detail || 'Failed to start call');
      }

      const session = await response.json() as CallSessionResponse;
      if (!session.voice_available || !session.websocket_url) {
        throw new Error('This persona voice is not available for live calls yet.');
      }

      outputSampleRateRef.current = session.audio_output?.sample_rate || DEFAULT_OUTPUT_SAMPLE_RATE;
      setStatus('requesting_mic');

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Microphone access is not available in this browser.');
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: true,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      if (callRunIdRef.current !== runId) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const inputContext = new AudioContextClass();
      const outputContext = outputAudioContextRef.current ?? new AudioContextClass();
      await inputContext.resume().catch(() => undefined);
      await outputContext.resume().catch(() => undefined);
      mediaStreamRef.current = stream;
      inputAudioContextRef.current = inputContext;
      outputAudioContextRef.current = outputContext;
      nextPlayTimeRef.current = outputContext.currentTime;

      const websocket = new WebSocket(session.websocket_url);
      websocket.binaryType = 'arraybuffer';
      websocketRef.current = websocket;
      setStatus('connecting');

      websocket.onopen = () => {
        if (callRunIdRef.current !== runId) {
          websocket.close();
          return;
        }
        connectMicrophone(stream, inputContext, websocket);
      };

      websocket.onmessage = (event: MessageEvent<string | ArrayBuffer | Blob>) => {
        if (typeof event.data === 'string') {
          handleControlMessage(event.data);
          return;
        }
        void playAudioPayload(event.data);
      };

      websocket.onerror = () => {
        if (endingRef.current) return;
        setError('Voice connection failed. Please try again.');
      };

      websocket.onclose = () => {
        cleanupCallResources();
        if (endingRef.current) {
          return;
        }
        setStatus((current) => (current === 'idle' ? 'idle' : 'ended'));
      };
    } catch (err) {
      callRunIdRef.current = null;
      cleanupCallResources();
      const message = err instanceof Error ? err.message : 'Failed to start call';
      const denied = message.toLowerCase().includes('permission') || message.toLowerCase().includes('denied');
      setError(denied ? 'Microphone access was denied.' : message);
      setStatus('idle');
    }
  }, [
    apiBase,
    cleanupCallResources,
    connectMicrophone,
    handleControlMessage,
    isPublic,
    playAudioPayload,
    setError,
    setStatus,
    setTranscript,
    shareToken,
    status,
    twinId,
  ]);

  const endCall = useCallback(() => {
    endingRef.current = true;
    callRunIdRef.current = null;
    const websocket = websocketRef.current;
    if (websocket?.readyState === WebSocket.OPEN) {
      websocket.send(JSON.stringify({ type: 'end' }));
    }
    cleanupCallResources();
    setStatus('ended');
  }, [cleanupCallResources, setStatus]);

  const resetCall = useCallback(() => {
    endingRef.current = true;
    callRunIdRef.current = null;
    cleanupCallResources();
    setStatus('idle');
    setTranscript([]);
    setError(null);
    setIsMuted(false);
  }, [cleanupCallResources, setError, setStatus, setTranscript]);

  const toggleMute = useCallback(() => {
    setIsMuted((current) => !current);
  }, []);

  const label = statusLabel(status, isMuted);
  const active = status !== 'idle';
  const busy = status === 'requesting_mic' || status === 'connecting';
  const voiceProofLabel = voiceName?.trim()
    ? `Cloned voice: ${voiceName.trim()}`
    : 'Uses cloned voice';

  if (status === 'idle') {
    return (
      <div className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => void startCall()}
          className="inline-flex h-10 items-center gap-2 rounded-full bg-emerald-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-60"
          title={`Call ${twinName}`}
          aria-label={`Call ${twinName}`}
        >
          <Phone className="h-4 w-4" aria-hidden="true" />
          <span>Call</span>
        </button>
        {showVoiceProof && (
          <p className="max-w-64 text-center text-[11px] font-medium leading-4 text-emerald-700">
            {voiceProofLabel}
          </p>
        )}
        {error && (
          <p className="max-w-56 text-center text-xs text-red-600">{error}</p>
        )}
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={status === 'ended' ? resetCall : endCall}
        className="inline-flex h-10 items-center gap-2 rounded-full border border-black/10 bg-white px-3 text-sm font-semibold text-[#1d1d1f] shadow-sm transition hover:bg-[#f5f5f7] active:scale-95"
        aria-label={status === 'ended' ? `Reset call with ${twinName}` : `End call with ${twinName}`}
      >
        {status === 'ended' ? (
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        ) : (
          <PhoneOff className="h-4 w-4 text-red-600" aria-hidden="true" />
        )}
        <span>{status === 'ended' ? 'Call again' : label}</span>
      </button>

      {active && (
        <div className="fixed bottom-20 right-4 z-50 w-[min(360px,calc(100vw-32px))] rounded-2xl border border-black/10 bg-white/95 p-4 shadow-[0_24px_80px_rgba(15,23,42,0.22)] backdrop-blur-xl">
          <div className="flex items-start gap-3">
            <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-2xl bg-[#eef5ff] text-sm font-semibold text-[#0b3d91] ring-1 ring-black/5">
              <AvatarDisplay name={twinName} avatarUrl={avatarUrl} size={56} />
              {status === 'speaking' && (
                <span className="absolute inset-0 rounded-2xl ring-4 ring-emerald-400/30" />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-semibold text-[#111111]">{twinName}</p>
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-[#0066cc]" aria-hidden="true" />}
                {status === 'speaking' && <Volume2 className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />}
              </div>
              <p className="mt-1 truncate text-[11px] font-medium text-emerald-700" title={voiceProofLabel}>
                {voiceProofLabel}
              </p>
              <p className="mt-0.5 text-xs tabular-nums text-[#6e6e73]">
                {label}{isCallRunning(status) ? ` · ${duration}` : ''}
              </p>
            </div>
          </div>

          {error && (
            <p className="mt-3 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </p>
          )}

          {transcript.length > 0 && (
            <div className="mt-3 max-h-44 space-y-2 overflow-y-auto rounded-xl border border-black/8 bg-[#f5f5f7] p-3">
              {transcript.map((entry, index) => (
                <TranscriptLine key={`${entry.role}-${entry.ts}-${index}`} entry={entry} twinName={twinName} />
              ))}
              <div ref={transcriptEndRef} />
            </div>
          )}

          {status === 'ended' ? (
            <div className="mt-4 flex items-center justify-between gap-2">
              <p className="text-xs text-[#6e6e73]">
                {transcript.length} transcript lines
              </p>
              <button
                type="button"
                onClick={resetCall}
                className="inline-flex h-10 items-center gap-2 rounded-full bg-[#0066cc] px-4 text-sm font-semibold text-white transition hover:bg-[#0055aa] active:scale-95"
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                Call again
              </button>
            </div>
          ) : (
            <div className="mt-4 flex items-center justify-center gap-3">
              <button
                type="button"
                onClick={toggleMute}
                disabled={busy}
                className="flex h-11 w-11 items-center justify-center rounded-full border border-black/10 bg-white text-[#1d1d1f] shadow-sm transition hover:bg-[#f5f5f7] active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
                title={isMuted ? 'Unmute microphone' : 'Mute microphone'}
              >
                {isMuted ? (
                  <MicOff className="h-5 w-5 text-red-600" aria-hidden="true" />
                ) : (
                  <Mic className="h-5 w-5" aria-hidden="true" />
                )}
              </button>
              <button
                type="button"
                onClick={endCall}
                className="flex h-12 w-12 items-center justify-center rounded-full bg-red-600 text-white shadow-lg shadow-red-600/20 transition hover:bg-red-700 active:scale-95"
                aria-label="End call"
                title="End call"
              >
                <PhoneOff className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function AvatarDisplay({
  name,
  avatarUrl,
  size,
}: {
  name: string;
  avatarUrl?: string | null;
  size: number;
}) {
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        width={size}
        height={size}
        className="h-full w-full object-cover"
      />
    );
  }

  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');

  return (
    <span className="flex h-full w-full items-center justify-center select-none text-sm font-bold">
      {initials || 'P'}
    </span>
  );
}

function TranscriptLine({ entry, twinName }: { entry: TranscriptEntry; twinName: string }) {
  const isAgent = entry.role === 'agent';
  return (
    <div className={`flex gap-2 ${isAgent ? '' : 'flex-row-reverse'}`}>
      <span
        className={`mt-0.5 shrink-0 text-xs font-semibold ${isAgent ? 'text-emerald-700' : 'text-[#6e6e73]'}`}
      >
        {isAgent ? twinName.split(' ')[0] : 'You'}
      </span>
      <p className={`text-xs leading-relaxed ${isAgent ? 'text-[#1d1d1f]' : 'text-[#424245]'}`}>
        {entry.text}
      </p>
    </div>
  );
}
