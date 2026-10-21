'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardContent, useToast } from '@/components/ui';
import { useTwin } from '@/lib/context/TwinContext';
import { useAuthFetch } from '@/lib/hooks/useAuthFetch';

interface Connector {
    id: string;
    connector_type: string;
    name: string;
    config: Record<string, unknown>;
    is_active: boolean;
    last_used_at?: string;
    last_error?: string;
    created_at: string;
}

const CONNECTOR_TYPES = [
    { value: 'gmail', label: 'Gmail', icon: 'G', description: 'Planned email action connector' },
    { value: 'google_calendar', label: 'Google Calendar', icon: 'Cal', description: 'Use the live calendar integration page for OAuth setup' },
    { value: 'slack', label: 'Slack', icon: '#', description: 'Planned team messaging connector' },
    { value: 'webhook', label: 'Webhook', icon: '{}', description: 'Planned custom HTTP action connector' },
    { value: 'notion', label: 'Notion', icon: 'N', description: 'Planned source and page connector' },
];

export default function ConnectorsPage() {
    const { showToast } = useToast();
    const { activeTwin, isLoading: twinLoading } = useTwin();
    const { get, post, del } = useAuthFetch();
    const [connectors, setConnectors] = useState<Connector[]>([]);
    const [loading, setLoading] = useState(true);
    const [testingId, setTestingId] = useState<string | null>(null);

    const twinId = activeTwin?.id;

    const fetchConnectors = useCallback(async () => {
        if (!twinId) return;
        try {
            const res = await get(`/twins/${twinId}/connectors`);
            if (res.ok) setConnectors(await res.json());
        } catch (err) {
            console.error('Fetch error:', err);
        } finally {
            setLoading(false);
        }
    }, [twinId, get]);

    useEffect(() => {
        if (twinId) {
            void fetchConnectors();
        } else if (!twinLoading) {
            setLoading(false);
        }
    }, [twinId, twinLoading, fetchConnectors]);

    const handleTest = async (id: string) => {
        if (!twinId) return;
        setTestingId(id);
        try {
            const res = await post(`/twins/${twinId}/connectors/${id}/test`, {});
            const data = await res.json();
            if (data.success) {
                showToast('Connection verified successfully', 'success');
            } else {
                showToast(data.error || 'Connection test failed', 'error');
            }
            void fetchConnectors();
        } catch {
            showToast('Connection test failed', 'error');
        } finally {
            setTestingId(null);
        }
    };

    const handleDelete = async (id: string) => {
        if (!twinId) return;
        if (!confirm('Are you sure you want to remove this connector?')) return;
        try {
            await del(`/twins/${twinId}/connectors/${id}`);
            showToast('Connector removed', 'success');
            void fetchConnectors();
        } catch {
            showToast('Failed to remove connector', 'error');
        }
    };

    const getConnectorInfo = (type: string) => {
        return CONNECTOR_TYPES.find((connector) => connector.value === type) || { icon: 'Plug', label: type, description: '' };
    };

    if (twinLoading) {
        return (
            <div className="flex justify-center p-20">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
            </div>
        );
    }

    if (!twinId) {
        return (
            <div className="flex items-center justify-center h-96">
                <div className="text-center max-w-md p-8">
                    <div className="w-16 h-16 bg-blue-900/50 rounded-2xl flex items-center justify-center mx-auto mb-6">
                        <svg className="w-8 h-8 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-white mb-3">No Persona Found</h2>
                    <p className="text-slate-400 mb-6">Create your persona first to configure connectors.</p>
                    <Link href="/dashboard/studio" className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition-colors">
                        Create Your Persona
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto space-y-8 pb-20">
            <div>
                <div className="flex items-center gap-3 mb-2">
                    <Link href="/dashboard/actions" className="text-slate-500 hover:text-white transition-colors">
                        Back to Actions Hub
                    </Link>
                </div>
                <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div>
                        <h1 className="text-4xl font-black tracking-tight text-white mb-2">Connectors</h1>
                        <p className="text-slate-400 font-medium">Review connected service records and manage live setup from Settings.</p>
                    </div>
                    <Link
                        href="/dashboard/settings"
                        className="inline-flex items-center justify-center px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-black transition-all shadow-lg shadow-blue-500/20"
                    >
                        Open settings
                    </Link>
                </div>
            </div>

            <Card glass className="p-5 border-blue-500/20">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                        <h2 className="text-lg font-black text-white">Live setup only</h2>
                        <p className="mt-1 text-sm text-slate-400">
                            New services are connected from Settings so users only see channels after real OAuth or API setup exists.
                        </p>
                    </div>
                    <Link
                        href="/dashboard/settings"
                        className="inline-flex shrink-0 items-center justify-center rounded-xl bg-white px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-slate-100"
                    >
                        Manage settings
                    </Link>
                </div>
            </Card>

            <Card glass>
                <CardHeader>
                    <h3 className="text-lg font-black text-white">Connected Services</h3>
                </CardHeader>
                <CardContent className="p-0">
                    {loading ? (
                        <div className="flex justify-center p-10">
                            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                        </div>
                    ) : connectors.length === 0 ? (
                        <div className="p-10 text-center">
                            <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-800 text-sm font-black text-slate-300">API</div>
                            <p className="text-slate-500 text-sm font-medium">No connectors configured</p>
                            <p className="text-slate-600 text-xs mt-1">Use Publish for website embed and Settings for account-level connections.</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-white/5">
                            {connectors.map((connector) => {
                                const info = getConnectorInfo(connector.connector_type);
                                return (
                                    <div key={connector.id} className="p-5 hover:bg-white/5 transition-colors">
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-4">
                                                <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center text-xs font-black text-slate-300">
                                                    {info.icon}
                                                </div>
                                                <div>
                                                    <div className="font-bold text-white">{connector.name}</div>
                                                    <div className="text-xs text-slate-500 mt-0.5">{info.label}</div>
                                                    {connector.last_error && (
                                                        <div className="text-xs text-rose-400 mt-1">{connector.last_error}</div>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <button
                                                    onClick={() => handleTest(connector.id)}
                                                    disabled={testingId === connector.id}
                                                    className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-white rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                                                >
                                                    {testingId === connector.id ? 'Testing' : 'Test'}
                                                </button>
                                                <button
                                                    onClick={() => handleDelete(connector.id)}
                                                    className="p-2 text-slate-500 hover:text-rose-500 transition-colors"
                                                    aria-label={`Remove ${connector.name}`}
                                                >
                                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                    </svg>
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </CardContent>
            </Card>

            <div>
                <h3 className="text-sm font-black text-slate-500 uppercase tracking-widest mb-4">Planned Connectors</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {CONNECTOR_TYPES.map((type) => {
                        const hasConnector = connectors.some((connector) => connector.connector_type === type.value);
                        return (
                            <Card key={type.value} glass className="p-5 opacity-85">
                                <div className="flex items-center gap-4">
                                    <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center text-xs font-black text-slate-300">
                                        {type.icon}
                                    </div>
                                    <div className="flex-1">
                                        <div className="font-bold text-white">{type.label}</div>
                                        <div className="text-xs text-slate-500 mt-0.5">{type.description}</div>
                                    </div>
                                    {hasConnector ? (
                                        <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 text-[10px] font-black rounded-lg">
                                            Existing
                                        </span>
                                    ) : (
                                        <span className="px-2 py-0.5 bg-white/5 text-slate-400 text-[10px] font-black rounded-lg">
                                            Planned
                                        </span>
                                    )}
                                </div>
                            </Card>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
