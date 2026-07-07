import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AdminPage } from './pages/AdminPage';
import { CallPage } from './pages/CallPage';
import { ChatPage } from './pages/ChatPage';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { NursePage } from './pages/NursePage';
import { VitalsPage } from './pages/VitalsPage';
import { ProtectedRoute } from './components/ProtectedRoute';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Navigate to="/login/nurse" replace />} />
        <Route path="/login/:portal" element={<LoginPage />} />
        <Route path="/patient" element={<LandingPage />} />
        <Route path="/vitals" element={<VitalsPage />} />
        <Route path="/call" element={<CallPage />} />
        <Route path="/chat" element={<ChatPage />} />
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
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
