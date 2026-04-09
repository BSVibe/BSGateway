import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

/** Legacy callback page — shared-cookie auth no longer needs it. Kept as redirect until route is removed. */
export function AuthCallbackPage() {
  const navigate = useNavigate();

  useEffect(() => {
    navigate('/', { replace: true });
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <p className="text-gray-500">Redirecting...</p>
    </div>
  );
}
