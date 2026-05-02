'use client';

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { HelpPanel } from './HelpPanel';

export function HelpButton() {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation();

  return (
    <>
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="fixed bottom-6 right-6 z-50 flex h-12 w-12 items-center justify-center rounded-full border border-gray-700 bg-gray-900 text-gray-50 shadow-lg transition-colors hover:border-amber-500 hover:bg-gray-800"
        aria-label={t('help.open')}
      >
        <span className="text-xl font-bold text-amber-500">?</span>
      </button>
      <HelpPanel open={open} onClose={() => setOpen(false)} />
    </>
  );
}
