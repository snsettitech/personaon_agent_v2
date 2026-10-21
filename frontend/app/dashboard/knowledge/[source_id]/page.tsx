import { redirect } from 'next/navigation';

// Source details are now shown inline via the SourceDetailPanel on the knowledge page.
export default function SourceDetailRedirect() {
  redirect('/dashboard/knowledge');
}
