import { useEffect, useState } from 'react';
import { LoginPage } from './pages/LoginPage';
import { InitialSetupPage } from './pages/InitialSetupPage';
import { DashboardPage } from './pages/DashboardPage';
import { useAuthStore } from './stores/authStore';
import { Loader2 } from 'lucide-react';
import { getSetupStatus } from '@robots/api-client';

export default function App() {
  const { isAuthenticated, checkAuth } = useAuthStore();
  const [checking, setChecking] = useState(true);
  const [initialized, setInitialized] = useState<boolean | null>(null);

  useEffect(() => {
    // 启动时检查 token 是否有效
    const token = localStorage.getItem('scheduler_token');
    if (token) {
      checkAuth().finally(() => setChecking(false));
    } else {
      setChecking(false);
    }
  }, []);

  useEffect(() => { getSetupStatus().then((status) => setInitialized(status.initialized)).catch(() => setInitialized(true)); }, []);

  if (checking || initialized === null) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={32} className="animate-spin text-[#2FD7FF]" />
      </div>
    );
  }

  if (!initialized) return <InitialSetupPage onInitialized={() => { setInitialized(true); window.location.reload(); }} />;

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return <DashboardPage />;
}
