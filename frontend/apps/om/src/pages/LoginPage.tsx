/** O&M端 登录页 */

import { useState } from 'react';
import { useAuthStore } from '../stores/authStore';
import { Loader2, Lock, User } from 'lucide-react';

export function LoginPage() {
  const { login, loading, error } = useAuthStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await login(username, password);
  };

  return (
    <div className="flex h-full items-center justify-center" style={{ background: 'radial-gradient(circle at 50% 50%, #0A1521, #050B13)' }}>
      <div className="w-96 rounded-xl border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.9)] p-8" style={{ boxShadow: '0 0 40px rgba(47,215,255,0.15)' }}>
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-lg font-mono text-xl font-black text-[#07111C]"
            style={{ background: 'linear-gradient(135deg, #2FD7FF, #34DF9A)', boxShadow: '0 0 24px rgba(47,215,255,0.4)' }}>R</div>
          <h1 className="text-[20px] font-bold text-[#E6F6FF]">施工设备集群调度系统</h1>
          <p className="mt-1 text-[12px] text-[#79A3BF]">O&M端 · 设备集群3D调度端</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-[12px] text-[#79A3BF]">用户名</label>
            <div className="flex items-center gap-2 rounded-lg border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3">
              <User size={16} className="text-[#79A3BF]" />
              <input value={username} onChange={(e) => setUsername(e.target.value)} className="flex-1 bg-transparent py-2 text-[14px] text-[#E6F6FF] outline-none" placeholder="输入用户名" />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[12px] text-[#79A3BF]">密码</label>
            <div className="flex items-center gap-2 rounded-lg border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3">
              <Lock size={16} className="text-[#79A3BF]" />
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="flex-1 bg-transparent py-2 text-[14px] text-[#E6F6FF] outline-none" placeholder="输入密码" />
            </div>
          </div>
          {error && <div className="rounded-lg border border-[#FF5C6D] bg-[rgba(255,92,109,0.1)] px-3 py-2 text-[12px] text-[#FF5C6D]">{error}</div>}
          <button type="submit" disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#2FD7FF] py-2.5 text-[14px] font-medium text-[#050B13] transition-colors hover:bg-[#34DF9A] disabled:opacity-50">
            {loading && <Loader2 size={16} className="animate-spin" />}
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
      </div>
    </div>
  );
}
