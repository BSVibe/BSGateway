import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { DashboardPage } from './pages/DashboardPage';
import { RulesPage } from './pages/RulesPage';
import { ModelsPage } from './pages/ModelsPage';
import { IntentsPage } from './pages/IntentsPage';
import { RoutingTestPage } from './pages/RoutingTestPage';
import { UsagePage } from './pages/UsagePage';
import { AuditPage } from './pages/AuditPage';
import { LoginPage } from './pages/LoginPage';
import { useAuth } from './hooks/useAuth';
import './index.css';

function App() {
  const { isAuthenticated, login, logout } = useAuth();

  if (!isAuthenticated) {
    return (
      <BrowserRouter basename="/dashboard">
        <LoginPage onLogin={login} />
      </BrowserRouter>
    );
  }

  return (
    <BrowserRouter basename="/dashboard">
      <Routes>
        <Route element={<Layout onLogout={logout} />}>
          <Route index element={<DashboardPage />} />
          <Route path="rules" element={<RulesPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="intents" element={<IntentsPage />} />
          <Route path="test" element={<RoutingTestPage />} />
          <Route path="usage" element={<UsagePage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
