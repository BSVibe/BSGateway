import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Hook for two-step delete confirmation with auto-cancel timeout.
 * First click sets "confirming" state; second click executes the delete.
 * Auto-cancels after `timeout` ms if not confirmed.
 */
export function useDeleteConfirm(timeout = 5000) {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleDelete = useCallback(
    async (id: string, deleteFn: () => Promise<void>, onSuccess?: () => void) => {
      if (deleting === id) {
        setError(null);
        if (timerRef.current) clearTimeout(timerRef.current);
        try {
          await deleteFn();
          setDeleting(null);
          onSuccess?.();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Delete failed');
        }
      } else {
        setDeleting(id);
        setError(null);
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setDeleting(null), timeout);
      }
    },
    [deleting, timeout],
  );

  return { deleting, deleteError: error, handleDelete, setDeleteError: setError };
}
