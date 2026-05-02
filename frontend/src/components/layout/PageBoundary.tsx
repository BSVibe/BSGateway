'use client';

import { Component, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

class PageErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; message: string }
> {
  state = { hasError: false, message: '' };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message };
  }

  render() {
    if (this.state.hasError) {
      return (
        <PageErrorFallback
          message={this.state.message}
          onReset={() => this.setState({ hasError: false, message: '' })}
        />
      );
    }
    return this.props.children;
  }
}

function PageErrorFallback({ message, onReset }: { message: string; onReset: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center min-h-[50vh] bg-surface">
      <div className="text-center p-8">
        <h1 className="text-2xl font-bold text-on-surface mb-2">{t('common.somethingWrong')}</h1>
        <p className="text-on-surface-variant mb-4">{message}</p>
        <button
          onClick={onReset}
          className="bg-primary-container text-on-primary px-4 py-2 rounded-xl hover:brightness-110 font-bold"
        >
          {t('common.tryAgain')}
        </button>
      </div>
    </div>
  );
}

export function PageBoundary({ children }: { children: ReactNode }) {
  return <PageErrorBoundary>{children}</PageErrorBoundary>;
}
