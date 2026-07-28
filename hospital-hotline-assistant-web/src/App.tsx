import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AdminPage } from './pages/AdminPage';
import { AvatarDevPage } from './pages/AvatarDevPage';
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
        {/* Dev-only avatar tuning harness — not linked from any screen. */}
        <Route path="/kiosk/avatar-dev" element={<AvatarDevPage />} />
        {/* Legacy web patient routes now point at the kiosk. */}
        <Route path="/patient" element={<Navigate to="/kiosk" replace />} />
        <Route path="/chat" element={<Navigate to="/kiosk" replace />} />
        <Route path="/call" element={<Navigate to="/kiosk" replace />} />
        <Route path="/login" element={<Navigate to="/login/nurse" replace />} />
        <Route path="/login/:portal" element={<LoginPage />} />
        <Route path="/slip/:sessionId" element={<SlipPage />} />
        {/* Ops staff reach the review queue from the admin portal shortcut;
            viewers land here read-only. */}
        <Route
          path="/nurse"
          element={
            <ProtectedRoute
              allowedRoles={['admin', 'super_admin', 'viewer']}
              loginPath="/login/nurse"
            >
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
