import { redirect } from 'next/navigation';

// Legacy alias — preserves SPA behavior of `/intents` → `/rules`.
export default function Page() {
  redirect('/rules');
}
