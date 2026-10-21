'use client';

import React, { useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

interface DeleteTwinModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDelete: (permanent: boolean) => Promise<void>;
  twinName: string;
  twinHandle?: string;
  twinId: string;
}

interface TwinDataVolume {
  knowledgeCount: number;
  conversationCount: number;
  isLoading: boolean;
  error: string | null;
}

export default function DeleteTwinModal({
  isOpen,
  onClose,
  onDelete,
  twinName,
  twinHandle,
  twinId,
}: DeleteTwinModalProps) {
  const [step, setStep] = useState<'review' | 'confirm'>('review');
  const [confirmText, setConfirmText] = useState('');
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataVolume, setDataVolume] = useState<TwinDataVolume>({
    knowledgeCount: 0,
    conversationCount: 0,
    isLoading: false,
    error: null,
  });

  useEffect(() => {
    if (!isOpen || !twinId) return;
    void fetchDataVolume();
  }, [isOpen, twinId]);

  useEffect(() => {
    if (!isOpen) return;
    setStep('review');
    setConfirmText('');
    setError(null);
  }, [isOpen]);

  const fetchDataVolume = async () => {
    setDataVolume((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const [knowledgeRes, conversationsRes] = await Promise.all([
        authFetchStandalone(`/sources/${twinId}`),
        authFetchStandalone(`/conversations/${twinId}`),
      ]);

      const knowledgeCount = knowledgeRes.ok ? (await knowledgeRes.json()).length || 0 : 0;
      const conversationCount = conversationsRes.ok ? (await conversationsRes.json()).length || 0 : 0;

      setDataVolume({
        knowledgeCount,
        conversationCount,
        isLoading: false,
        error: null,
      });
    } catch {
      setDataVolume((prev) => ({
        ...prev,
        isLoading: false,
        error: 'Could not load profile data volume',
      }));
    }
  };

  if (!isOpen) return null;

  const normalized = confirmText.trim();
  const matchesName = normalized === twinName;
  const matchesHandle = twinHandle ? normalized === twinHandle : false;
  const isConfirmValid = matchesName || matchesHandle;

  const handleProceed = () => {
    setStep('confirm');
    setError(null);
  };

  const handleBack = () => {
    setStep('review');
    setError(null);
  };

  const handleReset = async () => {
    if (!isConfirmValid) {
      setError('Confirmation does not match profile name or handle');
      return;
    }

    setIsResetting(true);
    setError(null);
    try {
      await onDelete(true);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reset profile');
    } finally {
      setIsResetting(false);
    }
  };

  const totalItems = dataVolume.knowledgeCount + dataVolume.conversationCount;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">
              {step === 'review' ? 'Reset Profile' : 'Confirm Profile Reset'}
            </h2>
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="p-6">
          {step === 'review' ? (
            <>
              <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-xl">
                <p className="font-semibold text-amber-800">Reset "{twinName}"</p>
                <p className="text-sm text-amber-700 mt-1">
                  This clears profile sources, research outputs, chat history, and vectors. Your account remains.
                </p>
              </div>

              <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-xl">
                <p className="font-semibold text-blue-900 mb-3">Data Snapshot</p>
                {dataVolume.isLoading ? (
                  <p className="text-sm text-blue-600">Calculating...</p>
                ) : dataVolume.error ? (
                  <p className="text-sm text-amber-600">{dataVolume.error}</p>
                ) : (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="text-center p-3 bg-white rounded-lg">
                      <p className="text-2xl font-bold text-blue-600">{dataVolume.knowledgeCount}</p>
                      <p className="text-xs text-slate-500">Sources</p>
                    </div>
                    <div className="text-center p-3 bg-white rounded-lg">
                      <p className="text-2xl font-bold text-blue-600">{dataVolume.conversationCount}</p>
                      <p className="text-xs text-slate-500">Conversations</p>
                    </div>
                  </div>
                )}
                {!dataVolume.isLoading && (
                  <p className="mt-3 text-xs text-blue-700 text-center">
                    Estimated items to clear: <strong>{totalItems}</strong>
                  </p>
                )}
              </div>

              <div className="p-4 bg-slate-50 rounded-xl">
                <p className="font-medium text-slate-700 mb-2">After reset:</p>
                <ul className="text-sm text-slate-600 space-y-1">
                  <li>Profile returns to draft mode</li>
                  <li>Public sharing and tokens are disabled</li>
                  <li>You can run onboarding again for this profile</li>
                </ul>
              </div>
            </>
          ) : (
            <>
              <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200">
                <p className="font-semibold text-red-800">This will clear profile data.</p>
                <p className="text-sm mt-1 text-red-700">
                  Type the profile name to confirm and continue.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  Type <span className="font-bold text-slate-900">"{twinName}"</span>
                  {twinHandle ? (
                    <span>
                      {' '}or <span className="font-bold text-slate-900">"{twinHandle}"</span>
                    </span>
                  ) : null}
                  {' '}to confirm:
                </label>
                <input
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={twinHandle ? `${twinName} or ${twinHandle}` : twinName}
                  className="w-full px-4 py-3 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"
                  autoFocus
                />
              </div>

              {error && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-between">
          {step === 'confirm' ? (
            <button
              onClick={handleBack}
              className="px-4 py-2 text-slate-600 font-medium rounded-lg hover:bg-slate-200 transition-colors"
            >
              Back
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-slate-600 font-medium rounded-lg hover:bg-slate-200 transition-colors"
            >
              Cancel
            </button>
            {step === 'review' ? (
              <button
                onClick={handleProceed}
                className="px-6 py-2 font-semibold rounded-xl transition-colors bg-amber-500 text-white hover:bg-amber-600"
              >
                Continue
              </button>
            ) : (
              <button
                onClick={handleReset}
                disabled={!isConfirmValid || isResetting}
                className="px-6 py-2 font-semibold rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-red-500 text-white hover:bg-red-600"
              >
                {isResetting ? 'Resetting...' : 'Reset Profile'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
