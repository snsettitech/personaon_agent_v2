import { redirect } from 'next/navigation';

export default function IntegrationsPage(): never {
  redirect('/dashboard/settings');
}
