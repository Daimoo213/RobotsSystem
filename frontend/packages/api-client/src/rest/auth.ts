/** REST API: Auth — 登录认证 */

import { apiFetch, apiPost, apiGet } from './client';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  role: 'pm' | 'om';
  display_name: string;
  username: string;
}

export interface UserInfo {
  id: string;
  username: string;
  role: 'pm' | 'om';
  display_name: string;
}

export interface InitialUser {
  username: string;
  display_name: string;
  password: string;
}

export interface InitialSetupRequest {
  project_code: string;
  project_name: string;
  location?: string;
  map_frame?: string;
  timezone?: string;
  om: InitialUser;
  pm: InitialUser;
}

export function login(body: LoginRequest) {
  return apiPost<LoginResponse>('/auth/login', body);
}

export function getMe() {
  return apiGet<UserInfo>('/auth/me');
}

export function getSetupStatus() {
  return apiGet<{ initialized: boolean }>('/auth/setup-status');
}

export async function initialSetup(token: string, body: InitialSetupRequest) {
  return apiFetch<LoginResponse>('/auth/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Initial-Setup-Token': token },
    body: JSON.stringify(body),
  });
}
