import { notFound } from 'next/navigation';
import { isRuntimeFeatureEnabled } from '@/lib/features/runtimeFlags';
import { NotificationsShell } from './NotificationsShell';

export default function AdminNotificationsPage() {
  if (!isRuntimeFeatureEnabled('notificationsAgentV1')) notFound();
  return <NotificationsShell />;
}
