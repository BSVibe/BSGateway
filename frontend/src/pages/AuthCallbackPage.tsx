import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { auth } from '../hooks/useAuth';

export function AuthCallbackPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const user = auth.handleCallback();
    if (user) {
      // Force full reload to re-initialize auth state
      window.location.href = '/dashboard/';
    } else {
      navigate('/', { replace: true });
    }
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <p className="text-gray-500">Signing in...</p>
    </div>
  );
}
