'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { LeadCaptureForm } from '@/components/widget/LeadCaptureForm';

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'https://api.personaon.com';

interface WidgetConfig {
  twin_id: string;
  persona_name: string;
  persona_avatar: string | null;
  welcome_message: string;
  lead_capture_enabled: boolean;
  lead_capture_prompt?: string;
  bubble_color: string;
  show_branding?: boolean;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export default function WidgetPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const keyPrefix = Array.isArray(params?.key) ? params.key[0] : (params?.key ?? '');
  const fullKey = searchParams?.get('key') || '';

  const visitorId = searchParams?.get('vid') || '';
  const utmSource = searchParams?.get('utm_source') || null;
  const utmMedium = searchParams?.get('utm_medium') || null;
  const utmCampaign = searchParams?.get('utm_campaign') || null;
  const utmContent = searchParams?.get('utm_content') || null;

  const [leadId, setLeadId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(`_pon_lead_${keyPrefix}`) || null;
    } catch {
      return null;
    }
  });

  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Lead capture gate — once passed in a session, skip the form on reload
  const [leadGatePassed, setLeadGatePassed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    return sessionStorage.getItem(`_pon_lead_pass_${keyPrefix}`) === '1';
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Load config
  useEffect(() => {
    if (!keyPrefix) return;
    fetch(`${API_BASE}/widget/config/${encodeURIComponent(keyPrefix)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject('Config not found')))
      .then((cfg: WidgetConfig) => {
        setConfig(cfg);
        setMessages([{ role: 'assistant', content: cfg.welcome_message }]);
      })
      .catch(() => setError('Widget not configured'));
  }, [keyPrefix]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading || !config) return;

    setInput('');
    const userMsg: Message = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/widget/chat/${config.twin_id}/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': fullKey,
        },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          lead_id: leadId || undefined,
          visitor_id: visitorId || undefined,
          utm_source: utmSource || undefined,
          utm_medium: utmMedium || undefined,
          utm_campaign: utmCampaign || undefined,
          utm_content: utmContent || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Chat failed' }));
        throw new Error(err.detail || 'Chat failed');
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error('No stream');

      const decoder = new TextDecoder();
      let assistantContent = '';
      const assistantMsg: Message = { role: 'assistant', content: '' };
      setMessages((prev) => [...prev, assistantMsg]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.token) {
                assistantContent += data.token;
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: 'assistant', content: assistantContent };
                  return updated;
                });
              }
              if (data.conversation_id) {
                setConversationId(data.conversation_id);
              }
              if (data.lead_id && !leadId) {
                setLeadId(data.lead_id);
                try {
                  sessionStorage.setItem(`_pon_lead_${keyPrefix}`, data.lead_id);
                } catch {
                  // sessionStorage blocked — lead tracking continues server-side
                }
              }
            } catch {
              // skip unparseable lines
            }
          }
        }
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Something went wrong';
      setMessages((prev) => [
        ...prev.filter((m) => m.content !== ''),
        { role: 'assistant', content: `Sorry, ${errorMsg}. Please try again.` },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  async function handleLeadSubmit(lead: { name: string; email: string }): Promise<void> {
    if (!config || !fullKey) return;
    const res = await fetch(`${API_BASE}/widget/leads`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': fullKey,
      },
      body: JSON.stringify({
        visitor_name: lead.name,
        visitor_email: lead.email,
        source_domain: typeof window !== 'undefined' ? window.location.hostname : '',
      }),
    });
    if (!res.ok) throw new Error('Failed to save your info');
    const data = await res.json();
    if (data?.lead_id) {
      sessionStorage.setItem(`_pon_lead_${keyPrefix}`, data.lead_id);
    }
    sessionStorage.setItem(`_pon_lead_pass_${keyPrefix}`, '1');
    setLeadGatePassed(true);
  }

  function handleLeadSkip(): void {
    sessionStorage.setItem(`_pon_lead_pass_${keyPrefix}`, '1');
    setLeadGatePassed(true);
  }

  if (error) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'system-ui', color: '#64748b' }}>
        {error}
      </div>
    );
  }

  if (!config) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'system-ui', color: '#94a3b8' }}>
        Loading...
      </div>
    );
  }

  if (config && config.lead_capture_enabled && !leadGatePassed) {
    return (
      <LeadCaptureForm
        prompt={config.lead_capture_prompt || 'Leave your name and email to start chatting'}
        personaName={config.persona_name}
        bubbleColor={config.bubble_color}
        onSubmit={handleLeadSubmit}
        onSkip={handleLeadSkip}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: "'Inter', system-ui, sans-serif", background: '#fafaf9' }}>
      {/* Header */}
      <div
        style={{
          padding: '14px 16px',
          background: config.bubble_color || '#F97316',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexShrink: 0,
        }}
      >
        {config.persona_avatar ? (
          <img
            src={config.persona_avatar}
            alt=""
            style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover' }}
          />
        ) : (
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: 'rgba(255,255,255,0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 14,
              fontWeight: 700,
            }}
          >
            {config.persona_name.charAt(0).toUpperCase()}
          </div>
        )}
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{config.persona_name}</div>
          {config.show_branding !== false && (
            <div style={{ fontSize: 11, opacity: 0.8 }}>Powered by PersonaOn</div>
          )}
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              maxWidth: '85%',
              padding: '10px 14px',
              borderRadius: 14,
              fontSize: 14,
              lineHeight: 1.55,
              whiteSpace: 'pre-wrap',
              ...(msg.role === 'user'
                ? {
                    alignSelf: 'flex-end',
                    background: config.bubble_color || '#F97316',
                    color: '#fff',
                    borderBottomRightRadius: 4,
                  }
                : {
                    alignSelf: 'flex-start',
                    background: '#fff',
                    color: '#1c1917',
                    border: '1px solid #e7e5e4',
                    borderBottomLeftRadius: 4,
                  }),
            }}
          >
            {msg.content || (loading && i === messages.length - 1 ? '...' : '')}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        style={{
          padding: '12px 14px',
          borderTop: '1px solid #e7e5e4',
          background: '#fff',
          display: 'flex',
          gap: 8,
          flexShrink: 0,
        }}
      >
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
          placeholder="Type a message..."
          disabled={loading}
          style={{
            flex: 1,
            border: '1px solid #d6d3d1',
            borderRadius: 10,
            padding: '9px 12px',
            fontSize: 14,
            outline: 'none',
            fontFamily: 'inherit',
          }}
        />
        <button
          onClick={sendMessage}
          disabled={loading || !input.trim()}
          style={{
            background: config.bubble_color || '#F97316',
            color: '#fff',
            border: 'none',
            borderRadius: 10,
            padding: '9px 16px',
            cursor: loading ? 'wait' : 'pointer',
            fontWeight: 600,
            fontSize: 14,
            opacity: loading || !input.trim() ? 0.6 : 1,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
