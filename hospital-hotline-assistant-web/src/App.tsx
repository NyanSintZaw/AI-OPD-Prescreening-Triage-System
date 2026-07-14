import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AdminPage } from './pages/AdminPage';
import { KioskHome } from './pages/KioskHome';
import { KioskSession } from './pages/KioskSession';
import { LoginPage } from './pages/LoginPage';
import { NursePage } from './pages/NursePage';
import { SlipPage } from './pages/SlipPage';
import { ProtectedRoute } from './components/ProtectedRoute';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/kiosk" replace />} />
        {/* Kiosk booth — the only patient-facing experience. */}
        <Route path="/kiosk" element={<KioskHome />} />
        <Route path="/kiosk/session" element={<KioskSession />} />
        {/* Legacy web patient routes now point at the kiosk. */}
        <Route path="/patient" element={<Navigate to="/kiosk" replace />} />
        <Route path="/chat" element={<Navigate to="/kiosk" replace />} />
        <Route path="/call" element={<Navigate to="/kiosk" replace />} />
        <Route path="/login" element={<Navigate to="/login/nurse" replace />} />
        <Route path="/login/:portal" element={<LoginPage />} />
        <Route path="/slip/:sessionId" element={<SlipPage />} />
        <Route
          path="/nurse"
          element={
            <ProtectedRoute allowedRoles={['admin']} loginPath="/login/nurse">
              <NursePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute allowedRoles={['super_admin', 'viewer']} loginPath="/login/admin">
              <AdminPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/kiosk" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
