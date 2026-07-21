/** Auth store — 登录认证状态管理 */

import { create } from 'zustand';
import { login as apiLogin, getMe, setAuthToken, getAuthToken, type LoginResponse } from '@robots/api-client';

interface AuthState {
  token: string | null;
  role: 'pm' | 'om' | null;
  displayName: string | null;
  username: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  checkAuth: () => Promise<boolean>;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: getAuthToken(),
  role: null,
  displayName: null,
  username: null,
  isAuthenticated: !!getAuthToken(),
  loading: false,
  error: null,

  login: async (username: string, password: string) => {
    set({ loading: true, error: null });
    try {
      const res: LoginResponse = await apiLogin({ username, password });
      setAuthToken(res.token);
      set({
        token: res.token,
        role: res.role,
        displayName: res.display_name,
        username: res.username,
        isAuthenticated: true,
        loading: false,
      });
      return true;
    } catch (e) {
      set({
        loading: false,
        error: e instanceof Error ? e.message : '登录失败',
        isAuthenticated: false,
      });
      return false;
    }
  },

  logout: () => {
    setAuthToken(null);
    set({
      token: null,
      role: null,
      displayName: null,
      username: null,
      isAuthenticated: false,
    });
  },

  checkAuth: async () => {
    const token = getAuthToken();
    if (!token) {
      set({ isAuthenticated: false });
      return false;
    }
    try {
      const me = await getMe();
      set({
        role: me.role,
        displayName: me.display_name,
        username: me.username,
        isAuthenticated: true,
      });
      return true;
    } catch {
      setAuthToken(null);
      set({ isAuthenticated: false, token: null });
      return false;
    }
  },
}));
