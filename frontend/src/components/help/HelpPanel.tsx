'use client';

import { useTranslation } from 'react-i18next';

interface HelpPageEntry {
  /** Translation key under `help.pages.<key>` (with `.title` and `.description`). */
  i18nKey: string;
  docLink?: string;
}

const HELP_CONTENT: Record<string, HelpPageEntry> = {
  '/dashboard': {
    i18nKey: 'dashboard',
    docLink: '/bsgateway/getting-started',
  },
  '/rules': {
    i18nKey: 'rules',
    docLink: '/bsgateway/features/routing',
  },
  '/models': {
    i18nKey: 'models',
  },
  '/routing-test': {
    i18nKey: 'routingTest',
  },
  '/usage': {
    i18nKey: 'usage',
    docLink: '/bsgateway/features/usage',
  },
  '/api-keys': {
    i18nKey: 'apiKeys',
    docLink: '/bsgateway/features/api-keys',
  },
  '/audit': {
    i18nKey: 'audit',
  },
};

const DEFAULT_HELP: HelpPageEntry = { i18nKey: 'default' };

const DOCS_BASE_URL = 'https://bsvibe.dev';

interface HelpPanelProps {
  open: boolean;
  onClose: () => void;
}

export function HelpPanel({ open, onClose }: HelpPanelProps) {
  const { t } = useTranslation();
  const pathname = typeof window !== 'undefined' ? window.location.pathname : '/';
  const entry =
    Object.entries(HELP_CONTENT).find(([path]) =>
      pathname.startsWith(path),
    )?.[1] ?? DEFAULT_HELP;

  const title = t(`help.pages.${entry.i18nKey}.title`);
  const description = t(`help.pages.${entry.i18nKey}.description`);

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        className={`fixed right-0 top-0 z-50 h-full w-80 transform border-l border-gray-700 bg-gray-900 text-gray-50 shadow-xl transition-transform duration-200 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-700 px-4 py-3">
          <h2 className="text-lg font-semibold text-amber-500">{t('help.title')}</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-gray-50"
            aria-label={t('help.close')}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>

        {/* Current page help */}
        <div className="p-4">
          <div className="mb-6 rounded-lg border border-gray-700 bg-gray-800 p-4">
            <h3 className="mb-2 text-base font-medium text-amber-500">
              {title}
            </h3>
            <p className="text-sm text-gray-300">{description}</p>
            {entry.docLink && (
              <a
                href={`${DOCS_BASE_URL}${entry.docLink}`}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex items-center gap-1 text-sm text-amber-500 hover:text-amber-400"
              >
                {t('help.viewDocs')}
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-4 w-4"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fillRule="evenodd"
                    d="M10.293 5.293a1 1 0 011.414 0l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414-1.414L12.586 11H5a1 1 0 110-2h7.586l-2.293-2.293a1 1 0 010-1.414z"
                    clipRule="evenodd"
                  />
                </svg>
              </a>
            )}
          </div>

          {/* All pages list */}
          <h3 className="mb-3 text-sm font-medium text-gray-400">
            {t('help.allPages')}
          </h3>
          <ul className="space-y-2">
            {Object.entries(HELP_CONTENT).map(([path, item]) => (
              <li key={path}>
                <a
                  href={path}
                  className={`block rounded px-3 py-2 text-sm transition-colors ${
                    pathname.startsWith(path)
                      ? 'bg-amber-500/10 text-amber-500'
                      : 'text-gray-300 hover:bg-gray-800 hover:text-gray-50'
                  }`}
                >
                  {t(`help.pages.${item.i18nKey}.title`)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
