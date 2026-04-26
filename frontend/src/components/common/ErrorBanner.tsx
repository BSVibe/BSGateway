'use client';

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="bg-error-container/20 border border-error/30 rounded-xl p-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-error text-lg">error</span>
        <p className="text-error text-sm">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-error hover:text-on-error-container text-sm font-bold underline"
        >
          Retry
        </button>
      )}
    </div>
  );
}
