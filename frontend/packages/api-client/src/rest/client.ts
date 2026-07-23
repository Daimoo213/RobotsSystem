/** REST API base client. */

import type { Role } from '@robots/shared-types';

const API_BASE = import.meta.env?.VITE_API_BASE || '/api';

let currentRole: Role = 'pm';
let authToken: string | null = null;

/** 将接口错误转换为用户可直接理解的中文提示。 */
function localizeApiError(status: number, body: string, statusText: string): string {
  let detail: unknown;
  try {
    detail = body ? (JSON.parse(body) as { detail?: unknown }).detail : undefined;
  } catch {
    detail = undefined;
  }

  if (typeof detail === 'string' && /[\u4e00-\u9fff]/.test(detail) && !/[A-Za-z]/.test(detail)) {
    return detail;
  }

  const messages: Record<number, string> = {
    400: '请求参数不正确，请检查后重试',
    401: '登录状态已失效，请重新登录',
    403: '没有权限执行此操作',
    404: '请求的资源不存在',
    409: '请求与当前状态冲突',
    422: '提交的数据不符合要求',
    429: '请求过于频繁，请稍后重试',
    501: '当前部署尚未配置该功能',
  };
  if (messages[status]) return messages[status];
  if (status >= 500) return '服务暂时不可用，请稍后重试';

  const normalizedStatusText = statusText && /[\u4e00-\u9fff]/.test(statusText) ? statusText : '';
  return normalizedStatusText || `接口请求失败（状态码：${status}）`;
}

export function setRole(role: Role): void {
  currentRole = role;
}

export function getRole(): Role {
  return currentRole;
}

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (token) {
    localStorage.setItem('scheduler_token', token);
  } else {
    localStorage.removeItem('scheduler_token');
  }
}

export function getAuthToken(): string | null {
  if (authToken) return authToken;
  if (typeof localStorage !== 'undefined') {
    authToken = localStorage.getItem('scheduler_token');
  }
  return authToken;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  // 注入 JWT token
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    if (res.status === 401) {
      // Token expired, clear and redirect to login
      setAuthToken(null);
      if (typeof window !== 'undefined') {
        window.location.reload();
      }
    }
    throw new Error(localizeApiError(res.status, text, res.statusText));
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    return res.json() as Promise<T>;
  }
  return res.blob() as unknown as Promise<T>;
}

export function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'PATCH',
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: 'DELETE' });
}

