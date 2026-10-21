'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardContent, Modal, useToast } from '@/components/ui';
import { useTwin } from '@/lib/context/TwinContext';
import { useAuthFetch } from '@/lib/hooks/useAuthFetch';

interface Execution {
    id: string;
    action_type: string;
    status: string;
    inputs: Record<string, any>;
    outputs: Record<string, any>;
    error_message?: string;
    execution_duration_ms?: number;
    executed_at: string;
    action_triggers?: {
        name: string;
    };
}

interface ResponseItem {
    id: string;
    status: string;
    approval_note: string;  // This is the response message
    context: {
        trigger_name?: string;
        user_message?: string;
    };
    proposed_action: {
        action_type: string;
    };
    created_at: string;
    updated_at: string;
}

export default function HistoryPage() {
    const { showToast } = useToast();
    const { activeTwin, isLoading: twinLoading } = useTwin();
    const { get } = useAuthFetch();
    const [activeTab, setActiveTab] = useState<'all' | 'responses' | 'executions'>('all');
    const [executions, setExecutions] = useState<Execution[]>([]);
    const [responses, setResponses] = useState<ResponseItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedExec, setSelectedExec] = useState<Execution | null>(null);
    const [selectedResponse, setSelectedResponse] = useState<ResponseItem | null>(null);

    const twinId = activeTwin?.id;

    const fetchData = useCallback(async () => {
        if (!twinId) return;
        setLoading(true);
        try {
            // Fetch executions
            const execRes = await get(`/twins/${twinId}/executions?limit=100`);
            if (execRes.ok) setExecutions(await execRes.json());

            // Fetch responded drafts
            const respRes = await get(`/twins/${twinId}/action-drafts-all?status=responded&limit=100`);
            if (respRes.ok) setResponses(await respRes.json());
        } catch (err) {
            console.error('Fetch error:', err);
        } finally {
            setLoading(false);
        }
    }, [twinId, get]);

    useEffect(() => {
        if (twinId) {
            fetchData();
        } else if (!twinLoading) {
            setLoading(false);
        }
    }, [twinId, twinLoading, fetchData]);

    const getActionIcon = (type: string) => {
        switch (type) {
            case 'draft_email': return '📧';
            case 'draft_calendar_event': return '📅';
            case 'notify_owner': return '🔔';
            case 'escalate': return '⚠️';
            case 'webhook': return '🔗';
            default: return '⚡';
        }
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'success':
                return <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 text-[10px] font-black rounded-lg">Success</span>;
            case 'failed':
                return <span className="px-2 py-0.5 bg-rose-500/10 text-rose-400 text-[10px] font-black rounded-lg">Failed</span>;
            case 'responded':
                return <span className="px-2 py-0.5 bg-blue-500/10 text-blue-400 text-[10px] font-black rounded-lg">Responded</span>;
            default:
                return <span className="px-2 py-0.5 bg-slate-500/10 text-slate-400 text-[10px] font-black rounded-lg">{status}</span>;
        }
    };

    if (twinLoading) {
        return (
            <div className="flex justify-center p-20">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
            </div>
        );
    }

    if (!twinId) {
        return (
            <div className="flex items-center justify-center h-96">
                <div className="text-center max-w-md p-8">
                    <div className="w-16 h-16 bg-blue-900/50 rounded-2xl flex items-center justify-center mx-auto mb-6">
                        <svg className="w-8 h-8 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-white mb-3">No persona found</h2>
                    <p className="text-slate-400 mb-6">Create your persona first to view activity history.</p>
                    <a href="/dashboard/studio" className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition-colors">
                        Create Your Persona
                    </a>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto space-y-8 pb-20">
            <div>
                <div className="flex items-center gap-3 mb-2">
                    <Link href="/dashboard/actions" className="text-slate-500 hover:text-white transition-colors">
                        ← Actions Hub
                    </Link>
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-4xl font-black tracking-tight text-white mb-2">Activity History</h1>
                        <p className="text-slate-400 font-medium">View all responses and executed actions with full audit trail.</p>
                    </div>
                    <div className="flex gap-2">
                        {[
                            { key: 'all', label: 'All', count: executions.length + responses.length },
                            { key: 'responses', label: '💬 Responses', count: responses.length },
                            { key: 'executions', label: '⚡ Executions', count: executions.length }
                        ].map((tab) => (
                            <button
                                key={tab.key}
                                onClick={() => setActiveTab(tab.key as any)}
                                className={`px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${activeTab === tab.key
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-white/5 text-slate-400 hover:bg-white/10'
                                    }`}
                            >
                                {tab.label}
                                <span className="px-1.5 py-0.5 bg-black/20 rounded text-[10px]">{tab.count}</span>
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            <Card glass>
                <CardContent className="p-0">
                    {/* Responses Section */}
                    {(activeTab === 'all' || activeTab === 'responses') && responses.length > 0 && (
                        <>
                            {activeTab === 'all' && (
                                <div className="p-4 bg-blue-500/5 border-b border-white/5">
                                    <span className="text-xs font-black text-blue-400 uppercase tracking-widest">Your Responses</span>
                                </div>
                            )}
                            <div className="divide-y divide-white/5">
                                {responses.map((resp) => (
                                    <div
                                        key={resp.id}
                                        onClick={() => setSelectedResponse(resp)}
                                        className="p-5 hover:bg-white/5 transition-colors cursor-pointer"
                                    >
                                        <div className="flex items-start justify-between">
                                            <div className="flex items-start gap-4">
                                                <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center text-xl">
                                                    💬
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <span className="font-bold text-white">
                                                            {resp.context.trigger_name || 'Response'}
                                                        </span>
                                                        {getStatusBadge('responded')}
                                                    </div>
                                                    {resp.context.user_message && (
                                                        <div className="text-xs text-slate-500 mt-1 max-w-md truncate">
                                                            Q: "{resp.context.user_message}"
                                                        </div>
                                                    )}
                                                    <div className="mt-1 p-2 bg-blue-500/10 border border-blue-500/20 rounded-lg text-sm text-blue-200 max-w-lg">
                                                        A: "{resp.approval_note?.substring(0, 100)}{resp.approval_note?.length > 100 ? '...' : ''}"
                                                    </div>
                                                    <div className="text-xs text-slate-500 mt-2">
                                                        {new Date(resp.updated_at || resp.created_at).toLocaleString()}
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="text-slate-500">
                                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7"></path>
                                                </svg>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {/* Executions Section */}
                    {(activeTab === 'all' || activeTab === 'executions') && executions.length > 0 && (
                        <>
                            {activeTab === 'all' && (
                                <div className="p-4 bg-blue-500/5 border-b border-white/5">
                                    <span className="text-xs font-black text-blue-400 uppercase tracking-widest">Executed Actions</span>
                                </div>
                            )}
                            <div className="divide-y divide-white/5">
                                {executions.map((exec) => (
                                    <div
                                        key={exec.id}
                                        onClick={() => setSelectedExec(exec)}
                                        className="p-5 hover:bg-white/5 transition-colors cursor-pointer"
                                    >
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-4">
                                                <div className="w-10 h-10 rounded-xl bg-slate-800/50 flex items-center justify-center text-xl">
                                                    {getActionIcon(exec.action_type)}
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <span className="font-bold text-white capitalize">
                                                            {exec.action_type.replace(/_/g, ' ')}
                                                        </span>
                                                        {getStatusBadge(exec.status)}
                                                    </div>
                                                    <div className="text-xs text-slate-500 mt-1 flex items-center gap-2">
                                                        <span>{new Date(exec.executed_at).toLocaleString()}</span>
                                                        {exec.execution_duration_ms && (
                                                            <span className="text-slate-600">• {exec.execution_duration_ms}ms</span>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="text-slate-500">
                                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7"></path>
                                                </svg>
                                            </div>
                                        </div>
                                        {exec.error_message && (
                                            <div className="mt-3 p-2 bg-rose-950/30 border border-rose-500/20 rounded-lg text-xs text-rose-400 truncate">
                                                {exec.error_message}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {/* Empty State */}
                    {((activeTab === 'all' && executions.length === 0 && responses.length === 0) ||
                        (activeTab === 'responses' && responses.length === 0) ||
                        (activeTab === 'executions' && executions.length === 0)) && (
                            <div className="p-16 text-center">
                                <div className="text-5xl mb-4">📜</div>
                                <h3 className="text-xl font-bold text-white mb-2">No Activity Yet</h3>
                                <p className="text-slate-500 text-sm max-w-md mx-auto">
                                    When you respond to triggered actions or execute automations, they'll appear here.
                                </p>
                            </div>
                        )}
                </CardContent>
            </Card>

            {/* Execution Details Modal */}
            <Modal isOpen={!!selectedExec} onClose={() => setSelectedExec(null)} title="Execution Details">
                {selectedExec && (
                    <div className="space-y-5 pt-4">
                        <div className="flex items-center justify-between p-4 bg-slate-800/50 rounded-2xl">
                            <div className="flex items-center gap-3">
                                <span className="text-3xl">{getActionIcon(selectedExec.action_type)}</span>
                                <div>
                                    <div className="font-bold text-white capitalize">
                                        {selectedExec.action_type.replace(/_/g, ' ')}
                                    </div>
                                    <div className="text-xs text-slate-500 mt-0.5">
                                        {new Date(selectedExec.executed_at).toLocaleString()}
                                    </div>
                                </div>
                            </div>
                            {getStatusBadge(selectedExec.status)}
                        </div>

                        {selectedExec.error_message && (
                            <div className="p-4 bg-rose-950/30 border border-rose-500/20 rounded-xl">
                                <div className="text-[10px] font-black text-rose-400 uppercase tracking-widest mb-1">Error</div>
                                <div className="text-sm text-rose-300">{selectedExec.error_message}</div>
                            </div>
                        )}

                        <div>
                            <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2">Inputs</label>
                            <pre className="p-3 bg-slate-900 rounded-xl text-xs text-slate-400 overflow-auto max-h-40">
                                {JSON.stringify(selectedExec.inputs, null, 2)}
                            </pre>
                        </div>

                        <div>
                            <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2">Outputs</label>
                            <pre className="p-3 bg-slate-900 rounded-xl text-xs text-slate-400 overflow-auto max-h-40">
                                {JSON.stringify(selectedExec.outputs, null, 2)}
                            </pre>
                        </div>
                    </div>
                )}
            </Modal>

            {/* Response Details Modal */}
            <Modal isOpen={!!selectedResponse} onClose={() => setSelectedResponse(null)} title="Response Details">
                {selectedResponse && (
                    <div className="space-y-5 pt-4">
                        <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-2xl">
                            <div className="text-[10px] font-black text-blue-400 uppercase tracking-widest mb-2">User Asked</div>
                            <div className="text-white">"{selectedResponse.context.user_message || 'N/A'}"</div>
                        </div>

                        <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-2xl">
                            <div className="text-[10px] font-black text-emerald-400 uppercase tracking-widest mb-2">Your Response</div>
                            <div className="text-white">{selectedResponse.approval_note || 'N/A'}</div>
                        </div>

                        <div className="flex items-center justify-between p-3 bg-white/5 rounded-xl">
                            <span className="text-sm text-slate-400">Trigger</span>
                            <span className="text-sm font-bold text-white">{selectedResponse.context.trigger_name || 'Unknown'}</span>
                        </div>

                        <div className="flex items-center justify-between p-3 bg-white/5 rounded-xl">
                            <span className="text-sm text-slate-400">Responded At</span>
                            <span className="text-sm font-bold text-white">{new Date(selectedResponse.updated_at || selectedResponse.created_at).toLocaleString()}</span>
                        </div>

                        <div className="text-[10px] text-slate-600 text-center">
                            ID: {selectedResponse.id}
                        </div>
                    </div>
                )}
            </Modal>
        </div>
    );
}
