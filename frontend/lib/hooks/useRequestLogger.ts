'use client';

import { useCallback, useRef, useState, useEffect } from 'react';

export interface RequestLog {
  id: string;
  timestamp: Date;
  method: string;
  url: string;
  status?: number;
  statusText?: string;
  duration: number;
  error?: string;
  requestBody?: string;
  requestHeaders?: Record<string, string>;
  responsePreview?: string;
}

interface RequestLoggerOptions {
  maxLogs?: number;
  enabled?: boolean;
}

export function useRequestLogger(options: RequestLoggerOptions = {}) {
  const { maxLogs = 50, enabled = process.env.NODE_ENV === 'development' } = options;
  const [logs, setLogs] = useState<RequestLog[]>([]);
  const [isEnabled, setIsEnabled] = useState(enabled);
  const activeRequests = useRef<Map<string, { startTime: number; url: string; method: string; body?: string; headers?: Record<string, string> }>>(new Map());

  const logRequest = useCallback((id: string, method: string, url: string, body?: string, headers?: Record<string, string>) => {
    if (!isEnabled) return;
    
    activeRequests.current.set(id, {
      startTime: performance.now(),
      url,
      method,
      body,
      headers
    });
  }, [isEnabled]);

  const logResponse = useCallback((id: string, response: Response) => {
    if (!isEnabled) return;
    
    const request = activeRequests.current.get(id);
    if (!request) return;
    
    const duration = performance.now() - request.startTime;
    
    const log: RequestLog = {
      id,
      timestamp: new Date(),
      method: request.method,
      url: request.url,
      status: response.status,
      statusText: response.statusText,
      duration: Math.round(duration),
      requestBody: request.body,
      requestHeaders: request.headers
    };

    setLogs(prev => [log, ...prev].slice(0, maxLogs));
    activeRequests.current.delete(id);
  }, [isEnabled, maxLogs]);

  const logError = useCallback((id: string, error: Error) => {
    if (!isEnabled) return;
    
    const request = activeRequests.current.get(id);
    if (!request) return;
    
    const duration = performance.now() - request.startTime;
    
    const log: RequestLog = {
      id,
      timestamp: new Date(),
      method: request.method,
      url: request.url,
      duration: Math.round(duration),
      error: error.message,
      requestBody: request.body,
      requestHeaders: request.headers
    };

    setLogs(prev => [log, ...prev].slice(0, maxLogs));
    activeRequests.current.delete(id);
  }, [isEnabled, maxLogs]);

  const clearLogs = useCallback(() => {
    setLogs([]);
    activeRequests.current.clear();
  }, []);

  const toggleEnabled = useCallback(() => {
    setIsEnabled(prev => !prev);
  }, []);

  // Persist logs to localStorage in development
  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    
    const saved = localStorage.getItem('api_request_logs');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setLogs(parsed.map((log: any) => ({
          ...log,
          timestamp: new Date(log.timestamp)
        })));
      } catch {
        // Ignore parse errors
      }
    }
  }, []);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    
    localStorage.setItem('api_request_logs', JSON.stringify(logs.slice(0, 20)));
  }, [logs]);

  return {
    logs,
    isEnabled,
    logRequest,
    logResponse,
    logError,
    clearLogs,
    toggleEnabled
  };
}

// Utility to generate unique request IDs
export function generateRequestId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}
