'use client';

import { Component, type ReactNode } from 'react';

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
        <div className="flex items-center justify-center min-h-[50vh] bg-surface">
          <div className="text-center p-8">
            <h1 className="text-2xl font-bold text-on-surface mb-2">Something went wrong</h1>
            <p className="text-on-surface-variant mb-4">{this.state.message}</p>
            <button
              onClick={() => this.setState({ hasError: false, message: '' })}
              className="bg-primary-container text-on-primary px-4 py-2 rounded-xl hover:brightness-110 font-bold"
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function PageBoundary({ children }: { children: ReactNode }) {
  return <PageErrorBoundary>{children}</PageErrorBoundary>;
}
