import { Navigate, Outlet } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';


const fetchAuthStatus = async () => {
  // Day 1 Placeholder: Do not invent backend behavior.
  // Return a mock user so the skeleton layout can be viewed without backend.
  return { id: 1, name: 'Day 1 User' };
};

export function ProtectedRoute() {
  const { data: user, isLoading, error } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: fetchAuthStatus,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background text-foreground">
        <div className="animate-pulse">Loading Application...</div>
      </div>
    );
  }

  if (error || !user) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
