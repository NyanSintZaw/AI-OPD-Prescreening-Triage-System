import { Navigate, useLocation } from 'react-router-dom';
import { getAdminRole, getAdminToken, type StaffRole } from '../api/client';

interface ProtectedRouteProps {
  allowedRoles: StaffRole[];
  loginPath: string;
  children: React.ReactNode;
}

export function ProtectedRoute({ allowedRoles, loginPath, children }: ProtectedRouteProps) {
  const location = useLocation();
  const token = getAdminToken();
  const role = getAdminRole();

  if (!token || !role || !allowedRoles.includes(role)) {
    return <Navigate to={loginPath} replace state={{ from: location.pathname }} />;
  }

  return children;
}
