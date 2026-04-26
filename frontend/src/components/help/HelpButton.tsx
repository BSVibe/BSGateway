'use client';

import { useState } from 'react';
import { HelpPanel } from './HelpPanel';

export function HelpButton() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="fixed bottom-6 right-6 z-50 flex h-12 w-12 items-center justify-center rounded-full border border-gray-700 bg-gray-900 text-gray-50 shadow-lg transition-colors hover:border-amber-500 hover:bg-gray-800"
        aria-label="도움말 열기"
      >
        <span className="text-xl font-bold text-amber-500">?</span>
      </button>
      <HelpPanel open={open} onClose={() => setOpen(false)} />
    </>
  );
}
