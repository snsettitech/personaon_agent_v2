import { notFound } from 'next/navigation';
import { isRuntimeFeatureEnabled } from '@/lib/features/runtimeFlags';
import { RunDetailShell } from './RunDetailShell';

export default function AdminNotificationRunPage({ params }: { params: { runId: string } }) {
  if (!isRuntimeFeatureEnabled('notificationsAgentV1')) notFound();
  return <RunDetailShell runId={params.runId} />;
}
