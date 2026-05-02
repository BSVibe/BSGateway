'use client';

export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center p-8">
      <div className="w-8 h-8 border-4 border-surface-container-highest border-t-primary-container rounded-full animate-spin" />
    </div>
  );
}
