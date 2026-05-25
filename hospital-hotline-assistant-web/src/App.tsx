import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AdminPage } from './pages/AdminPage';
import { CallPage } from './pages/CallPage';
import { ChatPage } from './pages/ChatPage';
import { LandingPage } from './pages/LandingPage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/call" element={<CallPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
