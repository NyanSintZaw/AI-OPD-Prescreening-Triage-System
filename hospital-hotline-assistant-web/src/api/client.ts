import type { ApiError } from './types';

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const ADMIN_TOKEN_KEY = 'hotline_admin_token';
const ADMIN_EMAIL_KEY = 'hotline_admin_email';
const ADMIN_ROLE_KEY = 'hotline_admin_role';

export type StaffRole = 'super_admin' | 'admin' | 'viewer';

function getAdminToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ADMIN_TOKEN_KEY);
}

function getAdminRole(): StaffRole | null {
  if (typeof window === 'undefined') return null;
  const role = window.localStorage.getItem(ADMIN_ROLE_KEY);
  if (role === 'super_admin' || role === 'admin' || role === 'viewer') {
    return role;
  }
  return null;
}

function getAdminEmail(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ADMIN_EMAIL_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    // Admin tokens are in-memory on the backend and vanish on restart. A 401
    // while we HAD a token means the session is stale — clear it and send
    // staff back to the right login instead of silently empty panels.
    if (response.status === 401 && token && typeof window !== 'undefined') {
      const path = window.location.pathname;
      if (path.startsWith('/admin') || path.startsWith('/nurse')) {
        setAdminSession(null, null);
        window.location.assign(
          path.startsWith('/admin') ? '/login/admin' : '/login/nurse',
        );
        throw new Error('Session expired — please log in again');
      }
    }
    let detail = response.statusText;
    try {
      const body = (await response.json()) as ApiError;
      detail = body.detail ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function setAdminToken(token: string | null): void {
  if (typeof window === 'undefined') return;
  if (token) {
    window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  }
}

function setAdminSession(
  token: string | null,
  user?: { email: string; role: StaffRole } | null,
): void {
  setAdminToken(token);
  if (typeof window === 'undefined') return;
  if (user && token) {
    window.localStorage.setItem(ADMIN_EMAIL_KEY, user.email);
    window.localStorage.setItem(ADMIN_ROLE_KEY, user.role);
  } else {
    window.localStorage.removeItem(ADMIN_EMAIL_KEY);
    window.localStorage.removeItem(ADMIN_ROLE_KEY);
  }
}

export {
  ADMIN_EMAIL_KEY,
  ADMIN_ROLE_KEY,
  ADMIN_TOKEN_KEY,
  baseUrl,
  getAdminEmail,
  getAdminRole,
  getAdminToken,
  request,
  setAdminSession,
  setAdminToken,
};
