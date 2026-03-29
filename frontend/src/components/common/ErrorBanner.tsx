interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex items-center justify-between">
      <p className="text-red-400 text-sm">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-red-400 hover:text-red-300 text-sm font-medium underline"
        >
          Retry
        </button>
      )}
    </div>
  );
}
